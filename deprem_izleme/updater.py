"""Guvenli otomatik guncelleme - GitHub Releases + imzali manifest.

Akis:
1. check_for_updates(): son release + imza/manifest asset'lerini bulur.
2. Kullanici onaylarsa secure_update(): indir (ilerleme+iptal) ->
   manifest imzasi -> alan capraz-kontrolu -> SHA-256 -> API digest ->
   ZIP guvenlik denetimi -> staging -> yardimciyi baslat -> normal kapatma.
3. update_helper (ayri exe): PID bekle -> yedek (exe+_internal) ->
   kur (data/ korunur) -> --update-probe saglik -> baslat / rollback.

Guven ilkeleri:
- Dogrulama bitmeden indirilen kod CALISTIRILMAZ; dogrulama
  basarisizsa program KAPANMAZ.
- Ozel imza anahtari repoda/EXE'de/ZIP'te YOKTUR.
- HTTPS dogrulamasi kapatilmaz; repo/surum/boyut capraz denetlenir.
"""
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

import requests

from deprem_izleme.config import (
    APP_VERSION, GITHUB_API_LATEST, UPDATE_ASSET_NAME,
)
from deprem_izleme.update_manifest import (
    EXPECTED_REPO, MANIFEST_NAME, SIGNATURE_NAME, ZIP_NAME,
    audit_zip, check_manifest, load_manifest, sha256_file,
    verify_manifest,
)

logger = logging.getLogger(__name__)
CHECK_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 60

# v1.0.4: imzali guvenli guncelleme altyapisi kuruldu -> etkin.
UPDATER_ENABLED = True

HELPER_EXE = "update-helper.exe"


def parse_version(s):
    """'v1.2.3' / '1.2.3' -> (1, 2, 3). Bozuksa (0,)."""
    try:
        parts = str(s or "").strip().lstrip("vV").split(".")
        nums = []
        for p in parts:
            digits = "".join(ch for ch in p if ch.isdigit())
            if not digits:
                break
            nums.append(int(digits))
        return tuple(nums) if nums else (0,)
    except Exception:
        return (0,)


def is_newer(remote, local=APP_VERSION):
    """Uzak sürüm yerelden büyük mü? (eşit/bozuk -> False)."""
    try:
        r, L = parse_version(remote), parse_version(local)
        n = max(len(r), len(L))
        r = r + (0,) * (n - len(r))
        L = L + (0,) * (n - len(L))
        return r > L
    except Exception:
        return False


def check_for_updates(timeout=CHECK_TIMEOUT):
    """Son release'i denetle.

    Döner: None (sürüm bilgisi alınarak güncellik DOĞRULANDI) veya
    {"version","tag","notes","url","page","manifest_url","sig_url",
     "api_digest"} (yeni sürüm) veya
    {"error","status"} (denetlenemedi).
    status: "not_found_404" (release yok ya da özel depoya yetkisiz erişim),
    "forbidden_403" (erişim engeli/rate-limit), "empty" (boş release yanıtı),
    "network" (bağlantı hatası).
    Hiçbir durumda exception fırlatmaz. "Güncel" yalnızca None ile söylenir.
    """
    try:
        resp = requests.get(
            GITHUB_API_LATEST,
            headers={"User-Agent": "DepremAnaliz-Marmara-Updater",
                     "Accept": "application/vnd.github+json"},
            timeout=timeout,
        )
        if resp.status_code == 404:
            return {"error": ("Sürüm bilgisi alınamadı (404): henüz release "
                              "yok ya da özel depoya erişim izni yok."),
                    "status": "not_found_404"}
        if resp.status_code == 403:
            return {"error": ("Sürüm bilgisi alınamadı (403): erişim engellendi "
                              "veya API hız sınırı aşıldı."),
                    "status": "forbidden_403"}
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            return {"error": "Sürüm yanıtı çözümlenemedi (boş/bozuk JSON).",
                    "status": "empty"}
        tag = (data or {}).get("tag_name", "")
        if not tag:
            return {"error": "Release yanıtı boş (sürüm etiketi yok).",
                    "status": "empty"}
        if not is_newer(tag):
            return None
        assets = {}
        for asset in data.get("assets", []) or []:
            assets[asset.get("name")] = asset
        url = (assets.get(UPDATE_ASSET_NAME) or {}).get("browser_download_url")
        digest = (assets.get(UPDATE_ASSET_NAME) or {}).get("digest")
        return {
            "version": tag.lstrip("vV"),
            "tag": tag,
            "notes": (data.get("body") or "").strip()[:1500],
            "url": url,
            "page": data.get("html_url", ""),
            "manifest_url": (assets.get(MANIFEST_NAME) or {}).get(
                "browser_download_url"),
            "sig_url": (assets.get(SIGNATURE_NAME) or {}).get(
                "browser_download_url"),
            "api_digest": digest,
        }
    except Exception as e:
        from deprem_izleme.errors import redact
        logger.info(f"Güncelleme denetimi atlandı: {redact(e)}")
        return {"error": f"Sürüm denetlenemedi (bağlantı hatası): {redact(e)}"[:150],
                "status": "network"}


