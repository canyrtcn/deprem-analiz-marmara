"""Imzali guncelleme manifesti (Ed25519) + paket guvenlik denetimi.

Guven modeli:
- Ozel imzalama anahtari ASLA repoda/EXE'de/ZIP'te bulunmaz; yalnizca
  yayincinin erisebildigi kalici konumda saklanir (scripts/sign_update.py).
- Uygulamaya gomulu ACIK anahtar (update_pubkey.py) imzayi dogrular.
- Manifest alani (app-id, repo, surum, zip adi/boyutu/sha, tag) ile
  release etiketi ve ZIP icerigi capraz denetlenir.
- Dogrulama tamamlanmadan indirilen kod CALISTIRILMAZ.
"""
import hashlib
import io
import json
import os
import zipfile

APP_ID = "deprem-analiz-marmara"
EXPECTED_REPO = "canyrtcn/deprem-analiz-marmara"
ZIP_NAME = "deprem-analiz-marmara-win64.zip"
MANIFEST_NAME = "update-manifest.json"
SIGNATURE_NAME = "update-manifest.sig"
# Asiri buyuk/sisirilmis paketlere karsi sinirlar
MAX_ZIP_BYTES = 500 * 1024 * 1024
MAX_RATIO = 30
MAX_FILES = 20000


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(version, tag, zip_path, repo=EXPECTED_REPO):
    """Surum paketinden manifest sozlugu uret (imzasiz)."""
    st = os.stat(zip_path)
    return {
        "app": APP_ID,
        "repo": repo,
        "version": str(version),
        "tag": str(tag),
        "zip": ZIP_NAME,
        "sha256": sha256_file(zip_path),
        "size": int(st.st_size),
    }


def canonical_bytes(manifest):
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sign_manifest(manifest, private_key):
    """Ed25519 private key nesnesi -> imza bayti."""
    return private_key.sign(canonical_bytes(manifest))


def verify_manifest(manifest, signature, public_key):
    """Imza gecerli mi? (True/False; exception firlatmaz)."""
    try:
        public_key.verify(signature, canonical_bytes(manifest))
        return True
    except Exception:
        return False


def check_manifest(manifest, tag, zip_path, repo=EXPECTED_REPO):
    """Manifest alanlari release/paket ile tutarli mi? (bool, neden)."""
    try:
        if not isinstance(manifest, dict):
            return False, "manifest bicimi bozuk"
        if manifest.get("app") != APP_ID:
            return False, "uygulama kimligi uyusmuyor"
        if manifest.get("repo") != repo:
            return False, "repo kimligi uyusmuyor"
        if str(manifest.get("tag", "")).lstrip("vV") != str(tag).lstrip("vV"):
            return False, "etiket/surum uyusmuyor"
        if str(manifest.get("version", "")) != str(tag).lstrip("vV"):
            return False, "surum/etiket uyusmuyor"
        if manifest.get("zip") != ZIP_NAME:
            return False, "paket adi uyusmuyor"
        try:
            if int(manifest.get("size", -1)) != int(os.stat(zip_path).st_size):
                return False, "paket boyutu uyusmuyor"
        except Exception:
            return False, "paket okunamadi"
        if str(manifest.get("sha256", "")).lower() != sha256_file(zip_path).lower():
            return False, "SHA-256 uyusmuyor"
        return True, "ok"
    except Exception as e:
        return False, f"denetim hatasi: {e}"


def audit_zip(zip_path):
    """ZIP guvenlik denetimi: traversal/symlink/yapi/sisme.

    Donus: (ok, neden). Tum girdiler 'deprem-analiz-marmara/' altinda,
    exe + _internal icermeli; asiri sikistirma orani reddedilir.
    """
    try:
        size = os.stat(zip_path).st_size
        if size > MAX_ZIP_BYTES:
            return False, "paket cok buyuk"
        with zipfile.ZipFile(zip_path, "r") as z:
            infos = z.infolist()
            if not infos or len(infos) > MAX_FILES:
                return False, "dosya sayisi anormal"
            total_uncomp = 0
            seen = set()
            has_exe = False
            for info in infos:
                name = info.filename
                if not name or name.startswith("/") or name.startswith("\\"):
                    return False, f"mutlak yol: {name[:60]}"
                if ".." in name.replace("\\", "/").split("/"):
                    return False, f"ust-dizin kacisi: {name[:60]}"
                if len(name) > 300:
                    return False, "asiri uzun yol"
                low = name.lower()
                if low in seen:
                    return False, f"yinelenen yol: {name[:60]}"
                seen.add(low)
                # symlink: unix mode bitleri
                if (info.external_attr >> 16) & 0o120000 == 0o120000:
                    return False, f"sembolik bag: {name[:60]}"
                if not name.startswith("deprem-analiz-marmara/"):
                    return False, f"beklenmeyen kok: {name[:60]}"
                if low == "deprem-analiz-marmara/deprem-analiz-marmara.exe":
                    has_exe = True
                total_uncomp += info.file_size
                if info.file_size > MAX_ZIP_BYTES:
                    return False, "sismis girdi"
            if total_uncomp > size * MAX_RATIO:
                return False, "supheli sikistirma orani (zip bomb)"
            if not has_exe:
                return False, "pakette exe yok"
            # _internal klasoru var mi?
            if not any(n.startswith("deprem-analiz-marmara/_internal/") for n in seen):
                return False, "pakette _internal yok"
            return True, "ok"
    except zipfile.BadZipFile:
        return False, "bozuk zip"
    except Exception as e:
        return False, f"denetim hatasi: {e}"


def load_manifest(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("manifest sozluk degil")
    return data
