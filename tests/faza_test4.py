"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""Faz A test-4 (commitlenmez, scratch):
   Mc tahmin != Mc dogrulama. n=20/n=25 (max<M4, GR-uyumsuz) -> baslikta
   sayi YOK; n=40 (GR-uyumlu) -> sayisal P; tani satiri AI prompt'ta. """
import os
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
import sys
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
import sys, time, random
sys.path.insert(0, REPO_ROOT)
import deprem_izleme.aggregation as AGG
import deprem_izleme.predictor as PRD
from deprem_izleme.aggregation import forecast_poisson
from deprem_izleme.analysis import build_analysis_prompt

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

NOW = time.time()
def mk(n, fn, span=30.0):
    return [{"magnitude": fn(i),
             "timestamp": NOW - ((span - (i / max(n - 1, 1)) * span) * 86400) - 3600,
             "occurred_at": 0, "latitude": 40.7, "longitude": 28.5,
             "location": "Test", "depth": 10.0, "source": "test"}
            for i in range(n)]

random.seed(7)
Q20 = mk(20, lambda i: round(1.1 + (i % 14) / 10.0, 1) if i < 14
       else round(2.4 + ((i - 14) % 6) / 10.0, 1))
Q25 = mk(25, lambda i: round(1.0 + (i % 16) / 10.0, 1) if i < 16
       else round(2.5 + ((i - 16) % 9) / 10.0, 1))
Q40 = mk(40, lambda i: round(1.0 + random.expovariate(2.0), 1))

for name, q in [("n=20", Q20), ("n=25", Q25)]:
    f = forecast_poisson(q, threshold=4.0)
    v = f["sufficiency"]["validation"]
    print(f"   [{name}] max={max(e['magnitude'] for e in q)} "
          f"est={f['sufficiency']['mc_estimated']} "
          f"GFT-R={v.get('gft_R')} ({v.get('reason')})")
    check(f"{name}: Mc tahmin edildi", f["sufficiency"]["mc_estimated"] is True)
    check(f"{name}: Mc DOGRULANMADI", f["sufficiency"]["mc_validated"] is False)
    check(f"{name}: baslik olasiligi YOK",
          f["p_7days"] is None and f["rate_source"] == "yok")
    check(f"{name}: GR yalnizca varsayimsal tani",
          f["lambda_gr"] is not None and f["gr_validated"] is False,
          f"lam_gr={f['lambda_gr']:.2e}")

# AI prompt: varsayimsal tani satiri var, baslik sayisi yok
AGG.get_earthquakes = lambda **kw: list(Q25)
PRD.get_earthquakes = lambda **kw: list(Q25)
import unittest.mock as _mm4
_sig4 = _mm4.patch.object(AGG, "_catalog_signature", return_value=(444, 555))
_sig4.start()
AGG._report_cache.clear()
r = AGG.get_comprehensive_risk_report(region="marmara")
p = PRD.EarthquakePredictor(region="marmara").predict_short_term()
pr = build_analysis_prompt(r, p, {"error": "x"})
check("prompt: baslik P yok", "hesaplanamadı" in pr or "yetersiz veri" in pr)
check("prompt: VARSAYIMSAL tani satiri var",
      "VARSAYIMSAL" in pr and "başlıkta kullanılmadı" in pr,
      [x for x in pr.splitlines() if "VARSAYIMSAL" in x])
check("prompt: tani basliga karismamis",
      r["poisson"]["p_m4_7days_pct"] is None)

# pozitif kontrol: GR-uyumlu n=40 -> sayisal P, gr-model, etiketli
AGG.get_earthquakes = lambda **kw: list(Q40)
PRD.get_earthquakes = lambda **kw: list(Q40)
AGG._report_cache.clear()
r40 = AGG.get_comprehensive_risk_report(region="marmara")
p40 = PRD.EarthquakePredictor(region="marmara").predict_short_term()
v40 = r40["poisson"]["sufficiency"]["validation"]
check("n=40: Mc dogrulandi", r40["poisson"]["sufficiency"]["mc_validated"] is True, v40)
check("n=40: sayisal P uretildi",
      r40["poisson"]["p_m4_7days_pct"] is not None
      and r40["poisson"]["rate_source"] == "gr-model",
      f"P7=%{r40['poisson']['p_m4_7days_pct']}")
check("n=40: rapor==tahmin",
      abs(r40["poisson"]["p_m4_7days_pct"] - p40["poisson_probability"] * 100) < 1e-9)

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
