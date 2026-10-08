"""
Deprem tekrarlama aralıkları ve yapay zeka analizi
"""
import logging
import math
from datetime import datetime, timedelta

from deprem_izleme.db import get_earthquakes
from deprem_izleme.aggregation import calculate_b_value, seismic_energy_joules

logger = logging.getLogger(__name__)


# =====================================================================
# TEKRARLAMA ARALIĞI (Gutenberg-Richter bazlı)
# =====================================================================

def recurrence_interval(magnitude, b_value, a_value, t_obs_days=30.0):
    """
    Gutenberg-Richter: log10(N) = a - b*M
    N = 10^(a - b*M)  -> gözlenen katalog penceresindeki beklenen olay sayısı

    Tekrarlama aralığı: T(M) = T_obs / N  (gün)
    T_obs = kataloğun zaman genişliği. Normalizasyonsuz (1/N) hesap
    gün biriminde YANLIŞTIR; oran pencereye bölünmelidir.
    """
    if b_value <= 0 or t_obs_days <= 0:
        return float('inf')
    n = 10 ** (a_value - b_value * magnitude)
    if n <= 0:
        return float('inf')
    return t_obs_days / n


def recurrence_years(magnitude, b_value, a_value, t_obs_days=30.0):
    """Tekrarlama aralığını yıl cinsinden ver."""
    days = recurrence_interval(magnitude, b_value, a_value, t_obs_days)
    if days == float('inf'):
        return float('inf')
    return days / 365.25


def catalog_span_days(earthquakes):
    """Katalog zaman genişliği (gün)."""
    ts = [e["timestamp"] for e in (earthquakes or []) if e.get("timestamp")]
    if len(ts) < 2:
        return 30.0
    return max((max(ts) - min(ts)) / 86400, 1.0)


def get_recurrence_report(magnitudes, b_value, a_value, region="marmara",
                          t_obs_days=30.0, quake_count=None):
    """
    Farklı magnitüdler için tekrarlama aralıkları raporu.
    t_obs_days: oranın dayandığı katalog penceresi (gün).
    """
    if not magnitudes or b_value <= 0:
        return {"error": "Yetersiz veri"}

    levels = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0]
    report = []
    for m in levels:
        days = recurrence_interval(m, b_value, a_value, t_obs_days)
        years = days / 365.25
        if days == float('inf'):
            report.append({"magnitude": m, "days": None, "years": None, "text": ">1000 yıl"})
        elif days < 1:
            report.append({"magnitude": m, "days": round(days, 2), "years": round(years, 4),
                           "text": f"~{days:.1f} gün"})
        elif years < 1:
            report.append({"magnitude": m, "days": round(days, 1), "years": round(years, 3),
                           "text": f"~{days:.0f} gün"})
        elif years < 100:
            report.append({"magnitude": m, "days": round(days, 0), "years": round(years, 1),
                           "text": f"~{years:.1f} yıl"})
        else:
            report.append({"magnitude": m, "days": round(days, 0), "years": round(years, 0),
                           "text": f"~{years:.0f} yıl"})

    return report


# =====================================================================
# TANIMLAYICI DAĞILIMLAR (sismikharita.com/istatistik tarzı)
# =====================================================================

def hourly_distribution(earthquakes):
    """24 saat dilimine göre deprem sayıları (yerel saat)."""
    hours = [0] * 24
    for e in (earthquakes or []):
        ts = e.get("timestamp")
        if not ts:
            continue
        try:
            hours[datetime.fromtimestamp(ts).hour] += 1
        except Exception:
            pass
    return hours


def monthly_distribution(earthquakes):
    """Aylara göre deprem sayıları (1-12)."""
    months = [0] * 12
    for e in (earthquakes or []):
        ts = e.get("timestamp")
        if not ts:
            continue
        try:
            months[datetime.fromtimestamp(ts).month - 1] += 1
        except Exception:
            pass
    return months


def depth_distribution(earthquakes):
    """Derinlik dilimleri: [aralık, adet, yüzde]."""
    edges = [0, 5, 10, 15, 20, 30, 50, 100, float("inf")]
    labels = ["0-5", "5-10", "10-15", "15-20", "20-30", "30-50", "50-100", "100+"]
    depths = [e["depth_km"] for e in (earthquakes or [])
              if e.get("depth_km") is not None]
    total = len(depths) or 1
    out = []
    for i, lab in enumerate(labels):
        n = sum(1 for d in depths if edges[i] <= d < edges[i + 1])
        out.append({"range": lab, "count": n, "pct": round(n / total * 100, 1)})
    shallow = sum(1 for d in depths if d < 20)
    return {"bins": out, "shallow_pct": round(shallow / total * 100, 1), "n": len(depths)}


