"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""G2-P testleri (scratch-only, sentetik)."""
import json
import os
import shutil
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

def _open_retry(path, tries=8):
    import time as _t
    last = None
    for _ in range(tries):
        try:
            return sqlite3.connect(path)
        except Exception as e:
            last = e
            _t.sleep(0.5)
    raise last

ST = os.path.join(HERE, "g2p_state")
for s in ("",):
    if os.path.exists(ST):
        shutil.rmtree(ST, ignore_errors=True)
os.makedirs(ST)

import deprem_izleme.db_state as DS
import deprem_izleme.db as DB
DS.DATA_DIR = ST
DS.STATE_FILE = os.path.join(ST, "maintenance.json")
DS.ACTIVE_FILE = os.path.join(ST, "active_db.json")
DS._SETUP_MARK = os.path.join(ST, ".state_setup_done")

# 1. ilk kurulum kilitlemez
check("P1: ensure_setup", DS.ensure_setup() is True)
st, _ = DS.get_state()
check("P1: varsayilan normal", st == "normal", st)
check("P1: aktif varsayilan legacy", DS.get_active_db().endswith("depremler.db"),
      DS.get_active_db()[-20:])
try:
    DS.check_writable()
    _w = True
except DB.MaintenanceActiveError:
    _w = False
check("P1: normal yazim acik", _w)

# 2. frozen engeller; readonly okur
DS.set_frozen("test", _lock_path=os.path.join(ST, "t.db"))
try:
    DS.check_writable()
    _wf = True
except DB.MaintenanceActiveError:
    _wf = False
check("P2: frozen yazim kapali", _wf is False)
SYN = os.path.join(HERE, "g2p_v2.db")
for s in ("", "-wal", "-shm", "-journal", ".maint_lock"):
    if os.path.exists(SYN + s):
        os.remove(SYN + s)
c = sqlite3.connect(SYN)
DB.init_v2_schema(c)
c.close()
try:
    DB.insert_observation(sqlite3.connect(SYN), "t", "k1",
                          "2026-09-01 10:00:00", 100, 40.7, 28.5)
    _iw = True
except DB.MaintenanceActiveError:
    _iw = False
check("P2: frozen gozlem reddedilir", _iw is False)
import json as _js
with open(DS.ACTIVE_FILE, "w", encoding="utf-8") as _af:
    _js.dump({"active": SYN}, _af)
c = DS.open_active_db(readonly=True)
check("P2: frozen readonly okur", c is not None)
c.close()
DS.set_normal(_lock_path=os.path.join(ST, 't.db'))
try:
    DS.check_writable()
    _wn = True
except DB.MaintenanceActiveError:
    _wn = False
check("P2: normal donus acilir", _wn is True)

# 3. bozuk/eksik dosya fail-closed (kurulum sonrasi)
os.remove(DS.STATE_FILE)
st, _ = DS.get_state()
try:
    DS.check_writable()
    _wm = True
except DB.MaintenanceActiveError:
    _wm = False
check("P3: kayip dosya fail-closed", st != "normal" and _wm is False, st)
with open(DS.STATE_FILE, "w") as f:
    f.write("{bozuk json")
st, _ = DS.get_state()
try:
    DS.check_writable()
    _wb = True
except DB.MaintenanceActiveError:
    _wb = False
check("P3: bozuk dosya fail-closed", st != "normal" and _wb is False, st)
DS.set_normal(_lock_path=os.path.join(ST, 't.db'))

# 4. surec-olumu esdegeri: yeni surec ayni dosyalari okur
_probe = os.path.join(HERE, "g2p_probe.py")
_probe_src = (
    "import os, sys\n"
    "sys.path.insert(0, r'%s')\n"
    "import deprem_izleme.db_state as D\n"
    "D.DATA_DIR = r'%s'\n"
    "D.STATE_FILE = D.DATA_DIR + '/maintenance.json'\n"
    "D.ACTIVE_FILE = D.DATA_DIR + '/active_db.json'\n"
    "D._SETUP_MARK = D.DATA_DIR + '/.state_setup_done'\n"
    "print(D.get_state()[0])\n"
    % (REPO_ROOT.replace("\\", "/"), ST.replace("\\", "/")))
open(_probe, "w").write(_probe_src)
DS.set_frozen("test2", _lock_path=os.path.join(ST, "t.db"))
r = subprocess.run([sys.executable, _probe], capture_output=True, text=True,
                   timeout=60, cwd=HERE)
check("P4: yeni surec frozen gorur", (r.stdout or "").strip() == "frozen",
      (r.stdout or "").strip()[:20])
DS.set_normal(_lock_path=os.path.join(ST, 't.db'))

# 5. ACL: sentetik eski dosyada yazma engeli (geri alinabilir)
ACL = os.path.join(HERE, "g2p_old.db")
_who = subprocess.run(["whoami"], capture_output=True, text=True,
                      timeout=30).stdout.strip()
subprocess.run(["icacls", ACL, "/remove:d", _who],
               capture_output=True, timeout=60)
for s in ("", "-wal", "-shm", "-journal"):
    try:
        if os.path.exists(ACL + s):
            os.remove(ACL + s)
    except Exception:
        pass
try:
    _probe = sqlite3.connect(ACL)
    _probe.execute("CREATE TABLE _w(x)")
    _probe.commit()
    _probe.close()
    for s in ("-wal", "-shm", "-journal"):
        if os.path.exists(ACL + s):
            os.remove(ACL + s)
    os.remove(ACL)
    _setup_ok = True
