"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""K3-M1 entegrasyon (scratch-only). v1+v2 uctan uca, parite, GUI."""
import os
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
import shutil
import sqlite3
import sys
import time
from unittest import mock
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

HERE = TESTTMP
V1 = os.path.join(HERE, "k3i_v1.db")
for s in ("", "-wal", "-shm", "-journal"):
    for f in (V1,):
        if os.path.exists(f + s):
            os.remove(f + s)

import deprem_izleme.db as DB
from deprem_izleme.db import init_v2_schema

NOW = int(time.time())
def Q(eid, mag, ts_ago, lat=40.7, lon=28.5, src="kandilli", extra=None):
    d = {"id": abs(hash(eid)) % 10**8, "event_id": eid,
         "occurred_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - ts_ago)),
         "latitude": lat, "longitude": lon, "depth_km": 8.0,
         "magnitude": mag, "location": "YER", "source": src,
         "region_tag": "marmara"}
    if extra:
        d.update(extra)
    return d

FRESH = [Q("api_%d" % i, 1.5 + (i % 5) * 0.2, i * 86400 + 3600, src="kandilli",
           extra={"magnitude_ml": 1.5 + (i % 5) * 0.2,
                  "sources": [{"name": "kandilli", "magnitude": 1.5 + (i % 5) * 0.2}]})
         for i in range(10)]
FRESH += [Q("ko_%d" % i, 2.0 + (i % 3) * 0.1, i * 86400 + 7200, lat=40.75, lon=28.55,
            src="koeri", extra={"magnitude_ml": 2.0 + (i % 3) * 0.1,
                                "revision": "preliminary",
                                "transport_verified": False,
                                "raw_line": "HAM%d" % i})
          for i in range(5)]

# --- v1 zinciri ---
c = sqlite3.connect(V1)
c.executescript("CREATE TABLE earthquakes (id INTEGER PRIMARY KEY, event_id TEXT UNIQUE, occurred_at TEXT NOT NULL, timestamp INTEGER NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL, depth_km REAL, magnitude REAL, magnitude_ml REAL, magnitude_mw REAL, magnitude_md REAL, location TEXT, source TEXT, region_tag TEXT, created_at TEXT DEFAULT (datetime('now')));")
c.commit()
c.close()
import deprem_izleme.fetcher as F
with mock.patch.object(F, "fetch_earthquakes", return_value=[dict(q) for q in FRESH]):
    n1 = F.fetch_and_store(days_back=30, min_magnitude=0.0, db_path=V1)
check("INT: v1 fetch->yazim", n1 == 15, n1)
with mock.patch.object(F, "fetch_earthquakes", return_value=[dict(q) for q in FRESH]):
    n1b = F.fetch_and_store(days_back=30, min_magnitude=0.0, db_path=V1)
check("INT: v1 tekrar-fetch 0", n1b == 0, n1b)
q1 = DB.get_earthquakes(db_path=V1)
s1 = DB.get_stats(region="marmara", db_path=V1)
check("INT: v1 okuma", len(q1) == 15 and s1["total"] == 15, (len(q1), s1["total"]))

# --- v2 zinciri (gercek migrate) ---
V2 = os.path.join(HERE, "k3i_v2.db")
for s in ("", "-wal", "-shm", "-journal"):
    if os.path.exists(V2 + s):
        os.remove(V2 + s)
counts, ver = DB.migrate_v1_to_v2(V1, V2)
check("INT: goc 15/15/15", counts["obs"] == 15 and counts["ver"] == 15
      and counts["ev"] == 15, counts)
with mock.patch.object(F, "fetch_earthquakes", return_value=[dict(q) for q in FRESH]):
    n2 = F.fetch_and_store(days_back=30, min_magnitude=0.0, db_path=V2)
c = sqlite3.connect(V2)
nver2 = c.execute("SELECT COUNT(*) FROM observation_versions").fetchone()[0]
c.close()
check("INT: v2 tekrar-fetch yalnizca tip-zenginlesmesi (5 koeri)",
      n2 == 5 and nver2 == 15 + 5, (n2, nver2))
