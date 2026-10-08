"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os, sys, time
os.environ['DEPREM_SKIP_DB_INIT']='1'
sys.path.insert(0, REPO_ROOT)
from deprem_izleme.db import maintenance_hold
db, secs = sys.argv[1], float(sys.argv[2])
sys.stdout.write('HOLDING\n'); sys.stdout.flush()
with maintenance_hold(db):
    time.sleep(secs)
