"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""CLI cikis kodlari (scratch-only, sentetik, gercek surec + rc)."""
import os
import sqlite3
import subprocess
import sys
import time
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

HERE = TESTTMP
SYN = os.path.join(HERE, "cli_main.db")
WDB = os.path.join(HERE, "cli_w.db")
MDB = os.path.join(HERE, "cli_m.db")
for f in (SYN, WDB, MDB):
    for s in ("", "-wal", "-shm", "-journal", ".maint_lock"):
        if os.path.exists(f + s):
            os.remove(f + s)
c = sqlite3.connect(SYN)
c.execute("CREATE TABLE earthquakes (id INTEGER PRIMARY KEY, event_id TEXT UNIQUE, occurred_at TEXT NOT NULL, timestamp INTEGER NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL, depth_km REAL, magnitude REAL, magnitude_ml REAL, magnitude_mw REAL, magnitude_md REAL, location TEXT, source TEXT, region_tag TEXT, created_at TEXT DEFAULT (datetime('now')))")
c.commit()
c.close()
import deprem_izleme.db as DB
DB.WEEKLY_DB = WDB
DB.MONTHLY_DB = MDB
DB.init_weekly_db()
DB.init_monthly_db()

def cli(*args):
    p = subprocess.run([sys.executable, os.path.join(HERE, "cli_driver.py"),
                        SYN, WDB, MDB] + list(args),
                       capture_output=True, text=True, timeout=180, cwd=HERE)
    return p.returncode, (p.stdout or "") + (p.stderr or "")

# 1. basarili yazma -> rc 0
rc, out = cli("fetch", "--days", "1", "--mock-fetch", "2")
n = sqlite3.connect(SYN).execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0]
check("E1: basarili fetch rc=0 + 2 satir", rc == 0 and n == 2, f"rc={rc} n={n}")
# 2. gercek-sifir -> rc 0 (reddedilmeden ayri)
rc, out = cli("fetch", "--days", "1", "--mock-fetch", "0")
check("E2: sifir-deprem rc=0", rc == 0 and "0 yeni" in out, f"rc={rc}")
# 3. bakim reddi -> rc!=0 + acik mesaj + DB degismedi
HOLDER = os.path.join(HERE, "g1a_holder.py")
h = subprocess.Popen([sys.executable, HOLDER, SYN, "60"], cwd=HERE,
                     stdout=subprocess.PIPE, text=True)
try:
    held = False
    for _i in range(100):
        time.sleep(0.2)
        try:
            with DB.maintenance_hold(SYN):
                pass
            continue
        except DB.MaintenanceActiveError:
            held = True
            break
    check("E3-hazirlik: holder tutuyor", held)
    n0 = sqlite3.connect(SYN).execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0]
    rc, out = cli("fetch", "--days", "1", "--mock-fetch", "2", "--mock-tag", "e3")
    n1 = sqlite3.connect(SYN).execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0]
    check("E3: bakim reddi rc!=0", rc != 0, f"rc={rc}")
    check("E3: acik bakim mesaji", "akim" in out, out.strip().splitlines()[-2:])
    check("E3: DB degismedi", n1 == n0, (n0, n1))
    rc, out = cli("update", "--no-fetch")
    check("E3b: update --no-fetch bakimdan etkilenmez", rc == 0, f"rc={rc}")
finally:
    try:
        h.terminate()
        h.wait()
    except Exception:
        pass
# 4. kilit zaman asimi (hizli birim): ~1sn bekler sonra red
t0 = time.monotonic()
h = subprocess.Popen([sys.executable, HOLDER, SYN, "60"], cwd=HERE,
                     stdout=subprocess.PIPE, text=True)
try:
    time.sleep(1.5)
    from deprem_izleme.db import _MaintLock, MaintenanceActiveError
    try:
        with _MaintLock(SYN, timeout_s=1):
            _to = False
    except MaintenanceActiveError:
        _to = True
    dt = time.monotonic() - t0
    check("E4: timeout ~1sn + red", _to and 0.8 < dt < 10, f"{dt:.1f}sn")
finally:
    try:
        h.terminate()
        h.wait()
    except Exception:
        pass
# 5. GUI: bakim reddinde anlasilir hata, yanlis basari yok
import deprem_izleme.fetcher as _F
from unittest import mock as _mk
h = subprocess.Popen([sys.executable, HOLDER, SYN, "60"], cwd=HERE,
                     stdout=subprocess.PIPE, text=True)
try:
    time.sleep(1.5)
    with _mk.patch.object(_DBW := __import__("deprem_izleme.db", fromlist=["x"]), "MAIN_DB", SYN), \
         _mk.patch.object(_DBW, "WEEKLY_DB", WDB), \
         _mk.patch.object(_DBW, "MONTHLY_DB", MDB), \
         _mk.patch.object(_F, "MAIN_DB", SYN), \
         _mk.patch.object(_F, "fetch_earthquakes", return_value=[
             {"id": 91, "event_id": "g5", "occurred_at": "2026-09-02 10:00:00",
              "latitude": 40.7, "longitude": 28.5, "magnitude": 1.1,
              "source": "t"}]), \
         _mk.patch("deprem_izleme.fetcher_koeri.fetch_koeri", return_value={"quakes": [], "ok": True, "error": None}):
        from deprem_izleme.gui import DepremGUI
        app = DepremGUI()
        try:
            app.withdraw()
            import threading as _th2
            _wt = _th2.Thread(target=app._startup_fetch_worker, daemon=True)
            _wt.start()
            txt = ""
            for _i in range(300):
                try:
                    app.update()
                except Exception:
                    pass
                time.sleep(0.2)
                txt = app.dash_status.cget("text")
                if "Hata" in txt or "hatası" in txt or "Güncel" in txt:
                    break
            _wt.join(timeout=10)
            check("E5: GUI bakim hatasi gosterir",
                  "hata" in txt.lower(), txt[:90])
            check("E5: yanlis basari yok", "Güncel" not in txt, txt[:90])
        finally:
            try:
                app.destroy()
            except Exception:
                pass
finally:
    try:
        h.terminate()
        h.wait()
    except Exception:
        pass

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
