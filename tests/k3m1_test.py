"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""K3-M1 testleri (scratch-only). Gercek moduller; yalnizca sentetik DB."""
import os
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
import shutil
import sqlite3
import sys
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)
import k3t_proto as P

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

import deprem_izleme.db as DB
from deprem_izleme.db import (
    init_v2_schema, insert_observation, get_analysis_catalog,
    get_typed_catalog, get_schema_version, check_db_compat,
    migrate_v1_to_v2, content_hash_v1, V2_USER_VERSION)

HERE = TESTTMP
SYN = os.path.join(HERE, "k3m1_syn.db")
for s in ("", "-wal", "-shm", "-journal"):
    if os.path.exists(SYN + s):
        os.remove(SYN + s)
# Bagimsiz fixture: baska bataryanin urettigi dosyaya bel baglanmaz.
if not os.path.exists(os.path.join(HERE, "k3t_v1.db")):
    P.build_v1()
shutil.copy(os.path.join(HERE, "k3t_v1.db"), SYN)

# 1. v2 sema + tetikleyici (gercek init_v2_schema)
c = sqlite3.connect(SYN)
c.execute("PRAGMA foreign_keys=ON")
init_v2_schema(c)
tabs = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view','trigger')")}
check("M1: v2 nesneleri", {"events", "observations", "observation_versions",
      "match_review", "merge_history", "v_compat", "v_typed_science",
      "trg_obs_version_link", "trg_obs_version_link_upd"} <= tabs)
check("M1: user_version=2", c.execute("PRAGMA user_version").fetchone()[0] == 2)

# 2. tetikleyici capraz-bag reddeder (INSERT + UPDATE)
c.execute("INSERT INTO events (canonical_time, latitude, longitude) VALUES (1, 1.0, 1.0)")
e1 = c.execute("SELECT last_insert_rowid()").fetchone()[0]
c.execute("INSERT INTO events (canonical_time, latitude, longitude) VALUES (2, 2.0, 2.0)")
cur = c.execute("INSERT INTO observations (event_id, source, source_event_id, occurred_raw, timestamp, tz_policy) VALUES (?,'s','k', '2026-01-01 00:00:00', 10, 'tz')", (e1,))
o1 = cur.lastrowid
cur = c.execute("INSERT INTO observations (event_id, source, source_event_id, occurred_raw, timestamp, tz_policy) VALUES (?,'s','k2', '2026-01-01 00:00:00', 11, 'tz')", (e1,))
o2 = cur.lastrowid
cur = c.execute("INSERT INTO observation_versions (obs_id, version_no, fetched_hash, occurred_raw, timestamp, revision) VALUES (?,?,?,?,?,?)",
          (o1, 1, "h1", "2026-01-01 00:00:00", 10, "unknown"))
v_other = cur.lastrowid
rej = 0
try:
    c.execute("UPDATE observations SET current_version_id=? WHERE obs_id=?", (v_other, o2))
except sqlite3.IntegrityError:
    rej += 1
try:
    c.execute("INSERT INTO observations (event_id, source, source_event_id, occurred_raw, timestamp, tz_policy, current_version_id) VALUES (?,'s','k3','2026-01-01 00:00:00', 12, 'tz', ?)", (e1, v_other))
except sqlite3.IntegrityError:
    rej += 1
c.execute("UPDATE observations SET current_version_id=? WHERE obs_id=?", (v_other, o1))
check("M1: capraz-bag INSERT+UPDATE reddedilir, oz-bag gecer", rej == 2)
c.rollback()

# 3. insert_observation akisi (hash ayni -> surum yok; degisik -> v2, eski durur)
c.execute("DELETE FROM observation_versions")
c.execute("DELETE FROM observations")
c.execute("DELETE FROM events")
o, v, created = insert_observation(
    c, "koeri", "k_1", "2026-09-01 10:00:00", 100, 40.7, 28.5, 10.0,
    ml=1.5, revision="preliminary", raw_line="HAM", raw_status="present",
    tz_policy="Europe/Istanbul-varsayim")
check("M1: yeni gozlem v1", created is True and v == 1, (o, v))
o2, v2, c2 = insert_observation(
    c, "koeri", "k_1", "2026-09-01 10:00:00", 100, 40.7, 28.5, 10.0,
    ml=1.5, revision="preliminary", raw_line="HAM", raw_status="present",
    tz_policy="Europe/Istanbul-varsayim")
check("M1: ayni icerik surum uretmez",
      (o2, v2, c2) == (o, 1, False)
      and c.execute("SELECT COUNT(*) FROM observation_versions").fetchone()[0] == 1)
o3, v3, c3 = insert_observation(
    c, "koeri", "k_1", "2026-09-01 10:00:05", 100, 40.71, 28.51, 10.0,
    ml=1.6, revision="revised", raw_line="HAM2", raw_status="present",
    tz_policy="Europe/Istanbul-varsayim")
