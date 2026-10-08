"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""CLI surucu (scratch): sentetik DB + main.main() + gercek cikis kodu.
Kullanim: cli_driver.py <SYN_DB> <WDB> <MDB> <komut...> [--mock-fetch N]
HB: db_guard her zaman kurulu (yama kacirsa bile canli engellenir).
"""
import os
import sys
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)

SYN, WDB, MDB = sys.argv[1], sys.argv[2], sys.argv[3]
rest = sys.argv[4:]
mock_n = None
mock_tag = "cli"
if "--mock-fetch" in rest:
    i = rest.index("--mock-fetch")
    mock_n = int(rest[i + 1])
    rest = rest[:i] + rest[i + 2:]
if "--mock-tag" in rest:
    i = rest.index("--mock-tag")
    mock_tag = rest[i + 1]
    rest = rest[:i] + rest[i + 2:]

import time
import deprem_izleme.db as DB
import deprem_izleme.fetcher as F
DB.MAIN_DB = SYN
F.MAIN_DB = SYN
DB.WEEKLY_DB = WDB
DB.MONTHLY_DB = MDB
# durum dosyalari scratch'e (gercek data'ya degmez)
import deprem_izleme.db_state as _DS
_DS.DATA_DIR = os.path.join(TESTTMP,
                            "cli_state")
os.makedirs(_DS.DATA_DIR, exist_ok=True)
_DS.STATE_FILE = os.path.join(_DS.DATA_DIR, "maintenance.json")
_DS.ACTIVE_FILE = os.path.join(_DS.DATA_DIR, "active_db.json")
_DS._SETUP_MARK = os.path.join(_DS.DATA_DIR, ".state_setup_done")

if mock_n is not None:
    NOW = int(time.time())

    def _fq(days_back=7, min_magnitude=0.0, sources=None):
        out = []
        for i in range(mock_n):
            ts = NOW - i * 86400
            out.append({"id": 5000 + i, "event_id": "%s_%d" % (mock_tag, i),
                        "occurred_at": time.strftime("%Y-%m-%d %H:%M:%S",
                                                     time.localtime(ts)),
                        "latitude": 40.7, "longitude": 28.5, "depth_km": 5.0,
                        "magnitude": 1.1, "location": "YER", "source": "t",
                        "region_tag": "marmara"})
        return out

    F.fetch_earthquakes = _fq

sys.argv = ["main.py"] + rest
import main
rc = main.main()
print("RC=%s" % rc)
sys.exit(rc or 0)
