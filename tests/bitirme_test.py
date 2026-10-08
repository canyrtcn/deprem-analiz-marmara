"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""Bitirme turu testleri (scratch-only, sentetik). 9 madde."""
import inspect
import os
import sqlite3
import sys
import time
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
os.environ.setdefault("DEPREM_API_KEY", "test-key-bitirme")
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

from unittest import mock
import deprem_izleme.aggregation as A
import deprem_izleme.notifier as N
import deprem_izleme.fetcher_koeri as FK
import deprem_izleme.fetcher as F
import deprem_izleme.updater as U

NOW = time.time()
def ev(mag, days_ago, **kw):
    d = {"magnitude": mag, "timestamp": NOW - days_ago * 86400,
         "depth": 10.0, "occurred_at": "2026-09-01 00:00:00"}
    d.update(kw)
    return d

# 1. SCI-16
m3only = [ev(3.0 + (i % 9) * 0.1, (i % 28) + 1) for i in range(40)]
m4rich = list(m3only) + [ev(4.5, 2), ev(4.8, 5), ev(4.2, 9)]
s_m3 = A._compute_risk_score(m3only, 1.0, 5.0, 1e9)
s_m4 = A._compute_risk_score(m4rich, 1.0, 5.0, 1e9)
s_1 = A._compute_risk_score([ev(1.0, 1)], 1.0, 5.0, 1e6)
check("SCI16: M3-only/M4/tek hepsi hesaplanir", all(isinstance(x, float) for x in (s_m3, s_m4, s_1)),
      f"{s_m3:.3f}/{s_m4:.3f}/{s_1:.3f}")
check("SCI16: M4 aktivite skoru yukseltir", s_m4 > s_m3, f"{s_m4:.3f}>{s_m3:.3f}")
src = inspect.getsource(A._compute_risk_score)
check("SCI16: tek servis kullanilir (M3-ham lambda yok)",
      "forecast_poisson" in src and "estimate_lambda(quakes, min_mag=3.0)" not in src)

# 2. BUG-09
check("BUG09: config yoksa send False", N.send_telegram_message("x") is False)
rep = {"composite_risk_score": 0.99, "risk_level": "YÜKSEK",
       "region": "marmara",
       "gutenberg_richter": {"b_value": 1.0, "expected_max_magnitude": 5.0,
                             "observed_max_magnitude": 4.0},
       "poisson": {"p_m4_7days_pct": 5.0, "p_m4_30days_pct": 20.0},
       "energy": {"total_energy_joules": 1e9, "total_energy_tnt_tons": 1.0}}
pred = {"warning_level": "red", "poisson_probability": 0.1, "composite_index": 0.8,
        "b_trend": 0.0, "anomaly_z_score": 0.0, "trend": "stable",
        "prediction_window_days": 7, "min_magnitude_of_interest": 4.0,
        "max_likely_magnitude": 5.0}
with mock.patch.object(N, "_notif_settings",
                       return_value={"telegram_enabled": True, "telegram_threshold": 0.0,
                                     "telegram_levels": ["red"], "telegram_cooldown_h": 0}):
    r = N.check_and_alert(rep, pred)
    st = N.check_and_alert.last_status
check("BUG09: gonderim basarisiz -> False + send_failed", r is False and st == "send_failed", st)
rep_lo = dict(rep, composite_risk_score=0.01)
pred_lo = dict(pred, warning_level="green")
with mock.patch.object(N, "_notif_settings",
                       return_value={"telegram_enabled": True, "telegram_threshold": 0.7,
                                     "telegram_levels": ["red"], "telegram_cooldown_h": 0}):
    r2 = N.check_and_alert(rep_lo, pred_lo)
    st2 = N.check_and_alert.last_status
check("BUG09: esik-alti -> not_needed (ayri durum)", r2 is False and st2 == "not_needed", st2)

# 3. BUG-08
m1 = N.format_risk_alert(rep, pred)
m2 = N.format_daily_summary({"quake_count": 5, "max_mag": 3.0, "avg_mag": 2.0, "risk_score": 0.1}, 2)
check("BUG08: sablonlarda legacy **/_ yok",
      "**" not in m1 and "**" not in m2 and "_Deprem" not in m1 and "_Deprem" not in m2)
check("BUG08: HTML etiketleri var", "<b>" in m1 and "<b>" in m2)
check("BUG08: escape HTML", N._escape_md("<b>&") == "&lt;b&gt;&amp;", N._escape_md("<b>&"))
check("BUG08: varsayilan parse_mode HTML",
      inspect.signature(N.send_telegram_message).parameters["parse_mode"].default == "HTML")

