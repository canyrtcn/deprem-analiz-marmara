"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""Faz A test-2 (commitlenmez, scratch): format + alert + GUI None-render."""
import os
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
import sys
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

INSUF_R = {
    "region": "marmara", "composite_risk_score": 0.05, "risk_level": "DÜŞÜK",
    "no_data": False, "quake_count": 9,
    "gutenberg_richter": {"b_value": 1.0, "b_std": 0.3, "a_value": 3.0,
        "magnitude_completeness": 1.2,
        "b_anomaly": 0.0, "expected_max_magnitude": None,
        "observed_max_magnitude": 2.8},
    "poisson": {"lambda_m3_per_day": 0.1, "lambda_m4_per_day": 0.0,
        "p_m4_7days_pct": None, "p_m4_30days_pct": None},
    "energy": {"total_energy_joules": 1e8, "total_energy_tnt_tons": 0.02},
}
INSUF_P = {"prediction_window_days": 7, "min_magnitude_of_interest": 4.0,
    "no_data": False, "sufficient": False, "composite_index": None,
    "poisson_probability": None, "expected_quake_count": None,
    "max_likely_magnitude": None, "trend": "stable", "warning_level": None,
    "b_trend": 0.0, "energy_ratio": 1.0, "anomaly_z_score": 0.0,
    "foreshock_ratio": 0.0,
    "components": {"poisson": None, "b_trend_score": 0.0,
        "energy_score": 0.0, "z_score": 0.0, "foreshock_score": 0.0}}

# 1. Telegram formati yetersiz veride cokmuyor, sayi uretmiyor
from deprem_izleme.notifier import format_risk_alert, check_and_alert
try:
    msg = format_risk_alert(INSUF_R, INSUF_P)
    bad = [t for t in ["%None", "None%", "MNone"] if t in msg]
    check("notifier format cokmedi", True)
    check("notifier sayi uretmedi", not bad and "yetersiz veri" in msg, bad)
    check("notifier kalibre etiketi", "kalibre edilmemis" in msg)
except Exception as e:
    check("notifier format cokmedi", False, repr(e))

# 2. check_and_alert: warning None -> alarm yok, hata yok
try:
    res = check_and_alert(INSUF_R, INSUF_P)
    check("alert None-uyarida sessiz", res is False, res)
except Exception as e:
    check("alert None-uyarida sessiz", False, repr(e))

# 3. AI prompt + yorum yetersiz veride cokmuyor
from deprem_izleme.analysis import (build_analysis_prompt, interpret_now,
    get_recurrence_report)
try:
    pr = build_analysis_prompt(INSUF_R, INSUF_P, {"error": "Yetersiz veri (n=9<10)"})
    check("AI prompt cokmedi", "yetersiz veri" in pr)
    check("AI prompt olasilik uretmedi", "%None" not in pr and "nan" not in pr.lower())
    il = interpret_now(INSUF_R, INSUF_P)
    check("interpret cokmedi", any("hesaplanamad" in x for x in il), il)
except Exception as e:
    check("AI/interpret cokmedi", False, repr(e))

# 4. tekrarlama kapisi
try:
    rec9 = get_recurrence_report([2.0]*9, 1.0, 3.0)
    rec15 = get_recurrence_report([1.5 + (i % 20)/10.0 for i in range(15)], 1.0, 3.0)
    check("recurrence n=9 kapali", isinstance(rec9, dict) and "error" in rec9, rec9)
    check("recurrence n=15 acik", isinstance(rec15, list) and len(rec15) == 11)
except Exception as e:
    check("recurrence kapisi", False, repr(e))

# 6. madde-1: yetersizlik yesil/DUSUK olarak YANSIMIYOR
try:
    from deprem_izleme.aggregation import report_sufficient
    check("gating: rapor yetersiz", report_sufficient(INSUF_R) is False)
    check("gating: bilinmeyen rapor yetersiz sayilir",
          report_sufficient({}) is False and report_sufficient(None) is False)
    check("interpret risk belirtmiyor",
          any("risk düzeyi belirtilmiyor" in x for x in il)
          and not any("DÜŞÜK" in x for x in il))
    check("notifier yesil yansitmiyor",
          "✅" not in msg and "🟢" not in msg and "⚪" in msg
          and "DÜŞÜK" not in msg)
    check("prompt risk skoru kapali", "Risk Skoru: — (yetersiz veri)" in pr)
except Exception as e:
    check("gating kontrolleri", False, repr(e))
try:
    from unittest import mock as _mockG
    import deprem_izleme.db as _DBG
    import deprem_izleme.fetcher as _FG
    _GSYN = os.path.join(TESTTMP, "fa_syn7.db")
    _GW = os.path.join(TESTTMP, "fa_syn7_w.db")
    _GM = os.path.join(TESTTMP, "fa_syn7_m.db")
    with _mockG.patch.object(_DBG, "MAIN_DB", _GSYN), \
         _mockG.patch.object(_DBG, "WEEKLY_DB", _GW), \
         _mockG.patch.object(_DBG, "MONTHLY_DB", _GM), \
         _mockG.patch.object(_FG, "fetch_earthquakes", return_value=[]):
        from deprem_izleme import fetcher_koeri as _FKG
        with _mockG.patch.object(_FKG, "fetch_koeri", return_value={"quakes": [], "ok": True, "error": None}):
            from deprem_izleme.gui import DepremGUI
            app = DepremGUI()
            app.withdraw()
            for _pg in ("tahmin", "risk-analiz", "tekrarlama", "panel"):
                try:
                    app.switch_page(_pg)
                except Exception:
                    pass
            app.risk_report = INSUF_R
            app.prediction = INSUF_P
            app.earthquakes = []
            app.stats_data = {"son_24h": 0}
            app.weekly_history = []
            app.monthly_history = []
            app.recurrence_data = {"error": "Yetersiz veri (n=9<10)"}
            app.rec_meta = {"t_obs": 30.0, "n": 9, "mc": 1.2}
            app._update_prediction()
            app._update_risk_analysis()
            app._update_recurrence()
            app._update_dashboard()
            app.update_idletasks()
            dash = (" ".join(w.cget("text") for w in app.metric_widgets.values())
                    + " " + " ".join(w.cget("text") for w in app.status_widgets.values()))
            pred = " ".join(l.cget("text") for l in app.pred_labels.values())
            check("GUI None-render cokmedi", True)
            check("GUI yuzde uretmedi", "%None" not in dash and "%None" not in pred)
            check("GUI '—' gosteriyor", "—" in dash and "—" in pred, pred[:120])
            check("GUI gosterge yesil degil",
                  "—" in app.risk_gauge_label.cget("text")
                  and app.risk_gauge_level.cget("text") == "—"
                  and "DÜŞÜK" not in app.sidebar_risk_label.cget("text"),
                  app.risk_gauge_label.cget("text"))
            try:
                app.destroy()
            except Exception:
                pass
except Exception as e:
    check("GUI None-render cokmedi", False, repr(e))

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