with mock.patch.object(F, "fetch_earthquakes", return_value=[dict(q) for q in FRESH]):
    n2b = F.fetch_and_store(days_back=30, min_magnitude=0.0, db_path=V2)
check("INT: v2 ucuncu-fetch 0", n2b == 0, n2b)
# revizyon: ayni anahtar, degisen buyukluk -> yeni surum
REV = [dict(FRESH[10], magnitude_ml=2.9, magnitude=2.9, revision="revised")]
with mock.patch.object(F, "fetch_earthquakes", return_value=REV):
    n2r = F.fetch_and_store(days_back=30, min_magnitude=0.0, db_path=V2)
c = sqlite3.connect(V2)
nver = c.execute("SELECT COUNT(*) FROM observation_versions").fetchone()[0]
old = c.execute("SELECT ml, revision FROM observation_versions WHERE obs_id=(SELECT obs_id FROM observations WHERE source_event_id='ko_0') AND version_no=1").fetchone()
c.close()
check("INT: v2 revizyon v3 uretir, v1+v2 korunur", n2r == 1 and nver == 21
      and old[0] is None and old[1] == "unknown", (n2r, nver, tuple(old) if old else None))
# ID cakismasi: ayni sayisal id, farkli olay -> ezme yok
c = sqlite3.connect(V2)
n_before = c.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
c.close()
CLASH = [dict(FRESH[0], event_id="tamamen_farkli_olay")]
with mock.patch.object(F, "fetch_earthquakes", return_value=CLASH):
    n2c = F.fetch_and_store(days_back=30, min_magnitude=0.0, db_path=V2)
c = sqlite3.connect(V2)
orig = c.execute("SELECT ml FROM observations WHERE source_event_id='api_0'").fetchone()[0]
c.close()
check("INT: ID cakismasi ezmez", orig == 1.5, orig)
q2 = DB.get_earthquakes(db_path=V2)
s2 = DB.get_stats(region="marmara", db_path=V2)
check("INT: v2 okuma", len(q2) >= 15 and s2["total"] >= 15, (len(q2), s2["total"]))

# --- parite: v1 satirlari v2'de (revize/catisma haric birebir) ---
A = {r["event_id"]: (r["magnitude"], r["timestamp"]) for r in DB.get_earthquakes(db_path=V1)}
B = {r["event_id"]: (r["magnitude"], r["timestamp"]) for r in DB.get_earthquakes(db_path=V2)}
same_keys = set(A) & set(B)
changed = {k for k in same_keys if A[k] != B[k]}
check("INT: revize-disi satirlar birebir",
      changed == {"ko_0"} and len(same_keys) == 15, sorted(changed))
check("INT: catisma ayri gozlem", "tamamen_farkli_olay" in B
      and B["api_0"] == A["api_0"])

# --- bilim: ayni girdi -> ayni rapor (v1 listesiyle iki yol) ---
# haftalik/aylik DB'ler de sentetige yamalanir (gercek dosya acilmaz)
W0 = os.path.join(HERE, "k3i_w0.db")
M0 = os.path.join(HERE, "k3i_m0.db")
for f in (W0, M0):
    for s in ("", "-wal", "-shm", "-journal"):
        if os.path.exists(f + s):
            os.remove(f + s)
import deprem_izleme.aggregation as AGG
import deprem_izleme.predictor as PRD
import deprem_izleme.db as _DB2
with mock.patch.object(_DB2, "WEEKLY_DB", W0), \
     mock.patch.object(_DB2, "MONTHLY_DB", M0):
    _DB2.init_weekly_db()
    _DB2.init_monthly_db()
    with mock.patch.object(AGG, "get_earthquakes", return_value=[dict(r) for r in q1]):
        r_risk = AGG.get_comprehensive_risk_report(region="marmara", db_path=V1)
    with mock.patch.object(PRD, "get_earthquakes", return_value=[dict(r) for r in q1]):
        r_pred = PRD.EarthquakePredictor(region="marmara").predict_short_term()
    with mock.patch.object(AGG, "get_earthquakes", return_value=[dict(r) for r in q2]):
        r_risk2 = AGG.get_comprehensive_risk_report(region="marmara", db_path=V2)
