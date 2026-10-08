"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""Izolasyon kapisi testleri (scratch-only). Beklenen: engelleme calisir."""
import os
import sqlite3
import sys
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)
from deprem_izleme.config import MAIN_DB as LIVE

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

HERE = TESTTMP
SYN = os.path.join(HERE, "k3g_syn.db")
for s in ("", "-wal", "-shm", "-journal"):
    if os.path.exists(SYN + s):
        os.remove(SYN + s)

# 1. dogrudan canli baglanti engellenir (3 yol bicimi)
blocked = 0
for p in (LIVE, LIVE.replace("/", "\\"),
          "file:" + LIVE + "?mode=ro"):
    try:
        sqlite3.connect(p).close()
    except db_guard.LiveDBBlockedError:
        blocked += 1
check("G1: 3 yol bicimi de engellenir", blocked == 3, blocked)

# 2. fonksiyon-ici yeniden import senaryosu
def kotu_yol():
    from deprem_izleme.config import MAIN_DB
    return sqlite3.connect(MAIN_DB)
try:
    kotu_yol().close()
    check("G2: yeniden-import yolu engellenir", False, "erisim saglandi!")
except db_guard.LiveDBBlockedError:
    check("G2: yeniden-import yolu engellenir", True)

# 3. API duzeyi: acik canli yol ve varsayilan yol reddedilir
import deprem_izleme.db as DB
cases = [
    ("get_earthquakes(acik)", lambda: DB.get_earthquakes(db_path=LIVE)),
    ("get_earthquakes(varsayilan)", lambda: DB.get_earthquakes()),
    ("get_stats(acik)", lambda: DB.get_stats(db_path=LIVE)),
    ("get_stats(varsayilan)", lambda: DB.get_stats()),
    ("insert(acik)", lambda: DB.insert_earthquake({"event_id": "x"}, db_path=LIVE)),
    ("check_compat(varsayilan)", lambda: DB.check_db_compat()),
]
for name, fn in cases:
    try:
        res = fn()
        if name.startswith("check_compat"):
            check("G3: " + name, res[0] is False, res[1][:50] if len(res) > 1 else "")
        else:
            check("G3: " + name, False, "erisim saglandi!")
    except db_guard.LiveDBBlockedError:
        check("G3: " + name, True)
    except Exception as e:
        check("G3: " + name, False, f"yanlis hata: {type(e).__name__}")

# 4. sentetik yol serbest
c = sqlite3.connect(SYN)
c.execute("CREATE TABLE t(x)")
c.commit()
c.close()
check("G4: sentetik serbest", os.path.exists(SYN))

# 5. :memory: serbest
m = sqlite3.connect(":memory:")
m.execute("CREATE TABLE t(x)")
m.close()
check("G5: bellek serbest", True)

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