nver = c.execute("SELECT COUNT(*) FROM observation_versions WHERE obs_id=?", (o,)).fetchone()[0]
old = c.execute("SELECT ml, revision FROM observation_versions WHERE obs_id=? AND version_no=1", (o,)).fetchone()
check("M1: degisiklik v2 uretir, v1 korunur",
      c3 is True and v3 == 2 and nver == 2 and tuple(old) == (1.5, "preliminary"),
      (v3, nver, tuple(old)))
cur = c.execute("SELECT current_version_id FROM observations WHERE obs_id=?", (o,)).fetchone()[0]
newv = c.execute("SELECT version_id FROM observation_versions WHERE obs_id=? AND version_no=2", (o,)).fetchone()[0]
check("M1: isaretci v2'yi gosterir", cur == newv)
c.commit()

# 4. hash surumlendirilmis + deterministik
h1 = content_hash_v1("2026-09-01 10:00:00", 40.7, 28.5, 10.0, 1.5, None, None, "unknown")
check("M1: hash v1 prefix + stabil",
      h1 == content_hash_v1("2026-09-01 10:00:00", 40.7, 28.5, 10.0, 1.5, None, None, "unknown"))

# 5. migrate canli reddi (src ve dst)
LIVE = _os.path.join(REPO_ROOT, "data/depremler.db")
ref = 0
try:
    migrate_v1_to_v2(LIVE, os.path.join(HERE, "k3m1_out.db"))
except RuntimeError as e:
    ref += 1
try:
    migrate_v1_to_v2(os.path.join(HERE, "k3t_v1.db"), LIVE)
except RuntimeError as e:
    ref += 1
check("M1: canli src/dst reddedilir", ref == 2)
check("M1: canli DB boyutu degismedi",
      os.path.getsize(LIVE) == 40960)

# 6. sentetik goc (gercek fonksiyon) + katalog paritesi
DST = os.path.join(HERE, "k3m1_work.db")
for s in ("", "-wal", "-shm", "-journal"):
    if os.path.exists(DST + s):
        os.remove(DST + s)
counts, ver = migrate_v1_to_v2(os.path.join(HERE, "k3t_v1.db"), DST)
check("M1: goc 41/41/41",
      counts["obs"] == 41 and counts["ver"] == 41 and counts["ev"] == 41
      and counts["uv"] == 2 and ver["fk"] == []
      and ver["integrity"] == "ok" and ver["link_mismatch"] == 0, counts)
c2 = sqlite3.connect(DST)
c2.row_factory = sqlite3.Row
cat = get_analysis_catalog(c2)
_legc = __import__("sqlite3").connect(os.path.join(HERE, "k3t_v1.db"))
_legc.row_factory = __import__("sqlite3").Row
leg = sorted([(r["magnitude"], r["timestamp"]) for r in
              _legc.execute("SELECT magnitude, timestamp FROM earthquakes")])
_legc.close()
got = sorted([(r["magnitude"], r["timestamp"]) for r in cat])
check("M1: v_compat legacy ile birebir", got == leg and len(cat) == 41, len(cat))
typ = get_typed_catalog(c2)
check("M1: typed alt-kume ayri", 0 < len(typ) < 41, len(typ))
c2.close()

# 7. uyumluluk kapisi
check("M1: legacy sessiz-ok", check_db_compat(os.path.join(HERE, "k3t_v1.db"))[0] is True)
check("M1: v2 ok", check_db_compat(DST)[0] is True)
import tempfile as _tf
with _tf.NamedTemporaryFile(suffix=".db", delete=False) as _f:
    _fp = _f.name
_cc = sqlite3.connect(_fp)
_cc.execute("PRAGMA user_version=99")
_cc.execute("CREATE TABLE observations(x)")
_cc.execute("CREATE TABLE observation_versions(x)")
_cc.execute("CREATE TABLE events(x)")
_cc.commit()
_cc.close()
ok99, msg99 = check_db_compat(_fp)
os.unlink(_fp)
check("M1: v99 acilis reddedilir", ok99 is False and "otomatik goc" in msg99, msg99[:60])

# 8. legacy yol bozulmadi (gercek insert_earthquake, sentetik legacy)
LEG = os.path.join(HERE, "k3m1_leg.db")
for s in ("", "-wal", "-shm", "-journal"):
    if os.path.exists(LEG + s):
        os.remove(LEG + s)
shutil.copy(os.path.join(HERE, "k3t_v1.db"), LEG)
import deprem_izleme.db as _DB
from unittest import mock as _mock
_cl = sqlite3.connect(LEG)
_n0 = _cl.execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0]
_cl.close()
with _mock.patch.object(_DB, "MAIN_DB", LEG):
    _DB.insert_earthquake({"id": 999001, "event_id": "sentetik_yeni",
                           "occurred_at": "2026-09-22 10:00:00", "latitude": 40.7,
                           "longitude": 28.5, "depth_km": 5.0, "magnitude": 1.1,
                           "source": "test"})
_cl = sqlite3.connect(LEG)
_n1 = _cl.execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0]
_cl.close()
check("M1: legacy insert calisir", _n1 == _n0 + 1, (_n0, _n1))

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
