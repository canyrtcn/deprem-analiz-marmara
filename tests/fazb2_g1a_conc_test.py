"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""G1-A normal-calisma eszamanlilik (scratch-only, sentetik, cok-surecli)."""
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
SYN = os.path.join(HERE, "g1c_main.db")
for s in ("", "-wal", "-shm", "-journal", ".maint_lock"):
    if os.path.exists(SYN + s):
        os.remove(SYN + s)

import deprem_izleme.db as DB

c = sqlite3.connect(SYN)
c.execute("CREATE TABLE earthquakes (id INTEGER PRIMARY KEY, event_id TEXT UNIQUE, occurred_at TEXT NOT NULL, timestamp INTEGER NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL, depth_km REAL, magnitude REAL, magnitude_ml REAL, magnitude_mw REAL, magnitude_md REAL, location TEXT, source TEXT, region_tag TEXT, created_at TEXT DEFAULT (datetime('now')))")
c.commit()
c.close()

_REPO_P = REPO_ROOT.replace("\\", "/")
W = os.path.join(HERE, "g1c_w.py")
_w_src = (
    "import os, sys\n"
    "os.environ['DEPREM_SKIP_DB_INIT']='1'\n"
    "sys.path.insert(0, r'__REPO__')\n"
    "import deprem_izleme.db as DB\n"
    "db, n, tag, mode = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]\n"
    "okc, refc = 0, 0\n"
    "for i in range(n):\n"
    "    q = {'id': 200000+abs(hash((tag, i))) % 10**7,\n"
    "         'event_id': f'{tag}_{i}', 'occurred_at': '2026-09-02 10:00:00',\n"
    "         'latitude': 40.7, 'longitude': 28.5, 'depth_km': 5.0,\n"
    "         'magnitude': 1.1, 'source': 'test'}\n"
    "    try:\n"
    "        if mode == 'v2':\n"
    "            DB.insert_observation(__import__('sqlite3').connect(db), 't', f'{tag}_{i}',\n"
    "                '2026-09-02 10:00:00', 100+i, 40.7, 28.5, 5.0, ml=1.1)\n"
    "        else:\n"
    "            DB.insert_earthquake(q, db_path=db)\n"
    "        okc += 1\n"
    "    except DB.MaintenanceActiveError:\n"
    "        refc += 1\n"
    "print(f'{okc} {refc}')\n")
open(W, "w").write(_w_src.replace("__REPO__", _REPO_P))
SLOW = os.path.join(HERE, "g1c_slow.py")
_slow_src = (
    "import os, sys, time\n"
    "os.environ['DEPREM_SKIP_DB_INIT']='1'\n"
    "sys.path.insert(0, r'__REPO__')\n"
    "import sqlite3\n"
    "from deprem_izleme.db import _write_guard_for_path\n"
    "db = sys.argv[1]\n"
    "with _write_guard_for_path(db):\n"
    "    c = sqlite3.connect(db)\n"
    "    c.execute('BEGIN IMMEDIATE')\n"
    "    c.execute(\"INSERT INTO earthquakes (id, event_id, occurred_at, timestamp, latitude, longitude, magnitude, source, region_tag) VALUES (777001, 'slow_1', '2026-09-02 10:00:00', 100, 40.7, 28.5, 1.1, 'test', 'marmara')\")\n"
    "    time.sleep(3)\n"
    "    c.commit()\n"
    "    c.close()\n"
    "print('SLOW-OK')\n")
open(SLOW, "w").write(_slow_src.replace("__REPO__", _REPO_P))

def run(args, **kw):
    return subprocess.run([sys.executable] + args, capture_output=True,
                          text=True, timeout=180, cwd=HERE, **kw)

# 1. normal: 3 legacy + 2 v2 surec x15 -> kayipsiz serilenme
V2 = os.path.join(HERE, "g1c_v2.db")
for s in ("", "-wal", "-shm", "-journal", ".maint_lock"):
    if os.path.exists(V2 + s):
        os.remove(V2 + s)
_vc = sqlite3.connect(V2)
DB.init_v2_schema(_vc)
_vc.close()
procs = []
for k in range(3):
    procs.append(subprocess.Popen([sys.executable, W, SYN, "15", f"n{k}", "leg"],
                                  cwd=HERE, stdout=subprocess.PIPE, text=True))
for k in range(2):
    procs.append(subprocess.Popen([sys.executable, W, V2, "15", f"v{k}", "v2"],
                                  cwd=HERE, stdout=subprocess.PIPE, text=True))
tot_ok, tot_ref = 0, 0
for p in procs:
    o = p.communicate()[0].strip().split()
    tot_ok += int(o[0])
    tot_ref += int(o[1])
n_leg = sqlite3.connect(SYN).execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0]
n_v2 = sqlite3.connect(V2).execute("SELECT COUNT(*) FROM observations").fetchone()[0]
check("C1: 75/75 kayipsiz serilenme", tot_ok == 75 and tot_ref == 0
      and n_leg == 45 and n_v2 == 30, f"ok={tot_ok} ref={tot_ref} leg={n_leg} v2={n_v2}")
