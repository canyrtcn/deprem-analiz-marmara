"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os, sys
os.environ['DEPREM_SKIP_DB_INIT']='1'
sys.path.insert(0, REPO_ROOT)
import deprem_izleme.db as DB
db, n, tag = sys.argv[1], int(sys.argv[2]), sys.argv[3]
okc, refc = 0, 0
for i in range(n):
    try:
        DB.insert_earthquake({'id': 100000+hash(tag+i.__str__()) % 10**7,
            'event_id': f'{tag}_{i}', 'occurred_at': '2026-09-02 10:00:00',
            'latitude': 40.7, 'longitude': 28.5, 'depth_km': 5.0,
            'magnitude': 1.1, 'source': 'test'}, db_path=db)
        okc += 1
    except DB.MaintenanceActiveError:
        refc += 1
print(f'{okc} {refc}')
