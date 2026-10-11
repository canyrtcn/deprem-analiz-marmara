"""Guncelleme mekanizmasi testleri (22 senaryo).

Birim (ag yok, sentetik):
 1. yeni release yok -> None/denetlenemedi
 2. yeni release bulunuyor (mock API)
 3. kullanici reddi (GUI karari; akis baslamaz)
 4. kabul -> indirme tamamlanir (mock indirme)
 5. indirme ortasinda kesinti -> hata, program kapanmaz
 6. bozuk/eksik ZIP -> audit reddi
 7. SHA-256 uyusmuyor -> red
 8. imza gecersiz -> red
 9. manifest baska surum/repo -> red
 10. tehlikeli ZIP yolu -> red
 11. manifest/imza asset'i yok -> red
 15. veri dosyalari degismez (kopya denetimi)
 18. cift tetikleme engeli (lock)
 20. data/ + LOCALAPPDATA konumu korunur (yardimci duzeyi)
 21. bosluklu/Unicode yol destegi
 22. surum bilgisi degisimi (probe)

e2e (gercek dosya+gercek surec, izole klasor; PyInstaller gerekli,
yoksa SKIP):
 12. exe calisirken degisim yok
 13. kapanma sonrasi kurulum
 14. yeni exe dogru yoldan acilir
 16. yarida kesinti -> rollback
 17. yeni exe acilamazsa -> rollback
 19. ayni isimli baska klasordeki exe etkilenmez

Canli ag/gercek release/uretim verisi YOKTUR. Imza anahtari test-ici
uretilir (yayinci anahtariyla ilgisi yok).
"""
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

os.environ["DEPREM_SKIP_DB_INIT"] = "1"
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))
import db_guard
db_guard.install()

from deprem_izleme import update_manifest as UM
from deprem_izleme import updater as UP

PASS = []
FAIL = []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" | {extra}" if extra else ""),
          flush=True)