def _app_dir():
    """Uygulama klasörü (exe'nin yanı / proje kökü)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    from deprem_izleme.config import BASE_DIR
    return BASE_DIR


def download_file(url, dest, progress_cb=None, cancel=None,
                  timeout=DOWNLOAD_TIMEOUT, max_mb=500, expected_size=None,
                  retries=3):
    """Dosya indir (ilerleme bayt, iptal kontrolu, retry+resume).

    Donus: (True, "") | (False, neden). neden: 'iptal' | 'ag-hatasi: ...' |
    'boyut-uyusmazligi' | 'sunucu-hatasi: ...'.
    Kismi indirme sessizce basarili SAYILMAZ: beklenen boyut tutmazsa red.
    """
    def _report(n):
        if progress_cb is not None:
            try:
                progress_cb(n)
            except Exception:
                pass
    last_err = ""
    for attempt in range(max(1, int(retries))):
        try:
            have = 0
            if os.path.exists(dest):
                try:
                    have = os.path.getsize(dest)
                except Exception:
                    have = 0
            headers = {"User-Agent": "DepremAnaliz-Marmara-Updater"}
            mode = "wb"
            if have > 0:
                headers["Range"] = f"bytes={have}-"
                mode = "ab"
            with requests.get(url, stream=True, timeout=timeout,
                              headers=headers) as r:
                if r.status_code == 416:
                    # Aralık gecersiz (dosya tam inmis olabilir)
                    if (expected_size and have == expected_size):
                        _report(have)
                        return True, ""
                    try:
                        os.remove(dest)
                    except Exception:
                        pass
                    have, mode = 0, "wb"
                    continue
                if r.status_code not in (200, 206):
                    r.raise_for_status()
                if r.status_code == 206:
                    # Content-Range dogrulamasi: sunucu istedigimiz
                    # aralik disinda bayt donduruyorsa bastan basla.
                    try:
                        cr = r.headers.get("Content-Range") or ""
                        # bicim: "bytes <ilk>-<son>/<toplam>"
                        if cr.startswith("bytes "):
                            first = int(cr.split(" ")[1].split("-")[0])
                            if first != have:
                                have, mode = 0, "wb"
                                try:
                                    os.remove(dest)
                                except Exception:
                                    pass
                                continue
                    except Exception:
                        pass
                if r.status_code == 200 and have > 0:
                    # Sunucu resume desteklemiyor: bastan basla.
                    have, mode = 0, "wb"
                size = have
                with open(dest, mode) as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if cancel is not None and cancel():
                            return False, "iptal"
                        if chunk:
                            size += len(chunk)
                            if size > max_mb * 1024 * 1024:
                                return False, "boyut-siniri"
                            f.write(chunk)
                        _report(size)
            want = expected_size
            if want is None:
                try:
                    want = int(r.headers.get("Content-Length") or 0) or None
                    if want and have > 0 and r.status_code == 206:
                        want = None  # kismi yanitta toplam belirsiz
                except Exception:
                    want = None
            if want and size != want:
                last_err = (f"boyut-uyusmazligi (indirilen={size}, "
                            f"beklenen={want})")
                time.sleep(1.0)
                continue
            return True, ""
        except Exception as e:
            last_err = f"ag-hatasi: {e}"[:160]
            time.sleep(1.5)
    return False, (last_err or "ag-hatasi: bilinmiyor")


def download_package(url, timeout=DOWNLOAD_TIMEOUT, max_mb=500,
                     progress_cb=None, cancel=None):
    """Release zip'ini indir, dosya yolunu döndür (hata/iptal: None)."""
    try:
        tmp = tempfile.mkdtemp(prefix="deprem_update_")
        dst = os.path.join(tmp, UPDATE_ASSET_NAME)
        ok, _why = download_file(url, dst, progress_cb=progress_cb,
                                 cancel=cancel, timeout=timeout,
                                 max_mb=max_mb)
        if ok:
            return dst
        return None
    except Exception as e:
        logger.error(f"Güncelleme indirilemedi: {e}")
        return None


