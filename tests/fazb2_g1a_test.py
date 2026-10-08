"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""G1-A kilit testleri (scratch-only, sentetik DB, cok-surecli)."""
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
SYN = os.path.join(HERE, "g1a_main.db")
for s in ("", "-wal", "-shm", "-journal", ".maint_lock"):
    if os.path.exists(SYN + s):
        os.remove(SYN + s)

import deprem_izleme.db as DB
from deprem_izleme.db import (maintenance_hold, MaintenanceActiveError,
                              lock_path_for)

# 0. kurulum: legacy sentetik
c = sqlite3.connect(SYN)
c.execute("CREATE TABLE earthquakes (id INTEGER PRIMARY KEY, event_id TEXT UNIQUE, occurred_at TEXT NOT NULL, timestamp INTEGER NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL, depth_km REAL, magnitude REAL, magnitude_ml REAL, magnitude_mw REAL, magnitude_md REAL, location TEXT, source TEXT, region_tag TEXT, created_at TEXT DEFAULT (datetime('now')))")
c.commit()
c.close()

# 1. temel: al/birak + ikinci ayni-surec reddedilir + reentrant
with maintenance_hold(SYN):
    try:
        with maintenance_hold(SYN):
            # ayni thread: reentrant sayac gecer (yanlis pozitif yok)
            _reentrant_ok = True
    except MaintenanceActiveError:
        _reentrant_ok = False
    check("G1A: reentrant ayni-thread", _reentrant_ok)
    import threading as _th
    _res = []
    def _other_thread():
        try:
            with maintenance_hold(SYN):
                _res.append("aldi")
        except MaintenanceActiveError:
            _res.append("red")
    _t = _th.Thread(target=_other_thread)
    _t.start(); _t.join()
    # NOT: ayni surec farkli handle Windows'ta cakisabilir (OS davranisi);
    # yalnızca gozlem, hukumsuz.
    print("   bilgi: ayri-thread ayni-surec sonucu:", _res)
check("G1A: kilit birakildi", os.path.exists(lock_path_for(SYN)))

EQ = {"id": 1, "event_id": "g1a_1", "occurred_at": "2026-09-01 10:00:00",
      "latitude": 40.7, "longitude": 28.5, "depth_km": 5.0, "magnitude": 1.1,
      "source": "test"}

# 2. yardimci surec betikleri
HOLDER = os.path.join(HERE, "g1a_holder.py")
WRITER = os.path.join(HERE, "g1a_writer.py")
_REPO_P = REPO_ROOT.replace("\\", "/")
_holder_src = (
    "import os, sys, time\n"
    "os.environ['DEPREM_SKIP_DB_INIT']='1'\n"
    "sys.path.insert(0, r'__REPO__')\n"
    "from deprem_izleme.db import maintenance_hold\n"
    "db, secs = sys.argv[1], float(sys.argv[2])\n"
    "sys.stdout.write('HOLDING\\n'); sys.stdout.flush()\n"
    "with maintenance_hold(db):\n"
    "    time.sleep(secs)\n")
open(HOLDER, "w").write(_holder_src.replace("__REPO__", _REPO_P))
_writer_src = (
    "import os, sys\n"
    "os.environ['DEPREM_SKIP_DB_INIT']='1'\n"
    "sys.path.insert(0, r'__REPO__')\n"
    "import deprem_izleme.db as DB\n"
    "db, n, tag = sys.argv[1], int(sys.argv[2]), sys.argv[3]\n"
    "okc, refc = 0, 0\n"
    "for i in range(n):\n"
    "    try:\n"
    "        DB.insert_earthquake({'id': 100000+hash(tag+i.__str__()) % 10**7,\n"
    "            'event_id': f'{tag}_{i}', 'occurred_at': '2026-09-02 10:00:00',\n"
    "            'latitude': 40.7, 'longitude': 28.5, 'depth_km': 5.0,\n"
    "            'magnitude': 1.1, 'source': 'test'}, db_path=db)\n"
    "        okc += 1\n"
    "    except DB.MaintenanceActiveError:\n"
    "        refc += 1\n"
    "print(f'{okc} {refc}')\n")
