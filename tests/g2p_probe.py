"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os, sys
sys.path.insert(0, REPO_ROOT)
import deprem_izleme.db_state as D
D.DATA_DIR = _os.path.join(TESTTMP, "g2p_state")
D.STATE_FILE = D.DATA_DIR + '/maintenance.json'
D.ACTIVE_FILE = D.DATA_DIR + '/active_db.json'
D._SETUP_MARK = D.DATA_DIR + '/.state_setup_done'
print(D.get_state()[0])
