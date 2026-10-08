"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""Faz A test-3 (commitlenmez, scratch):
   madde 2: sayisal rapor==tahmin esitligi (M4 + M5), monkeypatch DB.
   madde 3: %8.03 GR sayisinin anatomisi + yeni kapida None. """
import os
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
import sys
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
import sys, time
sys.path.insert(0, REPO_ROOT)
import deprem_izleme.aggregation as AGG
import deprem_izleme.predictor as PRD
from deprem_izleme.aggregation import (
    forecast_poisson, calculate_b_value, catalog_sufficiency)
from deprem_izleme.predictor import EarthquakePredictor

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

NOW = time.time()
def synth(n, seed_mag, span_days=30.0):
    out = []
    for i in range(n):
        f = i / max(n - 1, 1)
        ts = NOW - (span_days - f * span_days) * 86400 - 3600
        out.append({"magnitude": seed_mag(i), "timestamp": ts,
                    "occurred_at": ts, "latitude": 40.7, "longitude": 28.5,
                    "location": "Test", "depth": 10.0, "source": "test"})
    return out

# --- madde 3: eski %8.03 vakasi (n=15, hepsi M<4, tamlik OL CULEMEMIS) ---
old = synth(15, lambda i: 1.2 + (i % 20) / 10.0)
b, a, mc = calculate_b_value([e["magnitude"] for e in old])
suf = catalog_sufficiency(old)
f = forecast_poisson(old, threshold=4.0)
print(f"   [madde3] n=15: b={b:.3f} a={a:.3f} Mc_yedek={suf['mc']:.2f} "
      f"mc_est={suf['mc_estimated']} mc_val={suf['mc_validated']} gozlenen_max={max(e['magnitude'] for e in old):.1f}")
print(f"   [madde3] lambda_gr={f['lambda_gr']} P7={f['p_7days']} kaynak={f['rate_source']}")
check("madde3: tamlik olculeMemis katalogda GR sayi YOK",
      f["lambda_gr"] is None and f["p_7days"] is None,
      "eski %8.03 artik uretilmiyor")

# --- madde 2: yeterli katalog (n=25, 2 gozlenen M>=4) ---
SYN = synth(25, lambda i: (4.2 if i in (7, 18) else 1.0 + (i % 18) / 10.0))
AGG.get_earthquakes = lambda **kw: list(SYN)
PRD.get_earthquakes = lambda **kw: list(SYN)

import unittest.mock as _mm3
_sig3 = _mm3.patch.object(AGG, "_catalog_signature", return_value=(777, 888))
_sig3.start()
r = AGG.get_comprehensive_risk_report(region="marmara")
p4 = EarthquakePredictor(region="marmara").predict_short_term(
    days_ahead=7, min_mag_of_interest=4.0)
p5 = EarthquakePredictor(region="marmara").predict_short_term(
    days_ahead=7, min_mag_of_interest=5.0)
f5 = forecast_poisson(SYN, threshold=5.0, forecast_days=7.0)

print(f"   [madde2] n=25: yeterli={r['poisson']['sufficient']} "
      f"kaynak={r['poisson']['rate_source']} "
      f"Mc={r['poisson']['sufficiency']['mc']:.2f} "
      f"mc_val={r['poisson']['sufficiency']['mc_validated']}")
rp7 = r["poisson"]["p_m4_7days_pct"]
pp4 = p4["poisson_probability"]
check("madde2: sayisal P uretildi (M4)", rp7 is not None and pp4 is not None,
      f"rapor=%{rp7} tahmin=%{pp4*100:.4f}")
check("madde2: rapor==tahmin M4 (birebir)",
      rp7 is not None and pp4 is not None and abs(rp7 - pp4 * 100) < 1e-9,
      f"fark={abs(rp7 - pp4*100) if (rp7 is not None and pp4 is not None) else 'NA'}")
pp5 = p5["poisson_probability"]
fp5 = f5["p_forecast"]
check("madde2: sayisal P uretildi (M5)", pp5 is not None and fp5 is not None,
      f"tahmin=%{pp5*100:.4f} servis=%{fp5*100:.4f}")
# tahmin 4-ondalik yuvarlanmis sunum degeridir; ayni hesap + ayni yuvarlama
check("madde2: tahmin==servis M5 (birebir)",
      pp5 is not None and fp5 is not None and pp5 == round(fp5, 4))
check("madde2: M5 olasiligi < M4 olasiligi", pp5 < pp4, f"M4=%{pp4*100:.2f} M5=%{pp5*100:.2f}")

# tutarlilik: ayni girdide rapor b-degeri == servis b-degeri
# (rapor 4-ondalik yuvarlanmis sunum degeridir)
check("madde2: b tutarli",
      abs(r["gutenberg_richter"]["b_value"] - f5["b_value"]) < 1e-4,
      f"rapor={r['gutenberg_richter']['b_value']} servis={f5['b_value']:.6f}")

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
