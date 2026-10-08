"""
Otomatik güncelleme - GitHub Releases denetimi ve kurulumu.

Akış:
1. check_for_updates(): GitHub API'den son release'i sorar, sürümü
   karşılaştırır. Ağ yoksa / depo boşsa sessizce None döner.
2. Kullanıcı onaylarsa download_and_apply(): release paketini (zip)
   indirir, geçici klasöre açar, data/ hariç uygulama dosyalarını
   değiştirir.
3. Windows'ta çalışan exe kilitlidir; değişim, uygulamadan sonra
   çalışan küçük bir .bat ile yapılır (apply_update_bat + quit).

Release paketi düzeni (build.py --release üretir):
    deprem-analiz-marmara-win64.zip
    └── deprem-analiz-marmara/        <- exe yanındaki klasörün YENİ içeriği
        ├── deprem-analiz-marmara.exe
        └── _internal/...
"""
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

import requests

from deprem_izleme.config import (
    APP_VERSION, GITHUB_API_LATEST, UPDATE_ASSET_NAME,
)

logger = logging.getLogger(__name__)
CHECK_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 60


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

    Döner: None (güncel / erişilemez) veya
    {"version": "1.1.0", "notes": "...", "url": "<zip>", "page": "<release sayfası>"}.
    Hiçbir durumda exception fırlatmaz.
    """
    try:
        resp = requests.get(
            GITHUB_API_LATEST,
            headers={"User-Agent": "DepremAnaliz-Marmara-Updater",
                     "Accept": "application/vnd.github+json"},
            timeout=timeout,
        )
        if resp.status_code == 404:
            # Henüz release yok (gizli depo / ilk sürüm öncesi)
            return None
        resp.raise_for_status()
        data = resp.json()
        tag = data.get("tag_name", "")
        if not tag or not is_newer(tag):
            return None
        url = None
        for asset in data.get("assets", []) or []:
            if asset.get("name") == UPDATE_ASSET_NAME:
                url = asset.get("browser_download_url")
                break
        return {
            "version": tag.lstrip("vV"),
            "notes": (data.get("body") or "").strip()[:1500],
            "url": url,
            "page": data.get("html_url", ""),
        }
    except Exception as e:
        logger.info(f"Güncelleme denetimi atlandı: {e}")
        return None


def _app_dir():
    """Uygulama klasörü (exe'nin yanı / proje kökü)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    from deprem_izleme.config import BASE_DIR
    return BASE_DIR


def download_package(url, timeout=DOWNLOAD_TIMEOUT, max_mb=500):
    """Release zip'ini indir, dosya yolunu döndür (hata: None)."""
    try:
        tmp = tempfile.mkdtemp(prefix="deprem_update_")
        dst = os.path.join(tmp, UPDATE_ASSET_NAME)
        size = 0
        with requests.get(url, stream=True, timeout=timeout,
                          headers={"User-Agent": "DepremAnaliz-Marmara-Updater"}) as r:
            r.raise_for_status()
            with open(dst, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        size += len(chunk)
                        if size > max_mb * 1024 * 1024:
                            raise RuntimeError("Paket boyutu sınırı aştı")
                        f.write(chunk)
        return dst
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
    """Zip'i aç, içindeki uygulama klasörünü bul. (yol | None)."""
    try:
        tmp = tempfile.mkdtemp(prefix="deprem_stage_")
        _safe_extract(zip_path, tmp)
        # Beklenen: tek klasör içinde exe; değilse zip kökü
        entries = [os.path.join(tmp, e) for e in os.listdir(tmp)]
        dirs = [e for e in entries if os.path.isdir(e)]
        if len(dirs) == 1 and len(entries) == 1:
            return dirs[0]
        return tmp
    except Exception as e:
        logger.error(f"Paket açılamadı: {e}")
        return None


def apply_update_bat(staged_dir, on_done=None):
    """Değişimi uygulayacak .bat'i yazar ve başlatır, sonra uygulamayı kapatır.

    .bat: uygulamanın kapanmasını bekler, data/ HARİÇ her şeyi yeniyle
    değiştirir, uygulamayı yeniden başlatır, kendini ve geçici
    dosyaları temizler. Döner: True (bat başlatıldı).
    """
    try:
        app_dir = _app_dir()
        if getattr(sys, "frozen", False):
            exe_path = sys.executable
            exe_name = os.path.basename(exe_path)
        else:
            # Kaynaktan çalışıyorsa: güncelleme paketlenmiş sürüm içindir
            return False
        bat_path = os.path.join(tempfile.gettempdir(), "deprem_update_apply.bat")
        log_path = os.path.join(tempfile.gettempdir(), "deprem_update.log")
        with open(bat_path, 'w', encoding='utf-8') as f:
            f.write('@echo off\n')
            f.write('echo update basladi > "' + log_path + '"\n')
            # Uygulama kapanana kadar bekle (en fazla ~60 sn)
            f.write('for /L %%i in (1,1,60) do (\n')
            f.write('  tasklist /FI "IMAGENAME eq ' + exe_name + '" 2>NUL | find /I "' + exe_name + '" >NUL\n')
            f.write('  if errorlevel 1 goto swapped\n')
            f.write('  timeout /t 1 /nobreak >NUL\n')
            f.write(')\n')
            f.write(':swapped\n')
            # data/ hariç her şeyi değiştir (MIR: silinen dosyalar da temizlenir)
            f.write('robocopy "' + staged_dir + '" "' + app_dir + '" /MIR /XD data /R:2 /W:2 /NFL /NDL /NJH /NJS >> "' + log_path + '" 2>&1\n')
            f.write('start "" "' + exe_path + '"\n')
            f.write('rmdir /S /Q "' + os.path.dirname(staged_dir) + '"\n')
            f.write('del "' + bat_path + '"\n')
        subprocess.Popen(["cmd", "/c", bat_path],
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if on_done:
            try:
                on_done()
            except Exception:
                pass
        return True
    except Exception as e:
        logger.error(f"Güncelleme uygulanamadı: {e}")
        return False


def download_and_apply(info, on_quit):
    """info (check_for_updates çıktısı) -> indir, sahnele, bat + kapat."""
    url = (info or {}).get("url")
    if not url:
        return False, "Bu sürümde hazır paket yok (elle indirin)."
    zip_path = download_package(url)
    if not zip_path:
        return False, "Paket indirilemedi (ağ hatası)."
    staged = stage_package(zip_path)
    if not staged:
        return False, "Paket açılamadı (bozuk indirme)."
    ok = apply_update_bat(staged, on_done=on_quit)
    if not ok:
        return False, "Güncelleme bu kurulumda uygulanamadı."
    return True, "Güncelleme uygulanıyor; uygulama yeniden başlayacak."
