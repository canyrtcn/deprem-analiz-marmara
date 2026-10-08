"""K3-T migration prototipi (scratch-only; uretim modullerine dokunmaz).

Bilesenler: sentetik v1 DB kurulumu -> Backup API yedegi -> calisma
kopyasinda v2 semasi + tasima -> dogrulamalar -> rollback/kesinti testi.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import time

HERE = os.environ.get("DEPREM_TESTTMP") or os.path.dirname(os.path.abspath(__file__))
V1 = os.path.join(HERE, "k3t_v1.db")
BACKUP = os.path.join(HERE, "k3t_backup.db")
WORK = os.path.join(HERE, "k3t_work.db")
LIVE = os.path.join(HERE, "k3t_live.db")  # "canli" rolu oynayan kopya

LEGACY_SCHEMA = """
CREATE TABLE earthquakes (
    id INTEGER PRIMARY KEY, event_id TEXT UNIQUE,
    occurred_at TEXT NOT NULL, timestamp INTEGER NOT NULL,
    latitude REAL NOT NULL, longitude REAL NOT NULL, depth_km REAL,
    magnitude REAL, magnitude_ml REAL, magnitude_mw REAL, magnitude_md REAL,
    location TEXT, source TEXT, region_tag TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);"""

V2_SCHEMA = """
PRAGMA foreign_keys=OFF;
CREATE TABLE events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_time INTEGER NOT NULL, latitude REAL NOT NULL,
  longitude REAL NOT NULL, depth_km REAL,
  mag_canonical REAL, mag_type TEXT,
  status TEXT NOT NULL DEFAULT 'candidate'
    CHECK(status IN ('candidate','confirmed','quarantine')),
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE observations (
  obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL REFERENCES events(event_id)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  source TEXT NOT NULL, source_event_id TEXT NOT NULL,
  id_stable INTEGER NOT NULL DEFAULT 1,
  occurred_raw TEXT NOT NULL, timestamp INTEGER NOT NULL CHECK(timestamp>0),
  tz_policy TEXT NOT NULL, latitude REAL, longitude REAL, depth_km REAL,
  ml REAL, mw REAL, md REAL, mag_raw REAL,
  mag_canonical REAL, mag_type TEXT,
  revision TEXT NOT NULL DEFAULT 'unknown',
  transport TEXT NOT NULL DEFAULT 'http-unverified',
  cross_checked INTEGER NOT NULL DEFAULT 0,
  admit_science INTEGER NOT NULL DEFAULT 1,
  policy TEXT NOT NULL DEFAULT 'K3-compat',
  raw_status TEXT NOT NULL DEFAULT 'present'
    CHECK(raw_status IN ('present','legacy_unavailable')),
  current_version_id INTEGER REFERENCES observation_versions(version_id)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  fetched_at TEXT DEFAULT (datetime('now')),
  UNIQUE(source, source_event_id)
);
CREATE TABLE observation_versions (
  version_id INTEGER PRIMARY KEY AUTOINCREMENT,
  obs_id INTEGER NOT NULL REFERENCES observations(obs_id)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  version_no INTEGER NOT NULL,
  fetched_hash TEXT NOT NULL,
  occurred_raw TEXT NOT NULL, timestamp INTEGER NOT NULL,
  latitude REAL, longitude REAL, depth_km REAL,
  ml REAL, mw REAL, md REAL, mag_raw REAL,
  revision TEXT NOT NULL, raw_line TEXT,
  fetched_at TEXT DEFAULT (datetime('now')),
  UNIQUE(obs_id, version_no), UNIQUE(obs_id, fetched_hash)
);
CREATE TABLE match_review (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  obs_a INTEGER NOT NULL, obs_b INTEGER NOT NULL,
  score REAL NOT NULL, reason TEXT,
  decided INTEGER NOT NULL DEFAULT 0,
  decided_by TEXT, decided_at TEXT
);
CREATE TABLE merge_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  obs_id INTEGER NOT NULL, old_event INTEGER NOT NULL,
  new_event INTEGER NOT NULL, by_whom TEXT, at TEXT,
  undone INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_obs_time ON observations(timestamp);
