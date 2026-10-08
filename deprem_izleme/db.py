"""
SQLite veritabanı modülü - Deprem kayıtları, haftalık/aylık agregasyon
"""
import msvcrt
import sqlite3
import os
import threading
from datetime import datetime, timedelta
from deprem_izleme.config import MAIN_DB, WEEKLY_DB, MONTHLY_DB, DATA_DIR


class MaintenanceActiveError(RuntimeError):
    """Bakim kilidi aktif: yazma reddedildi (guvenli hata, fallback yok)."""


def lock_path_for(db_path):
    """Kilit dosyasi: DB'nin yani, `<ad>.maint_lock` (surecler-arasi OS kilidi)."""
    return str(db_path) + ".maint_lock"


_tls = threading.local()


def _depth(path):
    d = getattr(_tls, "maint_depth", None)
    if d is None:
        d = {}
        _tls.maint_depth = d
    return d


class _MaintLock:
    """msvcrt DISLAYICI kilit, iki bolge (surec olurse OS serbest birakir).

    Bolge 0 (WR): yazarlar transaction boyunca tutar (sinirli bekleme).
    Bolge 1 (MAINT): bakim pencere boyunca tutar.
    Protokol (yazici): MAINT bossa -> WR al (beklemeli) -> MAINT'i
    TEKRAR kontrol et -> temizse yaz, degilse birak+reddet. Boylece
    kontrol-yazma yarisi yoktur: bakim aktifken yazici ilerleyemez,
    normal yazar-yazar rekabeti sinirli beklemeyle cozulur (sahte red yok).
    Protokol (bakim): MAINT al -> WR al (bosalim beklenir) -> ikisini tut.
    Ayni surec/thread ic ice kullanimda sayacla re-entrant.
    """

    WRITE_TIMEOUT_S = 30.0
    _WR_OFF, _MAINT_OFF = 0, 1

    def __init__(self, db_path, kind="write", timeout_s=None):
        # realpath: gorece yol, .. bilesenleri, symlink/junction cozumlenir.
        self.key = os.path.normcase(os.path.realpath(lock_path_for(db_path)))
        self.kind = kind
        self.timeout_s = (self.WRITE_TIMEOUT_S if timeout_s is None
                          else timeout_s)
        self._fh = None

    def _slot(self):
        return (self.key, self.kind)

    def _try_region(self, kind):
        d = _depth(self.key)
        slot = (self.key, kind)
        if d.get(slot, 0) > 0:
            d[slot] += 1
            return "held-owned", None
        off = self._MAINT_OFF if kind == "maint" else self._WR_OFF
        os.makedirs(os.path.dirname(self.key) or ".", exist_ok=True)
        fh = open(self.key, "a+b")
        try:
            fh.seek(off)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            try:
                fh.close()
            except Exception:
                pass
            return "busy", None
        d[slot] = 1
        return "held", fh

    def _release_slot(self, kind, fh):
        d = _depth(self.key)
        slot = (self.key, kind)
        if d.get(slot, 0) > 1:
            d[slot] -= 1
            return
        d[slot] = 0
        try:
            if fh is not None:
                try:
                    fh.seek(self._MAINT_OFF if kind == "maint" else self._WR_OFF)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                finally:
                    fh.close()
        except Exception:
            pass

    def __enter__(self):
        import time as _t
        if self.kind == "maint":
            return self._enter_maint(_t)
        entered = self._enter_write(_t)
        # Kalici durum kontrolu: GERCEK kilit altinda (yazar yolu).
        # frozen/bozuk/celiskili -> ROLLBACK esdegeri: kilit birak + red.
        try:
            from deprem_izleme import db_state as _st
            _st.check_writable()
        except Exception:
            try:
                self._release_slot("write", self._fh)
            except Exception:
                pass
            self._fh = None
            d = _depth(self.key)
            try:
                d[(self.key, "write")] = 0
            except Exception:
                pass
            raise
        return entered

    def _enter_write(self, _t):
        # 1) MAINT bossa devam (hizli red: bakim aktifse bekleme yok)
        st, _ = self._try_region("maint")
        if st == "busy":
            raise MaintenanceActiveError(
                "bakim kilidi aktif; yazma reddedildi (sonra tekrar deneyin)")
        if st == "held":
            # MAINT serbestti ve su an bizde: hemen birak (sahiplenme yok)
            self._release_slot("maint", _)
        # 2) WR al (yazar-yazar siralamasi icin sinirli bekle)
        deadline = _t.monotonic() + max(0.0, float(self.timeout_s or 0))
        fh = None
        while True:
            st, fh = self._try_region("write")
            if st in ("held", "held-owned"):
                self._fh = fh
                break
            if _t.monotonic() >= deadline:
                raise MaintenanceActiveError(
                    "yazma kilidi alinamadi (yogun rekabet olabilir;"
                    " sonra tekrar deneyin)")
            _t.sleep(0.05)
        # 3) MAINT'i TEKRAR kontrol et (yazici-bakim yarisi kapanir)
        st, _fh2 = self._try_region("maint")
        if st == "busy":
            self._release_slot("write", self._fh)
            self._fh = None
            raise MaintenanceActiveError(
                "bakim kilidi aktif; yazma reddedildi (sonra tekrar deneyin)")
        if st == "held":
            self._release_slot("maint", _fh2)
        return self

    def _enter_maint(self, _t):
        # 1) MAINT al (baskasi tutuyorsa NO-GO)
        deadline = _t.monotonic() + max(0.0, float(self.timeout_s or 0))
        mfh = None
        while True:
            st, mfh = self._try_region("maint")
            if st in ("held", "held-owned"):
                break
            if _t.monotonic() >= deadline:
                raise MaintenanceActiveError(
                    "bakim kilidi alinamadi (baska bakim/yazici aktif olabilir)")
            _t.sleep(0.2)
        # 2) WR al (yazarlar bosalana kadar; ayni deadline)
        wfh = None
        try:
            while True:
                st, wfh = self._try_region("write")
                if st in ("held", "held-owned"):
                    break
                if _t.monotonic() >= deadline:
                    raise MaintenanceActiveError(
                        "yazicilar bosalmadi; bakim NO-GO")
                _t.sleep(0.2)
        except Exception:
            self._release_slot("maint", mfh)
            raise
        self._fh = (mfh, wfh)
        return self

    def __exit__(self, *exc):
        if self.kind == "maint":
            mfh, wfh = (self._fh if isinstance(self._fh, tuple)
                        else (self._fh, None))
            self._release_slot("maint", mfh)
            self._release_slot("write", wfh)
            self._fh = None
            return False
        d = _depth(self.key)
        if d.get((self.key, "write"), 0) > 1:
            d[(self.key, "write")] -= 1
            return False
        d[(self.key, "write")] = 0
        fh, self._fh = self._fh, None
        try:
            if fh is not None:
                try:
                    fh.seek(self._WR_OFF)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                finally:
                    fh.close()
        except Exception:
            pass
        return False