def _safe_extract(zip_path, dest):
    """Zip-slip korumalı çıkarma (kötü niyetli yolları reddeder)."""
    with zipfile.ZipFile(zip_path, "r") as z:
        for member in z.infolist():
            target = os.path.normpath(os.path.join(dest, member.filename))
            if not target.startswith(os.path.abspath(dest) + os.sep):
                raise RuntimeError(f"Güvensiz paket yolu: {member.filename}")
        z.extractall(dest)


def stage_package(zip_path):
    """Zip'i aç, içindeki uygulama klasörünü bul.

    Donus: (yol, "") | (None, neden). neden: 'bozuk' (gecersiz ZIP) |
    'guvenlik: ...' (yol denetimi) | 'ic-hata: ...' (uygulama hatasi).
    Cagri yerleri mesaji oldugu gibi gosterir (yanlis 'bozuk' yok).
    """
    try:
        tmp = tempfile.mkdtemp(prefix="deprem_stage_")
        try:
            _safe_extract(zip_path, tmp)
        except RuntimeError as e:
            # _safe_extract guvenlik reddi (yol denetimi)
            shutil.rmtree(tmp, ignore_errors=True)
            return None, f"guvenlik: {e}"
        except Exception as e:
            name = type(e).__name__
            shutil.rmtree(tmp, ignore_errors=True)
            if "BadZip" in name or "LargeZip" in name:
                return None, "bozuk"
            return None, f"ic-hata: {name}"
        # Beklenen: tek klasör içinde exe; değilse zip kökü
        entries = [os.path.join(tmp, e) for e in os.listdir(tmp)]
        dirs = [e for e in entries if os.path.isdir(e)]
        if len(dirs) == 1 and len(entries) == 1:
            return dirs[0], ""
        return tmp, ""
    except Exception as e:
        logger.error(f"Paket açılamadı: {e}")
        return None, f"ic-hata: {type(e).__name__}"


def _public_key():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey)
        from deprem_izleme.update_pubkey import PUBLISHER_PUBLIC_KEY_HEX
        return Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(PUBLISHER_PUBLIC_KEY_HEX))
    except Exception as e:
        logger.error(f"Yayıncı anahtarı yüklenemedi: {e}")
        return None


def verify_release(info, zip_path, workdir, progress_cb=None):
    """Tam dogrulama zinciri. Donus: (ok, mesaj)."""
    def prog(m):
        if progress_cb is not None:
            try:
                progress_cb(m)
            except Exception:
                pass
    try:
        prog("Bildiri indiriliyor...")
        man_path = os.path.join(workdir, MANIFEST_NAME)
        sig_path = os.path.join(workdir, SIGNATURE_NAME)
        if not info.get("manifest_url") or not info.get("sig_url"):
            return False, "Paket doğrulanamadı (bildiri yok)"
        ok, why = download_file(info["manifest_url"], man_path)
        if not ok:
            return False, f"İndirme başarısız (bildiri: {why})"
        ok, why = download_file(info["sig_url"], sig_path)
        if not ok:
            return False, f"İndirme başarısız (imza: {why})"
        try:
            manifest = load_manifest(man_path)
            with open(sig_path, "rb") as f:
                sig = f.read()
        except Exception:
            return False, "Paket doğrulanamadı (bildiri bozuk)"
        prog("İmza doğrulanıyor...")
        pub = _public_key()
        if pub is None:
            return False, "Paket doğrulanamadı (yayıncı anahtarı yok)"
        if not verify_manifest(manifest, sig, pub):
            return False, "Paket doğrulanamadı (imza geçersiz)"
        prog("Sürüm denetleniyor...")
        ok, why = check_manifest(manifest, info.get("tag", ""),
                                 zip_path, repo=EXPECTED_REPO)
        if not ok:
            return False, f"Paket doğrulanamadı ({why})"
        digest = info.get("api_digest") or ""
        if digest and "sha256:" in digest:
            want = digest.split("sha256:")[-1].strip().lower()
            if want and want != manifest["sha256"].lower():
                return False, "Paket doğrulanamadı (sunucu kaydı uyuşmuyor)"
        prog("Paket denetleniyor...")
        ok, why = audit_zip(zip_path)
        if not ok:
            return False, f"Paket doğrulanamadı ({why})"
        return True, "Paket doğrulandı"
    except Exception as e:
        return False, f"Paket doğrulanamadı ({e})"