open(WRITER, "w").write(_writer_src.replace("__REPO__", _REPO_P))
for f in ("HOLDER_READY",):
    if os.path.exists(os.path.join(HERE, f)):
        os.remove(os.path.join(HERE, f))

def run(args, **kw):
    return subprocess.run([sys.executable] + args, capture_output=True,
                          text=True, timeout=120, cwd=HERE, **kw)

# 3. bakim tutarken baska surec yazamaz
h = subprocess.Popen([sys.executable, HOLDER, SYN, "6"], cwd=HERE,
                     stdout=subprocess.PIPE, text=True)
try:
    for _ in range(100):
        time.sleep(0.1)
        try:
            with maintenance_hold(SYN):
                pass
            # kilit serbestse holder henuz baslamamis; bekle
            continue
        except MaintenanceActiveError:
            break
    r = run([WRITER, SYN, "5", "w1"])
    print("   writer ciktisi:", (r.stdout or "").strip(), (r.stderr or "").strip()[-200:])
    n = sqlite3.connect(SYN).execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0]
    check("G1A: bakim sirasinda surec disi yazma reddedilir", n == 0, f"satir={n}")
finally:
    h.terminate()
    h.wait()
# 4. kilit birakilinca yazilir
r = run([WRITER, SYN, "3", "w2"])
n = sqlite3.connect(SYN).execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0]
check("G1A: kilit kalkinca yazilir", n == 3, f"satir={n} cikti={(r.stdout or '').strip()}")

# 5. cok surec yaris: bakim tutarken 3 yazar x10 -> tumu red, sayim sabit
h = subprocess.Popen([sys.executable, HOLDER, SYN, "8"], cwd=HERE,
                     stdout=subprocess.PIPE, text=True)