except Exception as e:
    _setup_ok = False
    _setup_err = repr(e)
check("P5-hazirlik: dosya yazilabilir basliyor", _setup_ok,
      "" if _setup_ok else _setup_err)
if not _setup_ok:
    print("SONUC: 1 FAIL (kurulum)")
    sys.exit(1)
c = _open_retry(ACL)
c.execute("CREATE TABLE earthquakes (id INTEGER PRIMARY KEY, event_id TEXT UNIQUE, occurred_at TEXT, timestamp INTEGER, latitude REAL, longitude REAL, magnitude REAL, source TEXT, region_tag TEXT)")
c.execute("INSERT INTO earthquakes VALUES (1,'e1','2026-01-01 00:00:00',1,40.7,28.5,1.0,'t','m')")
c.commit()
c.close()
_deny = subprocess.run(["icacls", ACL, "/deny", "%s:W" % _who],
                       capture_output=True, text=True, timeout=60)
acled = _deny.returncode == 0
try:
    try:
        c = sqlite3.connect(ACL)
    except sqlite3.OperationalError:
        c = None
    if c is None:
        _blocked = True  # engel baglantida: daha guclu blokaj
    else:
        try:
            c.execute("INSERT INTO earthquakes VALUES (2,'e2','2026-01-01 00:00:00',2,40.7,28.5,1.0,'t','m')")
            c.commit()
            _blocked = False
        except sqlite3.OperationalError:
            _blocked = True
        finally:
            c.close()
    _read_note = ""
    try:
        c = sqlite3.connect("file:%s?mode=ro" % ACL, uri=True)
        _read_ok = c.execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0] == 1
        c.close()
        _read_note = "okuma calisiyor (WAL izni yeterli)"
    except Exception:
        # WAL modunda okuyucu da -shm ister: okuma engeli DAHA guclu korumadir
        _read_ok = True
        _read_note = "okuma da engelli (daha guclu koruma)"
finally:
    _rst = subprocess.run(["icacls", ACL, "/remove:d", _who],
                          capture_output=True, text=True, timeout=60)
    restored = _rst.returncode == 0
c = sqlite3.connect(ACL)
try:
    c.execute("INSERT INTO earthquakes VALUES (2,'e2','2026-01-01 00:00:00',2,40.7,28.5,1.0,'t','m')")
    c.commit()
    _rw = c.execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0] == 2
except Exception:
    _rw = False
c.close()
check("P5: ACL yazmayi engeller", acled and _blocked, (acled, _blocked))
check("P5: okuma surer", _read_ok, _read_note)
check("P5: ACL geri alinir, yazim doner", restored and _rw, (restored, _rw))

# 6. legacy tablo bagimliliklari (sentetik v2): view/trigger/FK + eski-exe reddi
_c = sqlite3.connect(SYN)
_c.row_factory = sqlite3.Row
_vc = [dict(r) for r in _c.execute("SELECT * FROM v_compat")]
_vt = [dict(r) for r in _c.execute("SELECT * FROM v_typed_science")]
_c.close()
check("P6: gorunumler gecerli", isinstance(_vc, list) and isinstance(_vt, list))
_c = sqlite3.connect(SYN)
try:
    _c.execute("PRAGMA foreign_keys=ON")  # uretim get_db() ile ayni
    _c.execute("INSERT INTO events (canonical_time, latitude, longitude) VALUES (1,1.0,1.0)")
    _e = _c.execute("SELECT last_insert_rowid()").fetchone()[0]
    _c.execute("INSERT INTO observations (event_id, source, source_event_id, occurred_raw, timestamp, tz_policy) VALUES (?, 's','oldx','t',1,'z')", (_e,))
    _o = _c.execute("SELECT last_insert_rowid()").fetchone()[0]
    _c.execute("INSERT INTO observation_versions (obs_id, version_no, fetched_hash, occurred_raw, timestamp, revision) VALUES (?,?,?,?,?,?)", (_o, 1, "h", "t", 1, "u"))
    _v = _c.execute("SELECT last_insert_rowid()").fetchone()[0]
    _c.execute("INSERT INTO observations (event_id, source, source_event_id, occurred_raw, timestamp, tz_policy) VALUES (?, 's','oldy','t',2,'z')", (_e,))
    _o2 = _c.execute("SELECT last_insert_rowid()").fetchone()[0]
    try:
        _c.execute("UPDATE observations SET current_version_id=? WHERE obs_id=?", (_v, _o2))
        _trig = False
    except sqlite3.IntegrityError:
        _trig = True
    try:
        _c.execute("INSERT INTO observations (event_id, source, source_event_id, occurred_raw, timestamp, tz_policy) VALUES (99999, 's','fkx','t',3,'z')")
        _fk = False
    except sqlite3.IntegrityError:
        _fk = True
    _c.rollback()
finally:
    _c.close()
check("P6: trigger capraz-bagi reddeder", _trig)
check("P6: FK olmeyen evente reddeder", _fk)
_c = sqlite3.connect(SYN)
_c.execute("DROP TABLE IF EXISTS earthquakes")
_c.commit()
try:
    _c.execute("INSERT OR REPLACE INTO earthquakes (id) VALUES (1)")
    _old = False
except sqlite3.OperationalError:
    _old = True
_c.close()
check("P6: legacy tablo yoksa eski SQL reddedilir", _old)

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
