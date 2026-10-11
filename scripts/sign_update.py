"""Release imzalama araci (yayinci tarafinda calisir).

Kullanim:
    set DEPREM_SIGN_KEY=C:\\Hermes_Win\\.secrets\\update-sign.key
    python scripts/sign_update.py --zip deprem-analiz-marmara-win64.zip --tag v1.0.4

Uretir: update-manifest.json + update-manifest.sig (calisma dizininde).
Ozel anahtar ASLA repoya/EXE'ye/ZIP'e/loga yazilmaz.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from deprem_izleme.update_manifest import (
    MANIFEST_NAME, SIGNATURE_NAME, build_manifest, canonical_bytes,
    sign_manifest,
)


def _load_private(path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey)
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) != 32:
        raise ValueError("ozel anahtar 32 bayt ham Ed25519 olmali")
    return Ed25519PrivateKey.from_private_bytes(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--key", default=os.environ.get("DEPREM_SIGN_KEY", ""))
    args = ap.parse_args()
    if not args.key or not os.path.exists(args.key):
        print("HATA: ozel anahtar bulunamadi (DEPREM_SIGN_KEY veya --key).")
        print("Anahtar repoya konmaz; guvenli konumdan verilir.")
        return 1
    priv = _load_private(args.key)
    version = str(args.tag).lstrip("vV")
    manifest = build_manifest(version, args.tag, args.zip)
    sig = sign_manifest(manifest, priv)
    with open(MANIFEST_NAME, "w", encoding="utf-8") as f:
        json.dump(manifest, f, sort_keys=True, ensure_ascii=False, indent=2)
    with open(SIGNATURE_NAME, "wb") as f:
        f.write(sig)
    print(f"manifest: {MANIFEST_NAME} (v{version})")
    print(f"imza: {SIGNATURE_NAME} ({len(sig)} bayt)")
    print(f"sha256: {manifest['sha256']}")
    print(f"boyut: {manifest['size']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
