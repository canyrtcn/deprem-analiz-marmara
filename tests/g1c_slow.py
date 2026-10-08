"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os, sys, time
os.environ['DEPREM_SKIP_DB_INIT']='1'
sys.path.insert(0, REPO_ROOT)
import sqlite3
from deprem_izleme.db import _write_guard_for_path
db = sys.argv[1]
with _write_guard_for_path(db):
    c = sqlite3.connect(db)
    c.execute('BEGIN IMMEDIATE')
    c.execute("INSERT INTO earthquakes (id, event_id, occurred_at, timestamp, latitude, longitude, magnitude, source, region_tag) VALUES (777001, 'slow_1', '2026-09-02 10:00:00', 100, 40.7, 28.5, 1.1, 'test', 'marmara')")
    time.sleep(3)
    c.commit()
    c.close()
print('SLOW-OK')