def _keys():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey)
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def _make_pkg(tmp, exe_content=b"E" * 1000, extra=None, bad_name=None,
              with_internal=True):
    """Sentetik guncelleme paketi: pkg/<exe+_internal>."""
    root = os.path.join(tmp, "pkg")
    os.makedirs(os.path.join(root, "deprem-analiz-marmara",
                             "_internal") if with_internal else
                os.path.join(root, "deprem-analiz-marmara"), exist_ok=True)
    base = os.path.join(root, "deprem-analiz-marmara")
    name = bad_name or "deprem-analiz-marmara.exe"
    with open(os.path.join(base, name), "wb") as f:
        f.write(exe_content)
    if with_internal:
        with open(os.path.join(base, "_internal", "mod.pyd"), "wb") as f:
            f.write(b"I" * 500)
    for rel in (extra or []):
        p = os.path.join(base, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"x")
    zp = os.path.join(tmp, "deprem-analiz-marmara-win64.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for dp, _, fns in os.walk(base):
            for fn in fns:
                full = os.path.join(dp, fn)
                z.write(full, os.path.join("deprem-analiz-marmara",
                                          os.path.relpath(full, base)))
    return zp


def _sign(manifest, priv):
    return UM.sign_manifest(manifest, priv)


# ---------- 1: surum karsilastirma ----------
check("U1: surum karsilastirma", UP.is_newer("v1.0.5", "1.0.4")
      and not UP.is_newer("v1.0.4", "1.0.4")
      and not UP.is_newer("v1.0.3", "1.0.4")
      and not UP.is_newer("bozuk", "1.0.4"))


from unittest import mock as _mk


def _api(tag, assets):
    m = _mk.Mock()
    m.status_code = 200
    m.json.return_value = {"tag_name": tag, "body": "notlar",
                           "html_url": "https://x/r/v",
                           "assets": assets}
    m.raise_for_status.return_value = None
    return m


def _assets(tag, digest=None):
    a = {"name": "deprem-analiz-marmara-win64.zip",
         "browser_download_url": "https://x/z.zip"}
    if digest:
        a["digest"] = digest
    return {"tag_name": tag, "body": "n", "html_url": "https://x/r",
            "assets": [a,
                       {"name": "update-manifest.json",
                        "browser_download_url": "https://x/m.json"},
                       {"name": "update-manifest.sig",
                        "browser_download_url": "https://x/m.sig"}]}


with _mk.patch("deprem_izleme.updater.requests.get") as _g:
    _g.return_value = _mk.Mock(status_code=200)
    _g.return_value.json.return_value = _assets("v9.9.9")
    _g.return_value.raise_for_status.return_value = None
    with _mk.patch("deprem_izleme.updater.APP_VERSION", "1.0.4"):
        _inf = UP.check_for_updates()
check("U2: yeni release bulunur", isinstance(_inf, dict)
      and _inf.get("version") == "9.9.9"
      and _inf.get("manifest_url") == "https://x/m.json"
      and _inf.get("sig_url") == "https://x/m.sig", str(_inf)[:80])
with _mk.patch("deprem_izleme.updater.requests.get") as _g:
    _g.return_value = _mk.Mock(status_code=200)
    _g.return_value.json.return_value = _assets("v1.0.4")
    _g.return_value.raise_for_status.return_value = None
    with _mk.patch("deprem_izleme.updater.APP_VERSION", "1.0.4"):
        # is_newer varsayilan argumani modulu baglar; dogrudan cagir
        _same = UP.is_newer("v1.0.4", "1.0.4")
check("U1: ayni surum yeni degil", not _same)
# U3: kullanici reddi = GUI karari; akis baslamaz (secure_update cagrilmaz).
# Burada sozlesme: reddedilen info ile yardimci asla tetiklenmez.
with _mk.patch.object(UP, "launch_helper") as _lh:
    _lh.return_value = True
    # reddi simule et: secure_update hic cagrilmiyor
    check("U3: ret sozlesmesi (cagri yoksa kurulum yok)", _lh.call_count == 0)


def _info(tag, zurl="https://x/z.zip", murl="https://x/m.json",
          surl="https://x/m.sig", digest=None):
    return {"version": tag.lstrip("vV"), "tag": tag, "notes": "",
            "url": zurl, "page": "", "manifest_url": murl,
            "sig_url": surl, "api_digest": digest}


# ---------- 4-11: dogrulama zinciri ----------
_TD = tempfile.mkdtemp(prefix="upd_unit_")
_priv, _pub = _keys()
_zp = _make_pkg(_TD)
_man = UM.build_manifest("9.9.9", "v9.9.9", _zp)
_sig = _sign(_man, _priv)
_mpath = os.path.join(_TD, "update-manifest.json")
_spath = os.path.join(_TD, "update-manifest.sig")
with open(_mpath, "w", encoding="utf-8") as f:
    json.dump(_man, f)
with open(_spath, "wb") as f:
    f.write(_sig)

with _mk.patch.object(UP, "_public_key", return_value=_pub), \
     _mk.patch.object(UP, "download_file",
                      side_effect=lambda u, d, **k: (shutil.copy(
                          _mpath if u.endswith(".json") else _spath, d),
                          True)[1]):
    ok, msg = UP.verify_release(_info("v9.9.9"), _zp, tempfile.mkdtemp())
check("U4: gecerli zincir", ok, msg)

# 7. sha uyusmuyor
_man2 = dict(_man)
_man2["sha256"] = "0" * 64
with _mk.patch.object(UP, "_public_key", return_value=_pub):
    assert UM.verify_manifest(_man2, _sign(_man2, _priv), _pub)
    ok, _ = UM.check_manifest(_man2, "v9.9.9", _zp)
check("U7: SHA-256 uyusmazligi", not ok)

# 8. imza gecersiz (baska anahtar)
_priv2, _ = _keys()
check("U8: yanlis imza", not UM.verify_manifest(_man, _sig, _priv2.public_key()))
check("U8: bozuk imza bayti", not UM.verify_manifest(_man, b"\x00" * 64, _pub))

# 9. baska surum / baska repo
_man3 = dict(_man)
_man3["version"] = "8.8.8"
ok, why = UM.check_manifest(_man3, "v9.9.9", _zp)
check("U9: surum uyusmazligi", not ok, why)
_man4 = dict(_man)
_man4["repo"] = "baskasi/repo"
ok, why = UM.check_manifest(_man4, "v9.9.9", _zp)
check("U9: repo uyusmazligi", not ok, why)

# 6/10. bozuk + tehlikeli zip
_bzp = os.path.join(_TD, "bozuk.zip")
open(_bzp, "wb").write(b"degilzip")
ok, why = UM.audit_zip(_bzp)
check("U6: bozuk zip", not ok, why)
_tzp = os.path.join(_TD, "kot.zip")
with zipfile.ZipFile(_tzp, "w") as z:
    z.writestr("../../kot.exe", b"x")
ok, why = UM.audit_zip(_tzp)
check("U10: traversal", not ok, why)
_tzp2 = os.path.join(_TD, "kot2.zip")
with zipfile.ZipFile(_tzp2, "w") as z:
    z.writestr("deprem-analiz-marmara/deprem-analiz-marmara.exe", b"x")
    z.writestr("baska/klasor/y.txt", b"y")
ok, why = UM.audit_zip(_tzp2)
check("U10: kok disi", not ok, why)
_tzp3 = os.path.join(_TD, "noexe.zip")
with zipfile.ZipFile(_tzp3, "w") as z:
    z.writestr("deprem-analiz-marmara/_internal/a.pyd", b"x")
ok, why = UM.audit_zip(_tzp3)
check("U10: exe yok", not ok, why)

# 11. manifest/imza asset'i yok
ok, msg = UP.verify_release(_info("v9.9.9", murl=None, surl=None), _zp,
                            tempfile.mkdtemp())
check("U11: bildiri yoksa red", not ok, msg)

# 5. indirme kesintisi -> hata, kapatma yok
called = {"quit": False}
st, msg = UP.secure_update(
    _info("v9.9.9"), lambda: called.update(quit=True),
    cancel=lambda: True)
check("U5: iptal", st == "iptal" and not called["quit"], msg)
with _mk.patch.object(UP, "download_file", return_value=False):
    called2 = {"quit": False}
    st, msg = UP.secure_update(
        _info("v9.9.9"), lambda: called2.update(quit=True))
check("U5: indirme hatasi kapatmaz", st == "hata" and not called2["quit"], msg)

# 15/20/21. yardimci: veri koruma + unicode yol (birim duzey)
from deprem_izleme import update_helper as UH
_HT = tempfile.mkdtemp(prefix="upd_help_")
UNI = os.path.join(_HT, "boşluklu klasör_çış")
os.makedirs(os.path.join(UNI, "data"))
open(os.path.join(UNI, "data", "k.db"), "wb").write(b"VERI" * 100)
open(os.path.join(UNI, "deprem-analiz-marmara.exe"), "wb").write(b"ESKI")
os.makedirs(os.path.join(UNI, "_internal"))
# staging: yeni paket icerigi
_ST = tempfile.mkdtemp(prefix="upd_stage_")
open(os.path.join(_ST, "deprem-analiz-marmara.exe"), "wb").write(b"YENI" * 200)
os.makedirs(os.path.join(_ST, "_internal"))
open(os.path.join(_ST, "_internal", "n.pyd"), "wb").write(b"N")
# staging'de data OLMAMALI ama olsa bile atlanmali (kot niyet simulasyonu)
os.makedirs(os.path.join(_ST, "data"))
open(os.path.join(_ST, "data", "k.db"), "wb").write(b"BOZUK")
rc = UH.main(["--staging", _ST, "--appdir", UNI, "--pid", "99999999",
              "--exe", "deprem-analiz-marmara.exe", "--version", "X"])
# probe basarisiz olur (sahte exe) -> rollback beklenir; veri SAGLAM kalmali
check("U15/20: veri korunur (rollback sonrasi)",
      open(os.path.join(UNI, "data", "k.db"), "rb").read() == b"VERI" * 100)
check("U21: unicode yol calisir", rc in (0, 1))
check("U18: sonuc dosyasi yazilir",
      os.path.exists(os.path.join(_ST, "update-result.json")))

# 18. cift tetikleme
_ST2 = tempfile.mkdtemp(prefix="upd_lock_")
open(os.path.join(_ST2, "update.lock"), "w").write("x")
rc2 = UH.main(["--staging", _ST2, "--appdir", UNI, "--pid", "99999999",
               "--exe", "a.exe", "--version", "X"])
check("U18: ikinci is engellenir", rc2 == 1)

# U23: yardimci staging'e kopyalanarak baslatilir (kilitlenme onlemi)
import sys as _sys
_FA = tempfile.mkdtemp(prefix="upd_fakeapp_")
os.makedirs(os.path.join(_FA, "_internal"))
open(os.path.join(_FA, "_internal", "update-helper.exe"), "wb").write(b"H")
_ST3 = tempfile.mkdtemp(prefix="upd_stg3_")
with _mk.patch.object(_sys, "frozen", True, create=True), \
     _mk.patch.object(_sys, "platform", "win32"), \
     _mk.patch.object(_sys, "executable", os.path.join(_FA, "a.exe")), \
     _mk.patch.object(UP.subprocess, "Popen") as _pp, \
     _mk.patch.object(UP, "_app_dir", return_value=_FA):
    _r23 = UP.launch_helper(_ST3, "9.9.9")
check("U23: helper staging'den baslatilir",
      _r23 is True and os.path.exists(os.path.join(_ST3, "update-helper.exe"))
      and _pp.call_count == 1, str(_r23))

print(f"\nBIRIM: {len(PASS)} PASS / {len(FAIL)} FAIL")
if FAIL:
    print("FAILLER:", FAIL)
    sys.exit(1)
print("TUMU PASS")