def magnitude_time(earthquakes, limit=500):
    """Büyüklük-zaman serisi: [(timestamp, magnitude)]."""
    pts = [(e["timestamp"], e["magnitude"]) for e in (earthquakes or [])
           if e.get("timestamp") and e.get("magnitude")]
    pts.sort()
    return pts[-limit:]


def baseline_status(weekly_history):
    """Son hafta sayısını önceki 8 haftayla karşılaştır.

    Döner: {last, median, low, high, state} — state:
    yuksek / normal / dusuk / veri-yok.
    """
    import statistics as _st
    counts = [s["quake_count"] for s in (weekly_history or []) if s.get("quake_count") is not None]
    if len(counts) < 3:
        return {"last": counts[0] if counts else 0, "median": 0,
                "low": 0, "high": 0, "state": "veri-yok"}
    last = counts[0]
    base = counts[1:9]
    med = _st.median(base)
    try:
        q = _st.quantiles(sorted(base), n=4)
        low, high = q[0], q[2]
    except Exception:
        low = high = med
    if last > max(high, med * 1.5):
        state = "yuksek"
    elif last < min(low, med * 0.5):
        state = "dusuk"
    else:
        state = "normal"
    return {"last": last, "median": round(med, 1), "low": round(low, 1),
            "high": round(high, 1), "state": state}


def interpret_now(risk_report, prediction):
    """Sade dille 3 cümlelik durum özeti ('Şu an ne diyor?')."""
    lines = []
    n = risk_report.get("quake_count", 0)
    lines.append(f"Son 30 günde bölgede {n} deprem kaydedildi.")
    lvl = risk_report.get("risk_level", "?")
    if risk_report.get("no_data"):
        lines.append("Veri az olduğu için sayılar gösterge niteliğinde; önce veri çekin.")
    elif lvl in ("YÜKSEK", "ÇOK YÜKSEK"):
        lines.append(f"Birleşik risk {lvl} düzeyde — hareketlilik olağanın üzerinde.")
    elif lvl == "ORTA":
        lines.append("Birleşik risk ORTA düzeyde — olağan dışı bir tablo yok.")
    else:
        lines.append(f"Birleşik risk {lvl} düzeyde — sismik tablo sakin.")
    b = risk_report["gutenberg_richter"]["b_value"]
    if b < 0.8:
        lines.append("b-değeri düşük; bölgede gerilim birikimi olabilir.")
    elif b > 1.2:
        lines.append("b-değeri yüksek; gerilim görece düşük görünüyor.")
    else:
        lines.append("b-değeri normal aralıkta (~1.0).")
    p7 = risk_report["poisson"]["p_m4_7days_pct"]
    if risk_report["poisson"].get("p_m4_gr_tahmini"):
        lines.append(f"Önümüzdeki 7 günde M≥4.0 olasılığı %{p7:.1f} (GR modelinden; gözlenen M≥4 yok).")
    else:
        lines.append(f"Önümüzdeki 7 günde M≥4.0 olasılığı %{p7:.1f} (istatistiksel tahmin).")
    return lines


# =====================================================================
# YAPAY ZEKA ANALİZİ - Veriyi yorumlanabilir metne dönüştürür
# =====================================================================