def maintenance_hold(db_path, timeout_s=0):
    """Bakim penceresi kilidi (snapshot+migrate+cutover boyunca tutulur).

    Kilit alinamazsa (yazici aktif) MaintenanceActiveError -> NO-GO.
    timeout_s>0 ise sinirli beklenir, sonra yine NO-GO.
    """
    return _MaintLock(db_path, kind="maint", timeout_s=timeout_s)


def _write_guard_for_path(db_path):
    """Yazma oncesi kapi: bakim yoksa txn boyunca dislayici tutar.

    Normal yazar-yazar rekabeti sinirli beklemeyle (30sn) cozulur;
    bakim tutarken sure dolar -> MaintenanceActiveError (fallback yok).
    """
    return _MaintLock(db_path)


def _write_guard_for_conn(conn):
    """Acik baglantinin dosyasina gore kapi (PRAGMA database_list)."""
    try:
        row = conn.execute("PRAGMA database_list").fetchall()
        path = (row[0][2] if row else "") or ""
    except Exception:
        path = ""
    if not path or path == ":memory:":
        class _Noop:
            def __enter__(self): return self
            def __exit__(self, *e): return False
        return _Noop()
    return _MaintLock(path)

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
    conn.execute("PRAGMA busy_timeout=5000")
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


def insert_earthquake(eq, region_tag="marmara", db_path=None):
    """Tek deprem kaydı ekle (upsert).

    db_path v2 semasiysa gozlem yazimina yonlenir (OR REPLACE YOK);
    legacy'de davranis aynen korunur.
    """
    path = db_path or MAIN_DB
    conn = get_db(path)
    if _is_v2_conn(conn):
        try:
            with _write_guard_for_path(path):
                return _insert_earthquake_v2(conn, eq, region_tag)
        finally:
            conn.close()
    try:
        with _write_guard_for_path(path):
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