CREATE INDEX idx_obs_src ON observations(source, source_event_id);
CREATE INDEX idx_obs_event ON observations(event_id);
CREATE VIEW v_compat AS
  SELECT e.event_id, o.occurred_raw, o.timestamp, o.latitude, o.longitude,
         o.mag_raw AS magnitude, o.mag_canonical, o.mag_type, o.source
  FROM events e JOIN observations o ON o.event_id = e.event_id;
CREATE VIEW v_typed_science AS
  SELECT e.event_id, o.timestamp,
         CASE WHEN o.mw IS NOT NULL THEN o.mw ELSE o.ml END AS analysis_mag,
         CASE WHEN o.mw IS NOT NULL THEN 'Mw' ELSE 'ML' END AS analysis_scale,
         o.source
  FROM events e JOIN observations o ON o.event_id = e.event_id
  WHERE (o.mw IS NOT NULL OR o.ml IS NOT NULL);
PRAGMA user_version=2;
"""


def fnum(x):
    if x is None:
        return "null"
    return repr(float(x))


def content_hash(occurred_raw, lat, lon, depth, ml, mw, md, revision):
    # Belgeli deterministik serilestirme (sabit sira, repr-float).
    s = "|".join([str(occurred_raw), fnum(lat), fnum(lon), fnum(depth),
                  fnum(ml), fnum(mw), fnum(md), str(revision)])
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def build_v1():
    for f in (V1, BACKUP, WORK, LIVE):
        if os.path.exists(f):
            os.remove(f)
        for suf in ("-wal", "-shm", "-journal"):
            if os.path.exists(f + suf):
                os.remove(f + suf)
    c = sqlite3.connect(V1)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(LEGACY_SCHEMA)
    base = 1788000000
    rows = []
    # 14 kandilli (ML beyanli) + 6 afad (Mw'li) + 1 emsc = 21 tipli
    for i in range(14):
        rows.append((1000 + i, f"api_k_{i}", "2026-09-%02d 10:00:00" % (i + 1),
                     base + i * 86400, 40.7, 28.5, 10.0, 1.5 + (i % 5) * 0.1,
                     1.5 + (i % 5) * 0.1, None, None, "YER", "kandilli", "marmara"))
    for i in range(6):
        rows.append((2000 + i, f"api_a_{i}", "2026-09-%02d 11:00:00" % (i + 1),
                     base + i * 86400 + 3600, 40.8, 28.6, 12.0, 2.0,
                     None, 2.0, None, "YER", "afad", "marmara"))
    rows.append((3000, "api_e_0", "2026-09-05 12:00:00", base + 4 * 86400 + 7200,
                 40.75, 28.55, 8.0, 2.2, 2.2, None, None, "YER", "emsc", "marmara"))
    # 17 duz koeri (tursuz) + yakin-zamanli cift (tursuz) = 19 tursuz
    for i in range(17):
        rows.append((500000000 + i * 7, "koeri_202609%02d_100000_%d" % (i + 1, i),
                     "2026-09-%02d 10:00:00" % (i + 1), base + i * 86400 + 7200,
                     40.71, 28.51, 9.0, 1.0 + (i % 9) * 0.2,
                     None, None, None, "YER", "koeri", "marmara"))
    rows.append((500000011, "koeri_20260918_145347_408567_288235",
                 "2026-09-18 14:53:47", base + 17 * 86400 + 52427,
                 40.8567, 28.8235, 16.4, 2.8, None, None, None, "DENIZ", "koeri", "marmara"))
    rows.append((500000018, "koeri_20260918_145537_408617_288268",
                 "2026-09-18 14:55:37", base + 17 * 86400 + 52537,
                 40.8617, 28.8268, 16.4, 2.8, None, None, None, "DENIZ", "koeri", "marmara"))
    # eksik kaynak kimlikli satir (ML beyanli -> tursuz sayisi 19 korunur)
    rows.append((4000, "", "2026-09-21 10:00:00", base + 20 * 86400,
                 40.7, 28.5, 10.0, 1.2, 1.2, None, None, "YER", "koeri", "marmara"))
    assert len(rows) == 41, len(rows)
    c.executemany(
        "INSERT INTO earthquakes (id, event_id, occurred_at, timestamp, latitude,"
        " longitude, depth_km, magnitude, magnitude_ml, magnitude_mw, magnitude_md,"
        " location, source, region_tag) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    c.commit()
    n = c.execute("SELECT COUNT(*) FROM earthquakes").fetchone()[0]
    c.close()
    return n


def backup_api(src, dst):
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def check_no_writers(path):
    """Acik yazma baglantisi provasi: IMMEDIATE islem alinamazsa yazici var."""
    try:
        c = sqlite3.connect(path, timeout=2)
        c.execute("BEGIN IMMEDIATE")
        c.execute("ROLLBACK")
        c.close()
        return True
    except sqlite3.OperationalError:
        return False


def migrate_to_v2(work_path):
    c = sqlite3.connect(work_path)
    c.execute("PRAGMA foreign_keys=OFF")
    c.executescript(V2_SCHEMA)
    c.execute("PRAGMA foreign_keys=ON")
    src = list(c.execute(
        "SELECT id, event_id, occurred_at, timestamp, latitude, longitude,"
        " depth_km, magnitude, magnitude_ml, magnitude_mw, magnitude_md,"
        " location, source, region_tag, rowid FROM earthquakes ORDER BY rowid"))
    for (i, eid, occ, ts, lat, lon, dep, mag, ml, mw, md, loc, src_name,
         rtag, rid) in src:
        if not eid:
            eid = "gen_" + hashlib.sha1(
                f"{src_name}|{occ}|{lat}|{lon}|{mag}".encode()).hexdigest()[:16]
            stable = 0
        else:
            stable = 1
        # kanonik: Mw->ML->MD (gosterim); analiz evreni ayri gorunumde
        canon, mtype = None, None
        for _t, _v in (("Mw", mw), ("ML", ml), ("MD", md)):
            if _v is not None:
                canon, mtype = float(_v), _t
                break
        if canon is None and mag is not None:
            canon, mtype = float(mag), "unknown"
        cur = c.execute(
            "INSERT INTO events (canonical_time, latitude, longitude, depth_km,"
            " mag_canonical, mag_type, status) VALUES (?,?,?,?,?,?,'candidate')",
            (ts, lat, lon, dep, canon, mtype))
        ev = cur.lastrowid
        h = content_hash(occ, lat, lon, dep, ml, mw, md, "unknown")
        cur = c.execute(
            "INSERT INTO observations (event_id, source, source_event_id, id_stable,"
            " occurred_raw, timestamp, tz_policy, latitude, longitude, depth_km,"
            " ml, mw, md, mag_raw, mag_canonical, mag_type, revision, transport,"
            " cross_checked, admit_science, policy, raw_status)"
            " VALUES ("
            "?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,"
            "0,1,'K3-compat','legacy_unavailable')",
            (ev, src_name, eid, stable, occ, ts, "Europe/Istanbul-varsayim",
             lat, lon, dep, ml, mw, md, mag, canon, mtype, "unknown",
             "http-unverified" if src_name == "koeri" else "https-verified"))
        obs = cur.lastrowid
        cur = c.execute(
            "INSERT INTO observation_versions (obs_id, version_no, fetched_hash,"
            " occurred_raw, timestamp, latitude, longitude, depth_km,"
            " ml, mw, md, mag_raw, revision, raw_line)"
            " VALUES ("
            "?,?,?,?, ?,?,?,?, ?,?,?,?"
            ",'unknown',NULL)",
            (obs, 1, h, occ, ts, lat, lon, dep, ml, mw, md, mag))
        ver = cur.lastrowid
        c.execute("UPDATE observations SET current_version_id=? WHERE obs_id=?",
                  (ver, obs))
    c.commit()
    # capraz-dogrulama: ayni current_version baska obs'a mi isaretli?
    bad = c.execute(
        "SELECT COUNT(*) FROM observations o JOIN observation_versions v"
        " ON o.current_version_id = v.version_id WHERE v.obs_id != o.obs_id"
    ).fetchone()[0]
    fk = c.execute("PRAGMA foreign_key_check").fetchall()
    integ = c.execute("PRAGMA integrity_check").fetchone()[0]
    counts = {
        "obs": c.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
        "ver": c.execute("SELECT COUNT(*) FROM observation_versions").fetchone()[0],
        "ev": c.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "uv": c.execute("PRAGMA user_version").fetchone()[0],
    }
    c.close()
    return counts, {"link_mismatch": bad, "fk": fk, "integrity": integ}