def build_analysis_prompt(risk_report, prediction, recurrence_data):
    """
    AI modeline verilecek yapılandırılmış analiz metnini oluşturur.
    Bu metin daha sonra bir yapay zeka modeline verilerek
    doğal dil yorumu alınabilir.
    """
    r = risk_report
    p = prediction

    lines = [
        "=== DEPREM ANALİZ - MARMARA - ANALİZ RAPORU ===",
        f"Bölge: {r['region'].title()}",
        f"Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        "",
    ]

    if r.get("no_data"):
        lines += [
            "UYARI: Son 30 günde yeterli veri yok (<5 deprem).",
            "Aşağıdaki sayılar varsayılan değerlerdir, yoruma esas almayın.",
            "Önce 'Verileri Çek & Güncelle' ile veri çekin.",
            "",
        ]

    lines += [
        "--- BİLEŞİK RİSK ---",
        f"Risk Skoru: {r['composite_risk_score']:.4f} ({r['risk_level']})",
        f"Tahmin Uyarı Seviyesi: { {'red': 'KIRMIZI', 'orange': 'TURUNCU', 'yellow': 'SARI', 'green': 'YEŞİL'}.get(p.get('warning_level', 'green'), p.get('warning_level', '?')) }",
        f"7 günlük M≥4.0 olasılığı: %{p.get('probability', 0)*100:.1f}",
        "",
        "--- GUTENBERG-RICHTER PARAMETRELERİ ---",
        f"b-değeri: {r['gutenberg_richter']['b_value']:.4f}",
        f"a-değeri: {r['gutenberg_richter']['a_value']:.4f}",
        f"b anomali: {r['gutenberg_richter']['b_anomaly']:+.4f}",
        f"Beklenen Mmax: M{r['gutenberg_richter']['expected_max_magnitude']:.1f}",
        f"Gözlenen Mmax: M{r['gutenberg_richter']['observed_max_magnitude']:.1f}",
        "",
        "--- TEKRARLAMA ARALIKLARI ---",
    ]

    if isinstance(recurrence_data, dict):
        # Yetersiz veri durumu: {"error": ...}
        lines.append(f"  Hesaplanamadı: {recurrence_data.get('error', 'yetersiz veri')}")
    else:
        for item in recurrence_data:
            m = item['magnitude']
            mtxt = ('%g' % m)
            lines.append(f"  M≥{mtxt}: {item['text']}")

    lines.extend([
        "",
        "--- POISSON OLASILIKLARI ---",
        f"λ(M≥3.0): {r['poisson']['lambda_m3_per_day']:.4f} /gün",
        f"λ(M≥4.0): {r['poisson']['lambda_m4_per_day']:.4f} /gün",
        f"P(M≥4.0) 7 gün: %{r['poisson']['p_m4_7days_pct']:.1f}",
        f"P(M≥4.0) 30 gün: %{r['poisson']['p_m4_30days_pct']:.1f}",
        "",
        "--- ENERJİ ---",
        f"Toplam sismik enerji: {r['energy']['total_energy_joules']:.2e} J",
        f"TNT eşdeğeri: {r['energy']['total_energy_tnt_tons']:.1f} ton",
        "",
        "--- TREND ---",
        f"b-trendi: {p.get('b_trend', 0):+.4f}",
        f"Aktivite Z-Skor: {p.get('anomaly_z_score', 0):.2f}",
        f"Trend yönü: { {'increasing': 'ARTIYOR', 'stable': 'STABİL', 'decreasing': 'AZALIYOR'}.get(p.get('trend', 'stable'), p.get('trend', '?')) }",
        f"Enerji oranı: {p.get('energy_ratio', 1.0):.2f}x",
        "",
        "--- TAHMIN BİLEŞENLERİ ---",
    ])

    for comp_name, comp_val in p.get('components', {}).items():
        lines.append(f"  {comp_name}: %{comp_val*100:.1f}")

    lines.extend([
        "",
        "=== YORUM TALEBİ ===",
        "Yukarıdaki verilere dayanarak:",
        "1. Bölgedeki genel sismik durumu değerlendir.",
        "2. b-değeri anomalisini yorumla (düşük b = yüksek stress).",
        "3. Poisson olasılıklarının anlamı nedir?",
        "4. Trend yönü ne ifade ediyor?",
        "5. Kısa vadede (7-30 gün) ne beklenmeli?",
        "6. Uzun vadede (1-5 yıl) bu bölge için risk durumu nedir?",
        "7. Marmara Denizi için özel bir değerlendirme yap.",
    ])
    return "\n".join(lines)


def save_analysis_report(risk_report, prediction, recurrence_data, filepath=None):
    """Analiz raporunu dosyaya kaydet."""
    text = build_analysis_prompt(risk_report, prediction, recurrence_data)
    if filepath:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(text)
    return text


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Test
    from deprem_izleme.aggregation import get_comprehensive_risk_report
    from deprem_izleme.predictor import EarthquakePredictor

    r = get_comprehensive_risk_report()
    p = EarthquakePredictor().predict_short_term()
    mags_data = [1.5, 2.0, 2.3, 1.8, 2.5, 3.0, 1.2, 1.9, 2.1]
    bv, av, _ = calculate_b_value(mags_data)
    rec = get_recurrence_report(mags_data, bv, av)
    text = build_analysis_prompt(r, p, rec)
    print(text[:500])