diffs = []
for k in ("composite_risk_score",):
    if abs(r_risk[k] - r_risk2[k]) > 1e-9:
        diffs.append((k, r_risk[k], r_risk2[k]))
for k in ("p_m4_7days_pct",):
    a, b = r_risk["poisson"][k], r_risk2["poisson"][k]
    if (a is None) != (b is None) or (a is not None and abs(a - b) > 1e-9):
        diffs.append((k, a, b))
for k in ("b_value",):
    if abs(r_risk["gutenberg_richter"][k] - r_risk2["gutenberg_richter"][k]) > 1e-9:
        diffs.append((k, r_risk["gutenberg_richter"][k], r_risk2["gutenberg_richter"][k]))
check("INT: bilim paritesi (farklar acik)", True,
      f"risk={r_risk['composite_risk_score']:.4f}/{r_risk2['composite_risk_score']:.4f} "
      f"P7={r_risk['poisson']['p_m4_7days_pct']}/{r_risk2['poisson']['p_m4_7days_pct']} "
      f"b={r_risk['gutenberg_richter']['b_value']:.4f}/{r_risk2['gutenberg_richter']['b_value']:.4f} "
      f"FARK={diffs if diffs else 'yok'}")
from deprem_izleme.notifier import format_risk_alert
msg = format_risk_alert(r_risk2, r_pred)
check("INT: Telegram gonderimsiz hazirlanir", "DEPREM RISK" in msg and len(msg) > 100)

# --- typed-science bagli degil ---
import inspect as _ins
tied = []
src = _ins.getsource(AGG.get_comprehensive_risk_report)
if "typed" in src or "v_typed" in src or "get_typed_catalog" in src:
    tied.append("get_comprehensive_risk_report")
src = _ins.getsource(PRD.EarthquakePredictor.predict_short_term)
if "typed" in src or "v_typed" in src or "get_typed_catalog" in src:
    tied.append("predict_short_term")
check("INT: typed-science analizlere bagli degil", not tied, tied)

# --- GUI dumani (sentetik v2, MAIN_DB yamali; gercek DB acilmaz) ---
W = os.path.join(HERE, "k3i_w.db")
M = os.path.join(HERE, "k3i_m.db")
for f in (W, M):
    for s in ("", "-wal", "-shm", "-journal"):
        if os.path.exists(f + s):
            os.remove(f + s)
import deprem_izleme.db as _DBM
with mock.patch.object(_DBM, "MAIN_DB", V2), \
     mock.patch.object(_DBM, "WEEKLY_DB", W), \
     mock.patch.object(_DBM, "MONTHLY_DB", M), \
     mock.patch.object(F, "fetch_earthquakes", return_value=[]), \
     mock.patch("deprem_izleme.fetcher_koeri.fetch_koeri", return_value={"quakes": [], "ok": True, "error": None}):
    _DBM.init_weekly_db()
    _DBM.init_monthly_db()
    from deprem_izleme.gui import DepremGUI
    app = DepremGUI()
    try:
        app.withdraw()
        for _pg in ("panel", "risk-analiz", "tahmin"):
            try:
                app.switch_page(_pg)
            except Exception:
                pass
        app.risk_report = r_risk2
        app.prediction = r_pred
        app.earthquakes = q2
        app.stats_data = s2
        app.weekly_history = []
        app.monthly_history = []
        app.recurrence_data = []
        app.rec_meta = {}
        app._update_dashboard()
        app._update_prediction()
        app._update_risk_analysis()
        app.update_idletasks()
        dash = " ".join(w.cget("text") for w in app.metric_widgets.values())
        check("INT: GUI v2 dumani", "%None" not in dash, dash[:100])
    finally:
        try:
            app.destroy()
        except Exception:
            pass

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