def _obs_measurements(eq, region_tag="marmara"):
    """Kayit sozlugunden gozlem olculerini cikar (tek normalizasyon).

    Doner: dict(ml, mw, md, mag_raw, mag_type, revision, transport,
    location, region_tag). insert + fetch-hash ayni fonksiyonu kullanir
    (revizyon karsilastirmasi tutarli olur).
    """
    ml = eq.get("magnitude_ml")
    mw = eq.get("magnitude_mw")
    md = eq.get("magnitude_md")
    if ml is None and mw is None and md is None:
        for s in (eq.get("sources") or []):
            if isinstance(s, dict):
                sn, sm = s.get("name", ""), s.get("magnitude")
                if sn == "kandilli" and sm is not None and ml is None:
                    ml = sm
                if sn == "afad" and sm is not None and mw is None:
                    mw = sm
    mag_raw = eq.get("magnitude")
    mag_type = None
    for _t, _v in (("Mw", mw), ("ML", ml), ("MD", md)):
        if _v is not None:
            mag_type = _t
            break
    if mag_type is None:
        mag_type = "unknown"
    rev = eq.get("revision", "unknown")
    tv = eq.get("transport_verified")
    if tv is None:
        transport = ("http-unverified" if eq.get("source") == "koeri"
                     else "https-verified")
    else:
        transport = "https-verified" if tv else "http-unverified"
    return {"ml": ml, "mw": mw, "md": md, "mag_raw": mag_raw,
            "mag_type": mag_type, "revision": rev, "transport": transport,
            "location": eq.get("location"),
            "region_tag": eq.get("region_tag") or region_tag}


def _insert_earthquake_v2(conn, eq, region_tag):
    """v2 yazma: gozlem + surum (ezme yok, revizyon korunur)."""
    occurred = eq.get("occurred_at", "")
    ts = _parse_occurred_ts(occurred)
    m = _obs_measurements(eq, region_tag)
    ml, mw, md = m["ml"], m["mw"], m["md"]
    mag_raw, mag_type = m["mag_raw"], m["mag_type"]
    rev, transport = m["revision"], m["transport"]
    tag = m["region_tag"]
    obs, vno, created = insert_observation(
        conn, eq.get("source") or "unknown", eq.get("event_id") or "",
        occurred, ts, eq.get("latitude"), eq.get("longitude"),
        eq.get("depth_km"), ml, mw, md, mag_raw, revision=rev,
        transport=transport, raw_line=eq.get("raw_line"),
        raw_status=eq.get("raw_status", "present"),
        tz_policy=eq.get("tz_policy", "Europe/Istanbul-varsayim"),
        location=m["location"], region_tag=tag)
    conn.commit()
    return obs


def bulk_insert_earthquakes(earthquakes, region_tag="marmara", db_path=None):
    """Toplu ekleme - performans için."""
    path = db_path or MAIN_DB
    conn = get_db(path)
    if _is_v2_conn(conn):
        try:
            with _write_guard_for_path(path):
                n = 0
                for eq in (earthquakes or []):
                    tag = eq.get("region_tag") or region_tag
                    _insert_earthquake_v2(conn, eq, tag)
                    n += 1
                return n
        finally:
            conn.close()
    try:
        with _write_guard_for_path(path):
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


def _is_v2_conn(conn):
    """Acik baglantida v2 tablolari var mi (yönlendirme karari)."""
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        return {"events", "observations", "observation_versions"} <= tables
    except Exception:
        return False