def launch_helper(staged_root, version):
    """Guncelleme yardimcisini ayri surecte baslat. Donus: True/False."""
    try:
        if not getattr(sys, "frozen", False):
            return False
        appdir = _app_dir()
        exe_path = sys.executable
        exe_name = os.path.basename(exe_path)
        if sys.platform != "win32":
            return False
        helper = os.path.join(appdir, "_internal", HELPER_EXE)
        if not os.path.exists(helper):
            helper = os.path.join(appdir, HELPER_EXE)
        if not os.path.exists(helper):
            return False
        # Helper KENDI klasorunu kilitlemesin diye staging'e kopyalanir ve
        # oradan baslatilir. Staging (sonuc+log ile) kanit olarak kalir.
        try:
            staged_helper = os.path.join(staged_root, HELPER_EXE)
            if os.path.abspath(helper) != os.path.abspath(staged_helper):
                shutil.copy2(helper, staged_helper)
        except Exception as e:
            logger.error(f"Yardımcı hazırlanamadı: {e}")
            return False
        subprocess.Popen(
            [staged_helper, "--staging", staged_root, "--appdir", appdir,
             "--pid", str(os.getpid()), "--exe", exe_name,
             "--version", str(version)],
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, close_fds=True)
        return True
    except Exception as e:
        logger.error(f"Yardımcı başlatılamadı: {e}")
        return False


def secure_update(info, on_quit, progress_cb=None, cancel=None):
    """Tam guvenli guncelleme akisi.

    Donus: (durum, mesaj). durum: 'hazir' (yardimci baslatildi,
    kapatilabilir), 'iptal', 'hata'. Program, 'hazir' disinda
    ASLA kapatilmaz.
    """
    if not UPDATER_ENABLED:
        return "hata", ("Otomatik güncelleme kapalı. Yeni sürümü GitHub "
                        "Releases sayfasından elle indirin.")
    url = (info or {}).get("url")
    if not url:
        return "hata", "Bu sürümde hazır paket yok (elle indirin)."
    workdir = tempfile.mkdtemp(prefix="deprem_update_")
    try:
        def dl_prog(n):
            if progress_cb is not None:
                try:
                    progress_cb(("indir", n))
                except Exception:
                    pass
        zip_path = os.path.join(workdir, UPDATE_ASSET_NAME)
        if progress_cb is not None:
            try:
                progress_cb(("durum", "Güncelleme indiriliyor..."))
            except Exception:
                pass
        ok, why = download_file(url, zip_path, progress_cb=dl_prog,
                                  cancel=cancel)
        if not ok:
            if (cancel is not None and cancel()) or why == "iptal":
                return "iptal", "Güncelleme iptal edildi."
            if why == "boyut-siniri":
                return "hata", "İndirme başarısız (paket boyutu sınırı)"
            if str(why).startswith("boyut-uyusmazligi"):
                return "hata", ("İndirme tamamlanamadı (eksik veri; "
                                "bağlantınızı kontrol edip tekrar deneyin)")
            return "hata", f"İndirme başarısız ({why})"
        if progress_cb is not None:
            try:
                progress_cb(("durum", "Paket doğrulanıyor..."))
            except Exception:
                pass
        def _st(m):
            if progress_cb is not None:
                try:
                    progress_cb(("durum", m))
                except Exception:
                    pass
        ok, msg = verify_release(info, zip_path, workdir, progress_cb=_st)
        if not ok:
            return "hata", msg
        if progress_cb is not None:
            try:
                progress_cb(("durum", "Güncelleme hazırlanıyor..."))
            except Exception:
                pass
        staged, stage_why = stage_package(zip_path)
        if not staged:
            if stage_why == "bozuk":
                return "hata", "Paket açılamadı (bozuk indirme)"
            return "hata", f"Paket hazırlanamadı ({stage_why})"
        staging = tempfile.mkdtemp(prefix="deprem_stage_")
        try:
            for e in os.listdir(staged):
                shutil.move(os.path.join(staged, e),
                            os.path.join(staging, e))
        except Exception:
            return "hata", "Güncelleme hazırlanamadı (hazırlık hatası)"
        if not launch_helper(staging, info.get("version", "")):
            return "hata", "Güncelleme bu kurulumda uygulanamadı"
        if progress_cb is not None:
            try:
                progress_cb(("durum", "Uygulama yeniden başlatılacak..."))
            except Exception:
                pass
        try:
            on_quit()
        except Exception:
            pass
        return "hazir", "Güncelleme hazırlanıyor; uygulama yeniden başlayacak."
    finally:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass


# --- Geriye uyumluluk (eski adlar korunur; .bat yolu KALDIRILDI) ---
def apply_update_bat(staged_dir, on_done=None):
    """Kaldirildi: robocopy/MIR yontemi veri kaybi riski tasir."""
    logger.error("apply_update_bat kaldirildi (guvenli yardimci kullanilir)")
    return False


def download_and_apply(info, on_quit):
    """Geriye uyumluluk sarmalayıcısı -> secure_update."""
    st, msg = secure_update(info, on_quit)
    return (st == "hazir"), msg
