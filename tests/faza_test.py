"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""Faz A rev.7 testleri (commitlenmez, scratch)."""
import os
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
import sys
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)
import time
from deprem_izleme.aggregation import (
    forecast_poisson, catalog_sufficiency, gr_rate,
    get_comprehensive_risk_report)
from deprem_izleme.predictor import EarthquakePredictor

NOW = time.time()
def mk(n, mags=None, span_days=30.0, start_ago=30.0):
    out = []
    for i in range(n):
        f = i / max(n - 1, 1)
        ts = NOW - (start_ago - f * span_days) * 86400
        m = mags[i] if mags else 1.0 + (i % 25) / 10.0
        out.append({"magnitude": m, "timestamp": ts})
    return out

ok = []
def check(name, cond, extra=""):
    ok.append(cond)
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

# 1. bos katalog
f = forecast_poisson([], threshold=4.0)
check("bos: P None", f["p_7days"] is None and f["p_30days"] is None)
check("bos: yetersiz", f["sufficient"] is False, f["sufficiency"]["reasons"])
check("bos: GR yok", f["lambda_gr"] is None)
check("bos: kaynak yok", f["rate_source"] == "yok")

# 2. n=5 yetersiz
f = forecast_poisson(mk(5))
check("n=5: P None", f["p_7days"] is None and f["sufficient"] is False)

# 3. n=9 yetersiz
f = forecast_poisson(mk(9))
check("n=9: P None", f["p_7days"] is None and f["sufficient"] is False)

# 4. n=15, hepsi M<4, yaygin 30g -> orneklem yeterli AMA tamlik olculeMemis
# (n<20, Mc yedek) -> GR disdegerleme YOK, P uretilmez (madde 3 karari)
mags = [1.2 + (i % 20) / 10.0 for i in range(15)]  # max ~3.1
f = forecast_poisson(mk(15, mags=mags), threshold=4.0)
check("n=15 sifir-M4: orneklem yeterli", f["sufficient"] is True, f["sufficiency"])
check("n=15 sifir-M4: tamlik olculeMemis", f["sufficiency"]["mc_estimated"] is False)
check("n=15 sifir-M4: GR sayi yok", f["lambda_gr"] is None and f["p_7days"] is None,
      f"kaynak={f['rate_source']}")

# 5. kume: n=15 ama 2 gunluk span -> yetersiz (sure kriteri)
f = forecast_poisson(mk(15, span_days=2.0, start_ago=2.0))
check("kume-2g: yetersiz", f["sufficient"] is False, f["sufficiency"]["reasons"])
check("kume-2g: P None", f["p_7days"] is None)

# 6. M>=5 esigi: GR genellestirme (lambda_M5 < lambda_M4)
q = mk(30, mags=[1.5 + (i % 30) / 10.0 for i in range(30)])
f4 = forecast_poisson(q, threshold=4.0)
f5 = forecast_poisson(q, threshold=5.0)
check("M5<M4 hiz", (f5["lambda_gr"] or 0) < (f4["lambda_gr"] or 0),
      f"M4={f4['lambda_gr']:.2e} M5={f5['lambda_gr']:.2e}")
check("gr_rate dogrudan", abs(gr_rate(3.0, 1.0, 5.0, 30.0) - 10**(3.0-5.0)/30.0) < 1e-12)

# 7. sentetik katalogda rapor == tahmin (ayni servis, ayni girdi)
# (canli DB okunmaz; 9 kayitli yetersiz-katalog senaryosu sentetik kurulur)
import sqlite3 as _sq3
_SYN7 = os.path.join(TESTTMP,
                     "fa_syn7.db")
for _suf in ("", "-wal", "-shm", "-journal"):
    if os.path.exists(_SYN7 + _suf):
        os.remove(_SYN7 + _suf)
_cc7 = _sq3.connect(_SYN7)
_cc7.execute("CREATE TABLE earthquakes (id INTEGER PRIMARY KEY, event_id TEXT UNIQUE, occurred_at TEXT NOT NULL, timestamp INTEGER NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL, depth_km REAL, magnitude REAL, magnitude_ml REAL, magnitude_mw REAL, magnitude_md REAL, location TEXT, source TEXT, region_tag TEXT, created_at TEXT DEFAULT (datetime('now')))")
for _i in range(9):
    _ts = int(NOW - (29 - _i * 3) * 86400)
    _cc7.execute("INSERT INTO earthquakes (id, event_id, occurred_at, timestamp, latitude, longitude, depth_km, magnitude, magnitude_ml, location, source, region_tag) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 (7000 + _i, "syn7_%d" % _i,
                  time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(_ts)), _ts,
                  40.7, 28.5, 8.0, 1.5 + (_i % 5) * 0.2, 1.5 + (_i % 5) * 0.2,
                  "YER", "kandilli", "marmara"))
_cc7.commit()
_cc7.close()
import deprem_izleme.db as _DB7
from unittest import mock as _mock7
_W7 = os.path.join(TESTTMP, "fa_syn7_w.db")
_M7 = os.path.join(TESTTMP, "fa_syn7_m.db")
for _f in (_W7, _M7):
    for _suf in ("", "-wal", "-shm", "-journal"):
        if os.path.exists(_f + _suf):
            os.remove(_f + _suf)
with _mock7.patch.object(_DB7, "MAIN_DB", _SYN7), \
     _mock7.patch.object(_DB7, "WEEKLY_DB", _W7), \
     _mock7.patch.object(_DB7, "MONTHLY_DB", _M7):
    _DB7.init_weekly_db()
    _DB7.init_monthly_db()
    r = get_comprehensive_risk_report(region="marmara")
    p = EarthquakePredictor(region="marmara").predict_short_term(days_ahead=7, min_mag_of_interest=4.0)
rp7, pp = r["poisson"]["p_m4_7days_pct"], p["poisson_probability"]
same = (rp7 is None and pp is None) or (rp7 is not None and pp is not None and abs(rp7 - pp*100) < 1e-9)
check("rapor==tahmin Poisson", same, f"rapor={rp7} tahmin={pp}")
print("   sentetik: n=", r["quake_count"], " yeterli=", r["poisson"]["sufficient"],
      " kaynak=", r["poisson"]["rate_source"], " Emax=", r["gutenberg_richter"]["expected_max_magnitude"])
print("   tahmin: yeterli=", p["sufficient"], " uyari=", p["warning_level"],
      " index=", p["composite_index"], " P=", p["poisson_probability"])

# 8. eksik-veri vs gercek-sifir ayrimi: bos -> yetersiz; 30 kayit sifir-M4
# (duzgun dagilmayan katalog) -> orneklem yeterli AMA Mc dogrulanmamis ->
# baslik P yok, yalnizca varsayimsal tani. Ayrim sufficient/gr_validated ile.
f_empty = forecast_poisson([])
f_zero = forecast_poisson(mk(30, mags=[1.0 + (i % 15) / 10.0 for i in range(30)]))
check("ayrim: bos yetersiz", f_empty["sufficient"] is False and f_empty["p_7days"] is None)
check("ayrim: 30 kayit sifir-M4 yeterli ama dogrulanmamis",
      f_zero["sufficient"] is True and f_zero["gr_validated"] is False
      and f_zero["p_7days"] is None and f_zero["lambda_gr"] is not None,
      f_zero["sufficiency"]["validation"].get("reason"))

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