def _get_stats_v2(conn, region):
    """v2 istatistik: K3-compat evreni (tum gozlemler; davranis paritesi)."""
    now_ts = int(datetime.now().timestamp())
    day_ago = now_ts - 86400
    week_ago = now_ts - 7 * 86400
    rclause, rparams = _region_clause(region)
    if rclause:
        rclause = rclause.replace("region_tag", "o.region_tag")
    where = f"WHERE {rclause}" if rclause else ""
    row = conn.execute(f"""
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN o.timestamp >= ? THEN 1 ELSE 0 END), 0) AS son_24h,
            COALESCE(SUM(CASE WHEN o.timestamp >= ? THEN 1 ELSE 0 END), 0) AS son_7g,
            COALESCE(AVG(o.mag_raw), 0) AS avg_mag,
            COALESCE(MAX(o.mag_raw), 0) AS max_mag,
            COALESCE(AVG(o.depth_km), 0) AS avg_depth,
            MIN(o.timestamp) AS earliest,
            MAX(o.timestamp) AS latest
        FROM observations o {where}
    """, [day_ago, week_ago] + rparams).fetchone()
    return dict(row)


def get_earthquakes(since=None, until=None, min_mag=None, region=None, limit=10000,
                    db_path=None):
    """Depremleri sorgula.

    db_path verilmezse MAIN_DB. v2 semasinda K3-compat gorunumunden
    legacy-sekilli sozlukler doner (davranis paritesi).
    """
    path = db_path or MAIN_DB
    conn = get_db(path)
    if _is_v2_conn(conn):
        try:
            return _get_earthquakes_v2(conn, since, until, min_mag, region, limit)
        finally:
            conn.close()
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


def _get_earthquakes_v2(conn, since, until, min_mag, region, limit):
    """v2 okuma: K3-compat gorunumunden legacy-sekilli kayitlar."""
    clauses = []
    params = []
    if since:
        clauses.append("o.timestamp >= ?")
        params.append(int(since.timestamp()))
    if until:
        clauses.append("o.timestamp <= ?")
        params.append(int(until.timestamp()))
    if min_mag is not None:
        clauses.append("o.mag_raw >= ?")
        params.append(min_mag)
    rclause, rparams = _region_clause(region)
    if rclause:
        clauses.append(rclause.replace("region_tag", "o.region_tag"))
        params.extend(rparams)
    where = " AND ".join(clauses) if clauses else "1"
    rows = conn.execute(
        "SELECT o.obs_id AS id, o.source_event_id AS event_id,"
        " o.occurred_raw AS occurred_at, o.timestamp, o.latitude, o.longitude,"
        " o.depth_km, o.mag_raw AS magnitude,"
        " o.ml AS magnitude_ml, o.mw AS magnitude_mw, o.md AS magnitude_md,"
        " o.location, o.source, o.region_tag,"
        " o.mag_canonical AS magnitude_canonical, o.mag_type, o.revision,"
        " o.transport, o.cross_checked, o.admit_science,"
        " o.current_version_id"
        f" FROM observations o WHERE {where} ORDER BY o.timestamp DESC LIMIT ?",
        params + [limit]).fetchall()
    out = []
    for r in rows:
        try:
            d = dict(r)
        except Exception:
            d = {}
        d.setdefault("transport_verified", d.get("transport") == "https-verified")
        d.setdefault("magnitude_missing", d.get("magnitude") is None)
        d.setdefault("mag_inferred", d.get("mag_type") in (None, "unknown"))
        out.append(d)
    return out


def get_stats(region=None, db_path=None):
    """Son durum istatistikleri (kesintiler Python'da hesaplanır - UTC kayması yok)."""
    path = db_path or MAIN_DB
    conn = get_db(path)
    if _is_v2_conn(conn):
        try:
            return _get_stats_v2(conn, region)
        finally:
            conn.close()
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
    with _write_guard_for_path(WEEKLY_DB):
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
    with _write_guard_for_path(MONTHLY_DB):
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


# ============================================================================
# K3-M1: Event-Observation-Version mimarisi (sentetik/test + acik tetikleme)
# ----------------------------------------------------------------------------
# - Bu bolum CANLI DB'yi kendiliginden degistirmez: v2 semasi yalnizca
#   init_v2_schema() acik cagrildiginda kurulur; migrate_v1_to_v2() canli
#   MAIN_DB yolunu reddeder (K3-M2 onayi olmadan canli goc YOK).
# - Uretim okuma/yazma yollari (insert_earthquake/get_earthquakes) aynen
#   legacy tabloda calisir; davranis degisikligi regresyon sayilir.
# ============================================================================

V2_USER_VERSION = 2
HASH_SER_VERSION = "v1"