# 4. BUG-07
with mock.patch.object(FK.requests, "get", side_effect=RuntimeError("ag yok")):
    res = FK.fetch_koeri()
check("BUG07: ag hatasi -> ok=False, bos degil", res["ok"] is False and res["error"], str(res)[:60])
html = ("2026.01.01 00:00:00  40.7000   28.5000        5.0      -.-  3.5  -.-   MARMARA DENIZI\n"
        "2026.01.01 00:00:00  60.0000   60.0000        5.0      -.-  3.5  -.-   UZAK BOLGE\n")
class _R:
    content = html.encode("utf-8")
    def raise_for_status(self): pass
with mock.patch.object(FK.requests, "get", return_value=_R()):
    res2 = FK.fetch_koeri()
check("BUG07: parse -> dict + bbox disi elenir",
      res2["ok"] is True and len(res2["quakes"]) == 1, len(res2.get("quakes", [])))

# 5. SCI-08
old_main = [ev(5.0, 2)]
check("SCI08: M5.0 (tursuz) -> None", A.omori_forecast(old_main) is None)
mw_main = [ev(6.2, 2, magnitude_mw=6.2, mag_type="Mw")]
r8 = A.omori_forecast(mw_main)
check("SCI08: Mw6.2 -> hesap uretilir", r8 is not None and r8["mainshock_mag"] == 6.2,
      (r8 or {}).get("mainshock_mag"))
legacy_main = [ev(6.5, 2)]
check("SCI08: legacy satir (tur yok) -> None", A.omori_forecast(legacy_main) is None)

# 6. BUG-03
raw = [{"latitude": 60.0 + i * 0.001, "longitude": 60.0, "magnitude": 1.0 + (i % 5) * 0.1,
        "timestamp": 1, "occurred_at": "2026-01-01 00:00:00", "source": "t",
        "event_id": f"e{i}"} for i in range(1000)]
class _R2:
    def raise_for_status(self): pass
    def json(self): return {"status": "success", "earthquakes": raw}
    is_redirect = False
    status_code = 200
SYN = _os.path.join(TESTTMP, "bitirme_v1.db")
for s in ("", "-wal", "-shm", "-journal"):
    if os.path.exists(SYN + s):
        os.remove(SYN + s)
with mock.patch.object(F, "build_api_request", return_value={"url": "https://x", "params": {}, "headers": {}}), \
     mock.patch.object(F.requests, "get", return_value=_R2()):
    F.fetch_and_store(days_back=7, min_magnitude=0.0, db_path=SYN)
check("BUG03: ham 1000 + filtre 0 -> truncated True",
      F.fetch_and_store.truncated is True, F.fetch_and_store.truncated)
with mock.patch.object(F, "build_api_request", return_value={"url": "https://x", "params": {}, "headers": {}}), \
     mock.patch.object(F.requests, "get", return_value=_R2()):
    F.fetch_earthquakes(7, 0.0)
check("BUG03: ham sayi kayitli", F.fetch_earthquakes.last_raw_count == 1000,
      F.fetch_earthquakes.last_raw_count)

# 7. DOC-02/03
rd = open(_os.path.join(REPO_ROOT, "README.md"), encoding="utf-8").read()
check("DOC: guncelleme kapali ifadesi",
      "otomatik güncelleme" in rd and "devre dışı" in rd)
check("DOC: denetim yalnizca bilgi", "bilgi vermek içindir" in rd)
check("DOC: gizli-depo denetim notu", "Denetlenemedi" in rd)
check("DOC: eski otomatik-kurma iddiasi yok", "değiştirir ve yeniden başlar" not in rd)

# 8. SEC-03/04
check("SEC: UPDATER_ENABLED False", U.UPDATER_ENABLED is False)
with mock.patch.object(U, "download_package", side_effect=AssertionError("ag cagrisi YASAK")):
    ok8, msg8 = U.download_and_apply({"url": "https://x/y.zip"}, on_quit=lambda: None)
check("SEC: download_and_apply ag'a cikmadan red", ok8 is False and "kapal" in msg8, msg8[:40])

# 9. SCI-09
gsrc = open(_os.path.join(REPO_ROOT, "deprem_izleme/gui.py"), encoding="utf-8").read()
check("SCI09: Coulomb sinir etiketi", "GERÇEK BİR ΔCFF ÇÖZÜMÜ DEĞİLDİR" in gsrc)
check("SCI09: tetikleme iddiasi kaldirildi", "bu uygulama tetikleme hesabı yapmaz" in gsrc)

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