c = sqlite3.connect(SYN)
check("C1: bütünlük", c.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
c.close()

# 2. yavas txn surerken bakim NO-GO; txn tamamlanir; sonra bakim OK
slow = subprocess.Popen([sys.executable, SLOW, SYN], cwd=HERE,
                        stdout=subprocess.PIPE, text=True)
time.sleep(1.0)
try:
    with DB.maintenance_hold(SYN):
        _early = True
except DB.MaintenanceActiveError:
    _early = False
check("C2: txn surerken bakim NO-GO", _early is False)
out = slow.communicate()[0].strip()
late_ok = False
try:
    with DB.maintenance_hold(SYN, timeout_s=10):
        late_ok = True
except DB.MaintenanceActiveError:
    late_ok = False
n_slow = sqlite3.connect(SYN).execute(
    "SELECT COUNT(*) FROM earthquakes WHERE event_id='slow_1'").fetchone()[0]
check("C2: txn tamamlandi + sonra bakim OK", out == "SLOW-OK" and late_ok
      and n_slow == 1, (out, late_ok, n_slow))

# 3. reddedilen yazim ust katmanda sessiz-basari/bos-katalog olmaz
# (holder ayri surecte; ayni-thread reentrant gecisi bilerek baypas edilir)
import deprem_izleme.fetcher as _F
from unittest import mock as _mk
import subprocess as _sp3
_H3 = os.path.join(HERE, "g1a_holder.py")
_fh3 = _sp3.Popen([sys.executable, _H3, SYN, "60"], cwd=HERE,
                  stdout=subprocess.PIPE, text=True)
try:
    _held3 = False
    for _i in range(100):
        time.sleep(0.2)
        try:
            with DB.maintenance_hold(SYN):
                pass
            continue
        except DB.MaintenanceActiveError:
            _held3 = True
            break
    check("C3-hazirlik: holder tutuyor", _held3)
    with _mk.patch.object(_F, "fetch_earthquakes",
                          return_value=[{"id": 5, "event_id": "fx",
                                         "occurred_at": "2026-09-02 10:00:00",
                                         "latitude": 40.7, "longitude": 28.5,
                                         "magnitude": 1.1, "source": "t"}]):
        try:
            _F.fetch_and_store(days_back=1, db_path=SYN)
            _raised = False
        except DB.MaintenanceActiveError:
            _raised = True
    check("C3: fetch_and_store yukseltir ([] degil)", _raised)
finally:
    try:
        _fh3.terminate()
        _fh3.wait()
    except Exception:
        pass
    import io as _io
    from contextlib import redirect_stdout as _rs
    import main as _MAIN
    import argparse as _ap
    with _mk.patch.object(_MAIN, "fetch_and_store",
                          side_effect=DB.MaintenanceActiveError("bakim kilidi aktif")):
        _buf = _io.StringIO()
        with _rs(_buf):
            try:
                _MAIN._fetch_safe(1, 1.0)
                _raised2 = False
            except DB.MaintenanceActiveError:
                _raised2 = True
        _txt = _buf.getvalue()
        check("C3: _fetch_safe yukseltir + acik mesaj",
              _raised2 and "bakim" in _txt, _txt.strip()[:90])
        _buf2 = _io.StringIO()
        with _rs(_buf2):
            _rc1 = _MAIN.cmd_fetch(_ap.Namespace(days=1, min_mag=0.0, sources=None))
        check("C3: cmd_fetch rc=1 (basari gibi 0 degil)", _rc1 == 1,
              f"rc={_rc1} msg={_buf2.getvalue().strip()[:80]}")
        _buf3 = _io.StringIO()
        with _rs(_buf3):
            _rc2 = _MAIN.cmd_update(_ap.Namespace(fetch=True, region="marmara"))
        check("C3: cmd_update rc=1 (analiz iptal)", _rc2 == 1, f"rc={_rc2}")

# 4. farkli yazim, AYNI kilit (farkli yazimli yol ayni gercek dosyaya
# cozumlenir; tasinabilirlik icin gecici dizin icinde kurulur)
import tempfile as _tf
with _tf.TemporaryDirectory() as td:
    alt = os.path.join(HERE, "sub", "..", "g1c_main.db")
    held = []
    import threading as _th
    def _hold():
        with DB.maintenance_hold(alt):
            held.append(True)
            time.sleep(2)
    t = _th.Thread(target=_hold)
    t.start()
    time.sleep(0.7)
    try:
        with DB.maintenance_hold(SYN):
            _same = False
    except DB.MaintenanceActiveError:
        _same = True
    t.join()
    check("C4: farkli yazim ayni kilit", _same and held == [True])
    from deprem_izleme.db import lock_path_for
    import deprem_izleme.db as _DBLP
    _lp = lambda p: os.path.normcase(os.path.realpath(
        _DBLP.lock_path_for(p)))
    check("C4: kilit yolu tekil", _lp(alt) == _lp(SYN))

# 5. kapsam: init DDL korunur (idempotent), migration kendi kilidini alir,
#    db.py disi ham yazim yok (kaynak denetimi)
import deprem_izleme.db as _D5
from unittest import mock as _mk5
_n0 = sqlite3.connect(SYN).execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0]
with _mk5.patch.object(_D5, "MAIN_DB", SYN):
    _D5.init_main_db()
    _D5.init_main_db()
import re as _re
srcs = []
for _f in ("deprem_izleme/db.py",):
    pass
import glob as _g
bad = []
for _fp in _g.glob(_os.path.join(REPO_ROOT, "deprem_izleme/*.py")) + \
          [_os.path.join(REPO_ROOT, "main.py")]:
    _t = open(_fp, encoding="utf-8").read()
    if _fp.endswith("db.py"):
        continue
    for _m in _re.finditer(r"\b(INSERT|UPDATE|DELETE)\b", _t):
        # yorum/satir-ici SQL metni mi? kaba: ayni satirda execute yoksa sayma
        _line = _t[max(0, _m.start()-120):_m.end()]
        if "execute" in _line or "executemany" in _line:
            bad.append((_fp.split("/")[-1], _line.strip()[-60:]))
check("C5: db.py disi SQL yazim yok", not bad, bad[:3])
check("C5: init idempotent (sayi sabit)",
      sqlite3.connect(SYN).execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0] == _n0)

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