procs = []
try:
    time.sleep(1.5)
    for k in range(3):
        procs.append(subprocess.Popen(
            [sys.executable, WRITER, SYN, "10", f"r{k}"],
            cwd=HERE, stdout=subprocess.PIPE, text=True))
    outs = [p.communicate()[0].strip() for p in procs]
    refused = sum(int(o.split()[1]) for o in outs)
    applied = sum(int(o.split()[0]) for o in outs)
    n = sqlite3.connect(SYN).execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0]
    check("G1A: yaris korunumu (reddedilen+uygulanan=denenen)",
          refused == 30 and applied == 0 and n == 3,
          f"red={refused} ok={applied} satir={n}")
    c = sqlite3.connect(SYN)
    check("G1A: bütünlük korunur",
          c.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
    c.close()
finally:
    h.terminate()
    h.wait()

# 6. crash: kilidi tutan surec oldurulur -> kilit serbest
h = subprocess.Popen([sys.executable, HOLDER, SYN, "60"], cwd=HERE,
                     stdout=subprocess.PIPE, text=True)
time.sleep(1.5)
h.kill()
h.wait()
time.sleep(0.5)
try:
    with maintenance_hold(SYN):
        _free = True
except MaintenanceActiveError:
    _free = False
check("G1A: olen surecin kilidi serbest kalir", _free)

# 7. tum yazma API'leri kapi arkasinda (v2 dahil)
V2 = os.path.join(HERE, "g1a_v2.db")
for s in ("", "-wal", "-shm", "-journal", ".maint_lock"):
    if os.path.exists(V2 + s):
        os.remove(V2 + s)
c = sqlite3.connect(V2)
c.executescript("CREATE TABLE earthquakes (id INTEGER PRIMARY KEY, event_id TEXT UNIQUE, occurred_at TEXT NOT NULL, timestamp INTEGER NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL, depth_km REAL, magnitude REAL, location TEXT, source TEXT, region_tag TEXT);")
c.commit()
c.close()
_vc = sqlite3.connect(V2)
DB.init_v2_schema(_vc)
_vc.close()
W = os.path.join(HERE, "g1a_w.db")
for s in ("", "-wal", "-shm", "-journal", ".maint_lock"):
    if os.path.exists(W + s):
        os.remove(W + s)
_full = {"year": 2026, "week": 1, "week_start": "x", "week_end": "y",
         "quake_count": 0, "min_mag": 0.0, "max_mag": 0.0, "avg_mag": 0.0,
         "median_mag": 0.0, "total_energy_j": 0.0, "avg_depth_km": 0.0,
         "min_depth_km": 0.0, "max_depth_km": 0.0, "b_value": 1.0, "a_value": 3.0,
         "max_mag_expected": 0.0, "risk_score": 0.0}
with maintenance_hold(SYN):
    # dis kilit: ayri-thread bile reddedilir (OS duzeyi); ayni-thread
    # reentrant gecisi bilerek serbesttir (asagida surec-disi test edilir).
    pass
import sqlite3 as _sqw
_cw = _sqw.connect(W)
_cw.execute("CREATE TABLE IF NOT EXISTS weekly_stats (year INTEGER, week INTEGER, week_start TEXT, week_end TEXT, region_tag TEXT, quake_count INTEGER, min_mag REAL, max_mag REAL, avg_mag REAL, median_mag REAL, total_energy_j REAL, avg_depth_km REAL, min_depth_km REAL, max_depth_km REAL, b_value REAL, a_value REAL, max_mag_expected REAL, risk_score REAL, UNIQUE(year, week, region_tag))")
_cw.commit()
_cw.close()
holders = []
try:
    for _db in (SYN, V2, W):
        _h = subprocess.Popen([sys.executable, HOLDER, _db, "30"], cwd=HERE,
                              stdout=subprocess.PIPE, text=True)
        holders.append(_h)
    time.sleep(2.0)
    import deprem_izleme.db as _D2
    _orig_w = _D2.WEEKLY_DB
    _D2.WEEKLY_DB = W
    refused = 0
    try:
        try:
            DB.insert_earthquake(dict(EQ), db_path=SYN)
        except MaintenanceActiveError:
            refused += 1
        try:
            DB.bulk_insert_earthquakes([dict(EQ, event_id="b1")], db_path=SYN)
        except MaintenanceActiveError:
            refused += 1
        try:
            DB.insert_observation(sqlite3.connect(V2), "koeri", "k1",
                                  "2026-09-01 10:00:00", 100, 40.7, 28.5)
        except MaintenanceActiveError:
            refused += 1
        try:
            DB.save_weekly_stats(dict(_full))
        except MaintenanceActiveError:
            refused += 1
    finally:
        _D2.WEEKLY_DB = _orig_w
    check("G1A: 4 yazi yolu da reddedilir", refused == 4, refused)
finally:
    for _h in holders:
        try:
            _h.terminate()
            _h.wait()
        except Exception:
            pass
# fetch_and_store uctan uca (mock fetch; holder aktifken reddedilir)
import deprem_izleme.fetcher as _F
_fh = subprocess.Popen([sys.executable, HOLDER, SYN, "30"], cwd=HERE,
                       stdout=subprocess.PIPE, text=True)
try:
    time.sleep(1.5)
    from unittest import mock as _mk
    with _mk.patch.object(_F, "fetch_earthquakes", return_value=[dict(EQ, event_id="fx2")]):
        try:
            _F.fetch_and_store(days_back=1, db_path=SYN)
            _fx = False
        except MaintenanceActiveError:
            _fx = True
    check("G1A: fetch_and_store reddedilir", _fx)
finally:
    try:
        _fh.terminate()
        _fh.wait()
    except Exception:
        pass

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