def get_schema_version(conn_or_path):
    """0=legacy/bilinmiyor-yok, 2=v2, >2=gelecek (uyumsuz)."""
    close = False
    try:
        if isinstance(conn_or_path, str):
            import sqlite3 as _sq
            conn = _sq.connect(f"file:{conn_or_path}?mode=ro", uri=True)
            close = True
        else:
            conn = conn_or_path
        try:
            v = conn.execute("PRAGMA user_version").fetchone()[0]
        except Exception:
            v = 0
        tables = {r[0] for r in
                  conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if close:
            conn.close()
        if "observations" in tables and "observation_versions" in tables \
                and "events" in tables:
            return int(v or 0)
        if "earthquakes" in tables:
            return 0
        return -1
    except Exception:
        try:
            if close:
                conn.close()
        except Exception:
            pass
        return -1


def check_db_compat(path=None):
    """Baslangic uyumluluk kapisi: (tamam: bool, mesaj: str).

    legacy(0) -> sessiz devam; v2(2) -> devam; gelecek/bilinmeyen ->
    guvenli hata (otomatik goc YOK, veri silinmez).
    """
    p = path or MAIN_DB
    v = get_schema_version(p)
    if v == 0 or v == 2:
        return True, "ok"
    return False, (f"Veritabani surumu desteklenmiyor (user_version={v}). "
                   "Lutfen uygulamayi guncelleyin; otomatik goc yapilmadi, "
                   "verileriniz degistirilmedi.")


def content_hash_v1(occurred_raw, lat, lon, depth, ml, mw, md, revision):
    """Deterministik icerik hash'i (belgeli serilestirme v1).

    Format: "v1|" + "|".join([occurred_raw, fnum(lat), ...]) ; floatlar
    repr() ile (platformdan bagimsiz metin), None -> "null".
    """
    import hashlib as _hl

    def _f(x):
        return "null" if x is None else repr(float(x))

    s = "v1|" + "|".join([str(occurred_raw), _f(lat), _f(lon), _f(depth),
                           _f(ml), _f(mw), _f(md), str(revision)])
    return _hl.sha256(s.encode("utf-8")).hexdigest()


_V2_DDL = """
CREATE TABLE IF NOT EXISTS events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_time INTEGER NOT NULL, latitude REAL NOT NULL,
  longitude REAL NOT NULL, depth_km REAL,
  mag_canonical REAL, mag_type TEXT,
  status TEXT NOT NULL DEFAULT 'candidate'
    CHECK(status IN ('candidate','confirmed','quarantine')),
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS observations (
  obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL REFERENCES events(event_id)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  source TEXT NOT NULL, source_event_id TEXT NOT NULL,
  id_stable INTEGER NOT NULL DEFAULT 1,
  occurred_raw TEXT NOT NULL, timestamp INTEGER NOT NULL CHECK(timestamp>0),
  tz_policy TEXT NOT NULL, latitude REAL, longitude REAL, depth_km REAL,
  ml REAL, mw REAL, md REAL, mag_raw REAL,
  mag_canonical REAL, mag_type TEXT,
  location TEXT, region_tag TEXT,
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
CREATE TABLE IF NOT EXISTS observation_versions (
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
CREATE TABLE IF NOT EXISTS match_review (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  obs_a INTEGER NOT NULL, obs_b INTEGER NOT NULL,
  score REAL NOT NULL, reason TEXT,
  decided INTEGER NOT NULL DEFAULT 0,
  decided_by TEXT, decided_at TEXT
);
CREATE TABLE IF NOT EXISTS merge_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  obs_id INTEGER NOT NULL, old_event INTEGER NOT NULL,
  new_event INTEGER NOT NULL, by_whom TEXT, at TEXT,
  undone INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_obs_time ON observations(timestamp);
CREATE INDEX IF NOT EXISTS idx_obs_src ON observations(source, source_event_id);
CREATE INDEX IF NOT EXISTS idx_obs_event ON observations(event_id);
CREATE VIEW IF NOT EXISTS v_compat AS
  SELECT e.event_id, o.obs_id, o.occurred_raw, o.timestamp,
         o.latitude, o.longitude, o.depth_km, o.mag_raw AS magnitude,
         o.ml AS magnitude_ml, o.mw AS magnitude_mw, o.md AS magnitude_md,
         o.mag_canonical, o.mag_type, o.location, o.source, o.region_tag,
         o.revision
  FROM events e JOIN observations o ON o.event_id = e.event_id;
CREATE VIEW IF NOT EXISTS v_typed_science AS
  SELECT e.event_id, o.obs_id, o.timestamp,
         CASE WHEN o.mw IS NOT NULL THEN o.mw ELSE o.ml END AS analysis_mag,
         CASE WHEN o.mw IS NOT NULL THEN 'Mw' ELSE 'ML' END AS analysis_scale,
         o.source
  FROM events e JOIN observations o ON o.event_id = e.event_id
  WHERE (o.mw IS NOT NULL OR o.ml IS NOT NULL);
"""


def init_v2_schema(conn):
    """v2 semasini + capraz-bag tetikleyicisini kurar (acik cagri).

    Tetikleyici: current_version_id baska gozleme ait surumu gosteremez;
    ihlal ROLLBACK ile reddedilir (uygulama hatasina degil, SQL'e emanet).
    """
    conn.executescript(_V2_DDL)
    conn.execute("DROP TRIGGER IF EXISTS trg_obs_version_link")
    conn.execute("""
        CREATE TRIGGER trg_obs_version_link
        BEFORE INSERT ON observations
        WHEN NEW.current_version_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM observation_versions
                          WHERE version_id = NEW.current_version_id
                            AND obs_id = NEW.obs_id)
        BEGIN
          SELECT RAISE(ABORT, 'current_version_id baska gozleme ait');
        END""")
    conn.execute("""
        CREATE TRIGGER trg_obs_version_link_upd
        BEFORE UPDATE OF current_version_id ON observations
        WHEN NEW.current_version_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM observation_versions
                          WHERE version_id = NEW.current_version_id
                            AND obs_id = NEW.obs_id)
        BEGIN
          SELECT RAISE(ABORT, 'current_version_id baska gozleme ait');
        END""")
    conn.execute(f"PRAGMA user_version={V2_USER_VERSION}")
    conn.commit()


# init all (test izolasyonu: DEPREM_SKIP_DB_INIT=1 ise baglanti acilmaz)
if os.environ.get("DEPREM_SKIP_DB_INIT") != "1":
    init_main_db()
    init_weekly_db()
    init_monthly_db()


# ============================================================================
# K3-M1 (devam): gozlem yazma, analiz katalogu, sentetik goc
# ============================================================================

def _synthetic_event_id(source, occurred_raw, lat, lon, mag):
    import hashlib as _hl
    return "gen_" + _hl.sha1(
        f"{source}|{occurred_raw}|{lat}|{lon}|{mag}".encode()).hexdigest()[:16]


def insert_observation(conn, source, source_event_id, occurred_raw, timestamp,
                       latitude, longitude, depth_km=None, ml=None, mw=None,
                       md=None, mag_raw=None, revision="unknown",
                       transport="http-unverified", raw_line=None,
                       raw_status="present", tz_policy="Europe/Istanbul-varsayim",
                       location=None, region_tag=None):
    """Yeni gozlem yaz (OR REPLACE YOK).

    - Ayni (source, source_event_id) varsa: hash karsilastir; ayniysa
      mevcutu dondur (surum uretilmez); degismisse yeni surum + isaretci
      guncelleme (tek transaction). Eski surum silinmez.
    - Doner: (obs_id, version_no, created: bool).
    """
    h = content_hash_v1(occurred_raw, latitude, longitude, depth_km,
                        ml, mw, md, revision)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass
    if not source_event_id:
        source_event_id = _synthetic_event_id(source, occurred_raw,
                                              latitude, longitude, mag_raw)
        id_stable = 0
    else:
        id_stable = 1
    if mag_raw is None:
        for _t, _v in (("Mw", mw), ("ML", ml), ("MD", md)):
            if _v is not None:
                mag_raw, mag_type = float(_v), _t
                break
        else:
            mag_raw, mag_type = None, "unknown"
    else:
        mag_type = None
        for _t, _v in (("Mw", mw), ("ML", ml), ("MD", md)):
            if _v is not None:
                mag_type = _t
                break
        if mag_type is None:
            mag_type = "unknown"
    with _write_guard_for_conn(conn):
        with conn:
            cur = conn.execute(
                "SELECT obs_id, event_id, current_version_id FROM observations"
                " WHERE source=? AND source_event_id=?", (source, source_event_id))
            row = cur.fetchone()
            if row is None:
                cur = conn.execute(
                    "INSERT INTO events (canonical_time, latitude, longitude,"
                    " depth_km, mag_canonical, mag_type, status)"
                    " VALUES (?,?,?,?,?,?,'candidate')",
                    (timestamp, latitude, longitude, depth_km, mag_raw, mag_type))
                ev = cur.lastrowid
                cur = conn.execute(
                    "INSERT INTO observations (event_id, source, source_event_id,"
                    " id_stable, occurred_raw, timestamp, tz_policy, latitude,"
                    " longitude, depth_km, ml, mw, md, mag_raw, mag_canonical,"
                    " mag_type, location, region_tag, revision, transport, raw_status)"
                    " VALUES (?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?,?)",
                    (ev, source, source_event_id, id_stable, occurred_raw,
                     timestamp, tz_policy, latitude, longitude, depth_km,
                     ml, mw, md, mag_raw, mag_raw, mag_type, location, region_tag,
                     revision, transport, raw_status))
                obs = cur.lastrowid
                cur = conn.execute(
                    "INSERT INTO observation_versions (obs_id, version_no,"
                    " fetched_hash, occurred_raw, timestamp, latitude, longitude,"
                    " depth_km, ml, mw, md, mag_raw, revision, raw_line)"
                    " VALUES (?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?)",
                    (obs, 1, h, occurred_raw, timestamp, latitude, longitude,
                     depth_km, ml, mw, md, mag_raw, revision, raw_line))
                ver = cur.lastrowid
                conn.execute("UPDATE observations SET current_version_id=?"
                             " WHERE obs_id=?", (ver, obs))
                return obs, 1, True
            obs, ev, cur_ver = row[0], row[1], row[2]
            same = False
            if cur_ver is not None:
                r = conn.execute("SELECT fetched_hash FROM observation_versions"
                                 " WHERE version_id=?", (cur_ver,)).fetchone()
                same = bool(r and r[0] == h)
            if same:
                vno = conn.execute("SELECT version_no FROM observation_versions"
                                   " WHERE version_id=?", (cur_ver,)).fetchone()[0]
                return obs, vno, False
            vno = conn.execute("SELECT COALESCE(MAX(version_no),0)+1"
                               " FROM observation_versions WHERE obs_id=?",
                               (obs,)).fetchone()[0]
            cur = conn.execute(
                "INSERT INTO observation_versions (obs_id, version_no,"
                " fetched_hash, occurred_raw, timestamp, latitude, longitude,"
                " depth_km, ml, mw, md, mag_raw, revision, raw_line)"
                " VALUES (?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?)",
                (obs, vno, h, occurred_raw, timestamp, latitude, longitude,
                 depth_km, ml, mw, md, mag_raw, revision, raw_line))
            ver = cur.lastrowid
            conn.execute(
                "UPDATE observations SET occurred_raw=?, timestamp=?,"
                " latitude=?, longitude=?, depth_km=?, ml=?, mw=?, md=?,"
                " mag_raw=?, location=?, region_tag=?, revision=?, transport=?,"
                " current_version_id=? WHERE obs_id=?",
                (occurred_raw, timestamp, latitude, longitude, depth_km,
                 ml, mw, md, mag_raw, location, region_tag, revision, transport,
                 ver, obs))
            return obs, vno, True


def get_analysis_catalog(conn, policy="K3-compat"):
    """Analiz katalogu gorunumu (K3: bugunku evrenin birebiri).

    policy="K3-compat" -> v_compat (tum gozlemler; davranis korunur).
    typed-science ayri fonksiyondadir ve ANALIZLERE BAGLI DEGILDIR.
    """
    if policy != "K3-compat":
        raise ValueError("K3'te yalnizca K3-compat politikasi acik")
    rows = conn.execute("SELECT * FROM v_compat ORDER BY timestamp DESC").fetchall()
    out = []
    for r in rows:
        try:
            out.append(dict(r))
        except Exception:
            out.append({"event_id": r[0], "obs_id": r[1], "occurred_raw": r[2],
                        "timestamp": r[3], "latitude": r[4], "longitude": r[5],
                        "depth_km": r[6], "magnitude": r[7],
                        "magnitude_ml": r[8], "magnitude_mw": r[9],
                        "magnitude_md": r[10], "magnitude_canonical": r[11],
                        "mag_type": r[12], "location": r[13], "source": r[14],
                        "region_tag": r[15], "revision": r[16]})
    return out


def get_typed_catalog(conn):
    """typed-science gorunumu (K3'te ANALIZLERE BAGLI DEGIL; tani/karsilastirma)."""
    return [dict(r) for r in
            conn.execute("SELECT * FROM v_typed_science ORDER BY timestamp DESC")]


def require_app_closed(exe_names=("deprem-analiz-marmara.exe",)):
    """Goc onkosulu: uygulamanin calismadigini dogrula (islem adi + kilit).

    Doner: (tamam: bool, mesaj). Basarisizsa goc BASLAMAZ.
    """
    import subprocess as _sp
    try:
        out = _sp.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                      text=True, timeout=30).stdout.lower()
    except Exception as e:
        return False, f"islem listesi okunamadi: {e}"
    for name in exe_names:
        if name.lower() in out:
            return False, f"uygulama calisiyor ({name}); kapatmadan goc yok"
    return True, "ok"


