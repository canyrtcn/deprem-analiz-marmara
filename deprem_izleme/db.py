"""
SQLite veritabanı modülü - Deprem kayıtları, haftalık/aylık agregasyon
"""
import sqlite3
import os
from datetime import datetime, timedelta
from deprem_izleme.config import MAIN_DB, WEEKLY_DB, MONTHLY_DB, DATA_DIR

# ---------------------------------------------------------------------------
# Ana deprem veritabanı
# ---------------------------------------------------------------------------

def _region_clause(region):
    """Bölge filtresi: 'marmara' geniş Marmara'yı (marmara+istanbul) kapsar."""
    if region in (None, "", "all", "tumu"):
        return "", []
    if region == "marmara":
        return "region_tag IN ('marmara','istanbul')", []
    return "region_tag = ?", [region]


def _parse_occurred_ts(occurred):
    """occurred_at -> unix epoch. Bilinmeyen formatta 0 (çökme yok)."""
    if not occurred:
        return 0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y.%m.%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
        try:
            return int(datetime.strptime(occurred[:19], fmt).timestamp())
        except (ValueError, TypeError):
            continue
    try:
        return int(datetime.fromisoformat(occurred).timestamp())
    except (ValueError, TypeError):
        return 0


def get_db(path=None):
    """SQLite bağlantısı - WAL modunda, performans için."""
    path = path or MAIN_DB
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_main_db():
    """Ana deprem tablosunu oluştur."""
    conn = get_db(MAIN_DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS earthquakes (
            id              INTEGER PRIMARY KEY,          -- sismikharita id
            event_id        TEXT UNIQUE,                  -- global unique id
            occurred_at     TEXT NOT NULL,                 -- ISO datetime
            timestamp       INTEGER NOT NULL,              -- unix epoch
            latitude        REAL NOT NULL,
            longitude       REAL NOT NULL,
            depth_km        REAL,
            magnitude       REAL,
            magnitude_ml    REAL,
            magnitude_mw    REAL,
            magnitude_md    REAL,
            location        TEXT,
            source          TEXT,
            region_tag      TEXT,                          -- 'marmara' | 'istanbul'
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_eq_timestamp ON earthquakes(timestamp);
        CREATE INDEX IF NOT EXISTS idx_eq_event_id ON earthquakes(event_id);
        CREATE INDEX IF NOT EXISTS idx_eq_region ON earthquakes(region_tag);
        CREATE INDEX IF NOT EXISTS idx_eq_mag ON earthquakes(magnitude);
    """)
    conn.commit()
    conn.close()


def insert_earthquake(eq, region_tag="marmara"):
    """Tek deprem kaydı ekle (upsert)."""
    conn = get_db(MAIN_DB)
    try:
        occurred = eq.get("occurred_at", "")
        ts = _parse_occurred_ts(occurred)
        sources = eq.get("sources") or []
        ml = mw = md = None
        for s in sources:
            if isinstance(s, dict):
                sn = s.get("name", "")
                sm = s.get("magnitude")
                if sn == "kandilli" and sm: ml = sm
                if sn == "afad" and sm: mw = sm
        conn.execute("""
            INSERT OR REPLACE INTO earthquakes
                (id, event_id, occurred_at, timestamp, latitude, longitude,
                 depth_km, magnitude, magnitude_ml, magnitude_mw, magnitude_md,
                 location, source, region_tag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            eq.get("id"),
            eq.get("event_id"),
            occurred,
            ts,
            eq.get("latitude"),
            eq.get("longitude"),
            eq.get("depth_km"),
            eq.get("magnitude"),
            ml,
            mw,
            md,
            eq.get("location"),
            eq.get("source"),
            region_tag,
        ))
        conn.commit()
    finally:
        conn.close()


def bulk_insert_earthquakes(earthquakes, region_tag="marmara"):
    """Toplu ekleme - performans için."""
    conn = get_db(MAIN_DB)
    try:
        rows = []
        for eq in earthquakes:
            occurred = eq.get("occurred_at", "")
            ts = _parse_occurred_ts(occurred)
            tag = eq.get("region_tag") or region_tag
            sources = eq.get("sources") or []
            ml = mw = md = None
            for s in sources:
                if isinstance(s, dict):
                    sn = s.get("name", "")
                    sm = s.get("magnitude")
                    if sn == "kandilli" and sm: ml = sm
                    if sn == "afad" and sm: mw = sm
            rows.append((
                eq.get("id"), eq.get("event_id"), occurred, ts,
                eq.get("latitude"), eq.get("longitude"), eq.get("depth_km"),
                eq.get("magnitude"), ml, mw, md,
                eq.get("location"), eq.get("source"), tag,
            ))

        conn.executemany("""
            INSERT OR IGNORE INTO earthquakes
                (id, event_id, occurred_at, timestamp, latitude, longitude,
                 depth_km, magnitude, magnitude_ml, magnitude_mw, magnitude_md,
                 location, source, region_tag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def get_earthquakes(since=None, until=None, min_mag=None, region=None, limit=10000):
    """Depremleri sorgula."""
    conn = get_db(MAIN_DB)
    clauses = []
    params = []
    if since:
        clauses.append("timestamp >= ?")
        params.append(int(since.timestamp()))
    if until:
        clauses.append("timestamp <= ?")
        params.append(int(until.timestamp()))
    if min_mag is not None:
        clauses.append("magnitude >= ?")
        params.append(min_mag)
    rclause, rparams = _region_clause(region)
    if rclause:
        clauses.append(rclause)
        params.extend(rparams)
    where = " AND ".join(clauses) if clauses else "1"
    rows = conn.execute(
        f"SELECT * FROM earthquakes WHERE {where} ORDER BY timestamp DESC LIMIT ?",
        params + [limit]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats(region=None):
    """Son durum istatistikleri (kesintiler Python'da hesaplanır - UTC kayması yok)."""
    conn = get_db(MAIN_DB)
    now_ts = int(datetime.now().timestamp())
    day_ago = now_ts - 86400
    week_ago = now_ts - 7 * 86400
    rclause, rparams = _region_clause(region)
    where = f"WHERE {rclause}" if rclause else ""
    row = conn.execute(f"""
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END), 0) AS son_24h,
            COALESCE(SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END), 0) AS son_7g,
            COALESCE(AVG(magnitude), 0) AS avg_mag,
            COALESCE(MAX(magnitude), 0) AS max_mag,
            COALESCE(AVG(depth_km), 0) AS avg_depth,
            MIN(timestamp) AS earliest,
            MAX(timestamp) AS latest
        FROM earthquakes {where}
    """, [day_ago, week_ago] + rparams).fetchone()
    conn.close()
    return dict(row)


# ---------------------------------------------------------------------------
# Haftalık ve Aylık Agregasyon Veritabanları
# ---------------------------------------------------------------------------

def init_weekly_db():
    conn = get_db(WEEKLY_DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS weekly_stats (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            year            INTEGER NOT NULL,
            week            INTEGER NOT NULL,
            week_start      TEXT NOT NULL,
            week_end        TEXT NOT NULL,
            region_tag      TEXT DEFAULT 'marmara',
            quake_count     INTEGER,
            min_mag         REAL,
            max_mag         REAL,
            avg_mag         REAL,
            median_mag      REAL,
            total_energy_j  REAL,       -- toplam sismik enerji (Joule)
            avg_depth_km    REAL,
            min_depth_km    REAL,
            max_depth_km    REAL,
            b_value         REAL,       -- Gutenberg-Richter b
            a_value         REAL,       -- Gutenberg-Richter a
            max_mag_expected REAL,      -- beklenen maks M (G-R'den)
            risk_score      REAL,       -- 0-1 normalized
            created_at      TEXT DEFAULT (datetime('now')),
            UNIQUE(year, week, region_tag)
        );
        CREATE INDEX IF NOT EXISTS idx_weekly_yrwk ON weekly_stats(year, week);
    """)
    conn.commit()
    conn.close()


def init_monthly_db():
    conn = get_db(MONTHLY_DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS monthly_stats (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            year            INTEGER NOT NULL,
            month           INTEGER NOT NULL,
            region_tag      TEXT DEFAULT 'marmara',
            quake_count     INTEGER,
            min_mag         REAL,
            max_mag         REAL,
            avg_mag         REAL,
            median_mag      REAL,
            total_energy_j  REAL,
            avg_depth_km    REAL,
            b_value         REAL,
            a_value         REAL,
            max_mag_expected REAL,
            risk_score      REAL,
            created_at      TEXT DEFAULT (datetime('now')),
            UNIQUE(year, month, region_tag)
        );
        CREATE INDEX IF NOT EXISTS idx_monthly_yrmo ON monthly_stats(year, month);
    """)
    conn.commit()
    conn.close()


def save_weekly_stats(stats):
    conn = get_db(WEEKLY_DB)
    conn.execute("""
        INSERT OR REPLACE INTO weekly_stats
            (year, week, week_start, week_end, region_tag,
             quake_count, min_mag, max_mag, avg_mag, median_mag,
             total_energy_j, avg_depth_km, min_depth_km, max_depth_km,
             b_value, a_value, max_mag_expected, risk_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        stats["year"], stats["week"], stats["week_start"], stats["week_end"],
        stats.get("region_tag", "marmara"),
        stats["quake_count"], stats["min_mag"], stats["max_mag"],
        stats["avg_mag"], stats["median_mag"],
        stats["total_energy_j"], stats["avg_depth_km"],
        stats["min_depth_km"], stats["max_depth_km"],
        stats["b_value"], stats["a_value"],
        stats["max_mag_expected"], stats["risk_score"],
    ))
    conn.commit()
    conn.close()


def save_monthly_stats(stats):
    conn = get_db(MONTHLY_DB)
    conn.execute("""
        INSERT OR REPLACE INTO monthly_stats
            (year, month, region_tag,
             quake_count, min_mag, max_mag, avg_mag, median_mag,
             total_energy_j, avg_depth_km,
             b_value, a_value, max_mag_expected, risk_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        stats["year"], stats["month"], stats.get("region_tag", "marmara"),
        stats["quake_count"], stats["min_mag"], stats["max_mag"],
        stats["avg_mag"], stats["median_mag"], stats["total_energy_j"],
        stats["avg_depth_km"],
        stats["b_value"], stats["a_value"],
        stats["max_mag_expected"], stats["risk_score"],
    ))
    conn.commit()
    conn.close()


def get_weekly_history(limit=52, region="marmara"):
    conn = get_db(WEEKLY_DB)
    rows = conn.execute(
        "SELECT * FROM weekly_stats WHERE region_tag=? ORDER BY year DESC, week DESC LIMIT ?",
        (region, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_monthly_history(limit=24, region="marmara"):
    conn = get_db(MONTHLY_DB)
    rows = conn.execute(
        "SELECT * FROM monthly_stats WHERE region_tag=? ORDER BY year DESC, month DESC LIMIT ?",
        (region, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# init all
init_main_db()
init_weekly_db()
init_monthly_db()
