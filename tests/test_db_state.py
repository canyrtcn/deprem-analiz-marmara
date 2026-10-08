"""db_state fail-closed matrisi (sentetik dizin, canliya dokunulmaz)."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)

import json
import shutil
import tempfile
ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

import deprem_izleme.db_state as DS
import deprem_izleme.db as DB

ST = tempfile.mkdtemp(prefix="dbstate_")
DS.DATA_DIR = ST
DS.STATE_FILE = os.path.join(ST, "maintenance.json")
DS.ACTIVE_FILE = os.path.join(ST, "active_db.json")
DS._SETUP_MARK = os.path.join(ST, ".state_setup_done")
LOCKDB = os.path.join(ST, "lock.db")

# 1. ilk kurulum: kilitlemez, normal + legacy
check("S1: ensure_setup", DS.ensure_setup() is True)
st, _ = DS.get_state()
check("S1: kurulum sonrasi normal", st == "normal", st)
check("S1: aktif varsayilan legacy", DS.get_active_db() == DB.MAIN_DB)
try:
    DS.check_writable()
    _w = True
except DB.MaintenanceActiveError:
    _w = False
check("S1: kurulum sonrasi yazim acik", _w)

# 2. kurulum sonrasi kayip dosya -> fail-closed (sessiz normal YOK)
os.remove(DS.STATE_FILE)
st, _ = DS.get_state()
try:
    DS.check_writable()
    _w2 = True
except DB.MaintenanceActiveError:
    _w2 = False
check("S2: kayip durum fail-closed", st != "normal" and _w2 is False, st)
DS.set_normal(_lock_path=LOCKDB)

# 3. bozuk active_db.json: okuma uyarili fallback, yazma red
with open(DS.ACTIVE_FILE, "w", encoding="utf-8") as f:
    f.write("{bozuk")
check("S3: okuma legacy fallback", DS.get_active_db() == DB.MAIN_DB)
try:
    DS.get_active_db(strict=True)
    _s3 = False
except DB.MaintenanceActiveError:
    _s3 = True
check("S3: strict red", _s3)
try:
    DS.check_writable()
    _w3 = True
except DB.MaintenanceActiveError:
    _w3 = False
check("S3: bozuk hedefte yazma kapali", _w3 is False)
with open(DS.ACTIVE_FILE, "w", encoding="utf-8") as f:
    json.dump({"active": DB.MAIN_DB}, f)
try:
    DS.check_writable()
    _w3b = True
except DB.MaintenanceActiveError:
    _w3b = False
check("S3: saglam hedefte yazim acilir", _w3b)

# 4. kilitli gecisler
DS.set_frozen("test", _lock_path=LOCKDB)
check("S4: frozen", DS.get_state()[0] == "frozen")
try:
    DS.check_writable()
    _w4 = True
except DB.MaintenanceActiveError:
    _w4 = False
check("S4: frozen yazim kapali", _w4 is False)
DS.set_normal(_lock_path=LOCKDB)
check("S4: normal donus", DS.get_state()[0] == "normal")

# 5. kurulum-oncesi varsayilan (mark yok) kilitlemez
ST2 = tempfile.mkdtemp(prefix="dbstate_pre_")
DS.DATA_DIR = ST2
DS.STATE_FILE = os.path.join(ST2, "maintenance.json")
DS.ACTIVE_FILE = os.path.join(ST2, "active_db.json")
DS._SETUP_MARK = os.path.join(ST2, ".state_setup_done")
st5, _ = DS.get_state()
check("S5: kurulum-oncesi varsayilan normal", st5 == "normal", st5)

shutil.rmtree(ST, ignore_errors=True)
shutil.rmtree(ST2, ignore_errors=True)
print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