def migrate_v1_to_v2(src_path, dst_path):
    """Sentetik/test gocu: src v1 -> dst v2 (kopya uzerinde).

    CANLI MAIN_DB reddedilir (K3-M2 onayi olmadan canli goc YOK).
    Doner: {"obs","ver","ev","user_version"} + dogrulama sozlugu.
    """
    import shutil as _sh
    if os.path.abspath(dst_path) == os.path.abspath(MAIN_DB):
        raise RuntimeError("canli DB'ye goc K3-M2 onayi olmadan yasak")
    if os.path.abspath(src_path) == os.path.abspath(MAIN_DB):
        raise RuntimeError("canli DB okuma-disi kullanim yasak (K3-M1)")
    ok, msg = require_app_closed()
    if not ok:
        raise RuntimeError(msg)
    _hold = maintenance_hold(dst_path)
    _hold.__enter__()
    try:
        _sh.copy(src_path, dst_path)
        for suf in ("-wal", "-shm", "-journal"):
            try:
                if os.path.exists(src_path + suf):
                    _sh.copy(src_path + suf, dst_path + suf)
            except Exception:
                pass
        import sqlite3 as _sq
        conn = _sq.connect(dst_path)
        try:
            init_v2_schema(conn)
            src_rows = conn.execute(
                "SELECT event_id, occurred_at, timestamp, latitude, longitude,"
                " depth_km, magnitude, magnitude_ml, magnitude_mw, magnitude_md,"
                " location, source, region_tag, rowid FROM earthquakes ORDER BY rowid"
            ).fetchall()
            for (eid, occ, ts, lat, lon, dep, mag, ml, mw, md,
                 loc, src_name, rtag, rid) in src_rows:
                rev = "unknown"
                insert_observation(
                    conn, src_name or "unknown", eid or "",
                    occ, ts, lat, lon, dep, ml, mw, md, mag,
                    revision=rev,
                    transport=("http-unverified" if src_name == "koeri"
                               else "https-verified"),
                    raw_line=None, raw_status="legacy_unavailable",
                    tz_policy="Europe/Istanbul-varsayim",
                    location=loc, region_tag=rtag)
            counts = {
                "legacy": len(src_rows),
                "obs": conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
                "ver": conn.execute("SELECT COUNT(*) FROM observation_versions").fetchone()[0],
                "ev": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                "uv": conn.execute("PRAGMA user_version").fetchone()[0],
            }
            ver = {
                "fk": conn.execute("PRAGMA foreign_key_check").fetchall(),
                "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
                "link_mismatch": conn.execute(
                    "SELECT COUNT(*) FROM observations o JOIN observation_versions v"
                    " ON o.current_version_id = v.version_id"
                    " WHERE v.obs_id != o.obs_id").fetchone()[0],
            }
            conn.commit()
            return counts, ver
        finally:
            conn.close()
    finally:
        _hold.__exit__(None, None, None)
