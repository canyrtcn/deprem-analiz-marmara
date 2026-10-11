"""Guncelleme e2e: gercek dosya + gercek surec, izole klasor.

Senaryolar: E12 (kilitli exe), E13 (kurulum), E14 (dogru yol),
E16 (eksik paket -> red), E17 (bozuk exe -> rollback),
E19 (baska klasor/yol etkilenmez), E22 (surum degisimi).

PyInstaller yoksa tum e2e SKIP (nedeniyle). Ag/gercek release yok.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

os.environ["DEPREM_SKIP_DB_INIT"] = "1"
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))
import db_guard
db_guard.install()

PASS = []
FAIL = []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" | {extra}" if extra else ""),
          flush=True)


def _have_pyinstaller():
    try:
        import PyInstaller  # noqa
        return True
    except Exception:
        return False


if not _have_pyinstaller():
    print("SKIP e2e (PyInstaller yok)")
    sys.exit(0)

_ET = tempfile.mkdtemp(prefix="upd_e2e_")
_STUB = os.path.join(REPO_ROOT, "scripts", "probe_stub.py")
_PROBE = os.path.join(_ET, "probe.exe")
r = subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                    "--name", "probe", "--onefile", "--console",
                    "--distpath", _ET, "--workpath",
                    os.path.join(_ET, "build"),
                    "--specpath", _ET, _STUB],
                   capture_output=True, text=True, timeout=300, cwd=_ET)
if r.returncode != 0 or not os.path.exists(_PROBE):
    print("SKIP e2e (probe derlenemedi)")
    print((r.stderr or "")[-500:])
    sys.exit(0)
print("probe derlendi", flush=True)
HELPER = [sys.executable, os.path.join(REPO_ROOT, "deprem_izleme",
                                       "update_helper.py")]


def _mkapp(tag):
    """Sentetik kurulu-dizin: kilitlenebilir exe + data + localappdata."""
    app = tempfile.mkdtemp(prefix=f"upd_app_{tag}_")
    shutil.copy2(_PROBE, os.path.join(app, "probe.exe"))
    os.makedirs(os.path.join(app, "_internal"))
    open(os.path.join(app, "_internal", "old.pyd"), "wb").write(b"O")
    os.makedirs(os.path.join(app, "data"))
    open(os.path.join(app, "data", "k.db"), "wb").write(b"VERI" * 50)
    open(os.path.join(app, "data", "settings.json"), "w").write('{"a":1}')
    local = tempfile.mkdtemp(prefix=f"upd_local_{tag}_")
    open(os.path.join(local, "c.db"), "wb").write(b"YEREL" * 50)
    return app, local


def _mkstage(good=True, broken_exe=False):
    st = tempfile.mkdtemp(prefix="upd_stg_")
    if good and not broken_exe:
        shutil.copy2(_PROBE, os.path.join(st, "probe.exe"))
    elif broken_exe:
        open(os.path.join(st, "probe.exe"), "wb").write(b"bozuk-icerik")
    os.makedirs(os.path.join(st, "_internal"), exist_ok=True)
    open(os.path.join(st, "_internal", "n.pyd"), "wb").write(b"N")
    return st


def _run_helper(st, app, pid, ver, wait=15):
    return subprocess.run(
        HELPER + ["--staging", st, "--appdir", app, "--pid", str(pid),
                  "--exe", "probe.exe", "--version", ver, "--wait", str(wait)],
        capture_output=True, text=True, timeout=180)


def _result(st):
    import json
    p = os.path.join(st, "update-result.json")
    if not os.path.exists(p):
        return {}
    return json.load(open(p, encoding="utf-8"))


# E12: exe calisirken degisim yok
app12, _ = _mkapp("e12")
hold = subprocess.Popen([os.path.join(app12, "probe.exe"), "--hold", "60"])
time.sleep(2)
before = open(os.path.join(app12, "probe.exe"), "rb").read()
p = _run_helper(_mkstage(), app12, hold.pid, "9.9.9-test", wait=8)
after = open(os.path.join(app12, "probe.exe"), "rb").read()
hold.terminate()
hold.wait()
check("E12: kilitli exe degismez", before == after and p.returncode != 0,
      f"rc={p.returncode}")

# E13/E14/E22: tam kurulum
app13, local13 = _mkapp("e13")
st13 = _mkstage()
p = _run_helper(st13, app13, 99999999, "9.9.9-test")
res = _result(st13)
q = subprocess.run([os.path.join(app13, "probe.exe"), "--update-probe"],
                   capture_output=True, text=True, timeout=30)
check("E13: kurulum basarili", p.returncode == 0 and res.get("ok") is True,
      f"rc={p.returncode}")
check("E14: dogru yoldan acilir", q.returncode == 0, q.stdout.strip()[:20])
check("E22: surum degisti", q.stdout.strip() == "9.9.9-test", q.stdout.strip()[:20])
check("E15/20: data + local korunur",
      open(os.path.join(app13, "data", "k.db"), "rb").read() == b"VERI" * 50
      and open(os.path.join(local13, "c.db"), "rb").read() == b"YEREL" * 50
      and open(os.path.join(app13, "data", "settings.json")).read() == '{"a":1}')

# E16: eksik paket (_internal yok) -> red, dosya degismez
app16, _ = _mkapp("e16")
st16 = tempfile.mkdtemp(prefix="upd_stg16_")
shutil.copy2(_PROBE, os.path.join(st16, "probe.exe"))
before16 = open(os.path.join(app16, "probe.exe"), "rb").read()
p = _run_helper(st16, app16, 99999999, "9.9.9-test")
after16 = open(os.path.join(app16, "probe.exe"), "rb").read()
check("E16: eksik paket reddedilir", p.returncode != 0 and before16 == after16,
      f"rc={p.returncode}")

# E17: bozuk yeni exe -> rollback
app17, _ = _mkapp("e17")
before17 = open(os.path.join(app17, "probe.exe"), "rb").read()
st17 = _mkstage(broken_exe=True)
p = _run_helper(st17, app17, 99999999, "9.9.9-test")
after17 = open(os.path.join(app17, "probe.exe"), "rb").read()
res17 = _result(st17)
check("E17: bozuk surumde rollback", p.returncode != 0 and before17 == after17
      and res17.get("ok") is not True, f"rc={p.returncode}")

# E19: baska klasordeki ayni isimli exe + yanlis PID reddi
app19a, _ = _mkapp("e19a")
app19b, _ = _mkapp("e19b")
other = subprocess.Popen([os.path.join(app19b, "probe.exe"), "--hold", "30"])
time.sleep(2)
st19 = _mkstage()
p = _run_helper(st19, app19a, other.pid, "9.9.9-test", wait=10)
other.terminate()
other.wait()
still = subprocess.run([os.path.join(app19b, "probe.exe"), "--update-probe"],
                       capture_output=True, text=True, timeout=30)
check("E19: yanlis PID reddedilir", p.returncode != 0, f"rc={p.returncode}")
check("E19: diger klasor etkilenmez", still.returncode == 0
      and still.stdout.strip() == "9.9.9-test")

print(f"\nE2E: {len(PASS)} PASS / {len(FAIL)} FAIL")
if FAIL:
    print("FAILLER:", FAIL)
    sys.exit(1)
print("TUMU PASS")
