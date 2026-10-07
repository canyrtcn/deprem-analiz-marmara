"""
Haftalık ve aylık deprem istatistikleri + agregasyon
"""
import logging
import math
import statistics
from datetime import datetime, timedelta, date
from collections import Counter

from deprem_izleme.config import MAGNITUDE_OF_INTEREST
from deprem_izleme.db import (
    get_earthquakes, save_weekly_stats, save_monthly_stats,
    get_db, MAIN_DB
)

logger = logging.getLogger(__name__)


def _iso_week_key(dt):
    """(year, week) tuple döndür."""
    iso = dt.isocalendar()
    return (iso[0], iso[1])


def _week_bounds(year, week):
    """Haftanın başlangıç (Pazartesi) ve bitiş (Pazar) tarihleri."""
    start = date.fromisocalendar(year, week, 1)
    end = date.fromisocalendar(year, week, 7)
    return start.isoformat(), end.isoformat()


def _month_bounds(year, month):
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


# ---------------------------------------------------------------------------
# Sismik Enerji Hesabı
# ---------------------------------------------------------------------------

def seismic_moment(magnitude):
    """
    Sismik moment M0 (dyn·cm).
    Hanks & Kanamori (1979): Mw = (2/3)·log10(M0) − 10.7  (M0 dyn·cm)
    => M0 = 10^(1.5·(Mw + 10.7)) dyn·cm  (= ×10⁻⁷ N·m)
    """
    return 10 ** (1.5 * (magnitude + 10.7))


def seismic_moment_nm(magnitude):
    """Sismik moment M0 (N·m)."""
    return seismic_moment(magnitude) * 1e-7


def seismic_energy_joules(magnitude):
    """
    Sismik enerji (Joule)
    Gutenberg-Richter enerji-magnitüd: log10(E) = 1.5 * M + 4.8
    => E = 10^(1.5 * M + 4.8)
    (E in Joules)
    """
    return 10 ** (1.5 * magnitude + 4.8)


# ---------------------------------------------------------------------------
# Gutenberg-Richter Analizi
# Kaynaklar: Gutenberg & Richter (1944); Aki (1965) MLE;
# Utsu (1966) ayrıklaştırma düzeltmesi; Wiemer & Wyss (2000) MAXC;
# Shi & Bolt (1982) belirsizlik. Parametrizasyon SeismoStats ile uyumlu:
#   N(m) = 10^(a − b·m),  a = log10(N≥mc) + b·mc
# ---------------------------------------------------------------------------

DELTA_M = 0.1  # katalog magnitüd ayrıklaştırma adımı


def estimate_mc_maxc(magnitudes, bin_width=0.1, correction=0.2):
    """
    Tamlık magnitüdü Mc — Maksimum Eğrilik (MAXC) yöntemi.
    Mc = argmax(bin) + düzeltme. Düzeltme varsayılan +0.2, eksik tahmini
    önler (Wiemer & Wyss 2000; Woessner & Wiemer 2005).
    Yetersiz veride None döner.
    """
    mags = [m for m in magnitudes if m is not None]
    if len(mags) < 20:
        return None
    lo = math.floor(min(mags) / bin_width) * bin_width
    hi = math.ceil(max(mags) / bin_width) * bin_width
    best_bin, best_n = None, -1
    b = lo
    while b < hi:
        n = sum(1 for m in mags if b <= m < b + bin_width)
        if n > best_n:
            best_n, best_bin = n, b
        b += bin_width
    if best_bin is None:
        return None
    return round(best_bin + correction, 2)


def b_uncertainty(b_value, n):
    """b belirsizliği — Aki yaklaşımı: σ ≈ b/√n."""
    if n <= 0:
        return 0.0
    return b_value / math.sqrt(n)

def calculate_b_value(magnitudes, m_min=None, method="mle"):
    """
    Gutenberg-Richter b-değeri hesaplama.
    log10(N) = a - b * M

    MLE metodu (Aki 1965), Utsu (1966) ayrıklaştırma düzeltmeli:
    b = log10(e) / (ortalama(M) - (Mc - ΔM/2))

    m_min verilmezse MAXC ile kestirilir (Wiemer & Wyss 2000);
    yetersiz veride güvenli varsayılanlara düşer.

    Döner: (b, a, Mc)  # Mc = completeness magnitude
    """
    mags_all = [m for m in (magnitudes or []) if m is not None]
    if len(mags_all) < 10:
        return 1.0, 3.0, 0.0

    if m_min is None:
        mc_est = estimate_mc_maxc(mags_all)
        m_min = mc_est if mc_est is not None else max(min(mags_all), 1.0)

    mags = [m for m in mags_all if m >= m_min - DELTA_M / 2]
    if len(mags) < 10:
        return 1.0, 3.0, m_min

    if method == "mle":
        mean_m = statistics.mean(mags)
        denom = mean_m - (m_min - DELTA_M / 2)
        if denom <= 0:
            return 1.0, 3.0, m_min
        b = math.log10(math.e) / denom
    else:
        # Least squares
        bins = Counter(round(m * 2) / 2 for m in mags)  # 0.5'lik binler
        sorted_bins = sorted(bins.items())
        cumulative = []
        total = len(mags)
        cum = total
        for mag_bin, cnt in sorted_bins:
            cumulative.append((mag_bin, cum))
            cum -= cnt

        m_vals = [c[0] for c in cumulative]
        log_n = [math.log10(c[1]) if c[1] > 0 else 0 for c in cumulative]
        if len(m_vals) < 3:
            return 1.0, 3.0, m_min

        n = len(m_vals)
        sum_x = sum(m_vals)
        sum_y = sum(log_n)
        sum_xy = sum(x * y for x, y in zip(m_vals, log_n))
        sum_xx = sum(x * x for x in m_vals)
        b = (n * sum_xy - sum_x * sum_y) / (n * sum_xx - sum_x * sum_x)
        if b <= 0:
            b = 1.0

    # a = log10(N) + b * M_min  (aktivite seviyesi)
    a = math.log10(len(mags)) + b * m_min

    return b, a, m_min


def expected_max_magnitude(b, a):
    """
    G-R'dan beklenen maksimum magnitüd.
    N(M>=Mmax) = 1 log10(1) = 0 => Mmax = a / b
    """
    if b <= 0:
        return 0
    return a / b


# ---------------------------------------------------------------------------
# Poisson Zaman Modeli
# ---------------------------------------------------------------------------

def poisson_probability(lambda_rate, time_window_days=7):
    """
    Poisson dağılımı ile M≥threshold olayının time_window_days içinde olma olasılığı.
    P(k≥1) = 1 - exp(-λ * t)
    """
    return 1 - math.exp(-lambda_rate * time_window_days)


def estimate_lambda(earthquakes, min_mag=None, declustered=False):
    """
    Günlük olay hızı λ (lambda) tahmini.
    λ = N / T (gün)

    declustered=True ise Gardner-Knopoff (1974) pencereleriyle artçılar
    ayıklanır, artçı-kümelenmeden arındırılmış zemin hızı döner.
    Poisson hesabı için zemin hızı kullanılmalıdır (Gardner & Knopoff 1974).
    """
    if declustered:
        earthquakes = decluster_gardner_knopoff(earthquakes)

    if not earthquakes:
        return 0.0

    mags = [e["magnitude"] for e in earthquakes if e.get("magnitude")]
    if min_mag:
        mags = [m for m in mags if m >= min_mag]
    if not mags:
        return 0.0

    timestamps = [e["timestamp"] for e in earthquakes if e.get("timestamp")]
    if not timestamps:
        return 0.0

    t_span_days = (max(timestamps) - min(timestamps)) / 86400
    if t_span_days <= 0:
        return 0.0

    return len(mags) / t_span_days


def _gk_windows(magnitude):
    """
    Gardner-Knopoff (1974) artçı pencereleri.
    d = 10^(0.1238·M + 0.983) km
    M<6.5: t = 10^(0.5409·M − 0.547) gün
    M≥6.5: t = 10^(0.032·M + 2.7389) gün
    """
    d = 10 ** (0.1238 * magnitude + 0.983)
    if magnitude >= 6.5:
        t = 10 ** (0.032 * magnitude + 2.7389)
    else:
        t = 10 ** (0.5409 * magnitude - 0.547)
    return t, d


def _haversine_km(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, sqrt, atan2
    r = 6371.0
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def decluster_gardner_knopoff(earthquakes):
    """
    Gardner-Knopoff (1974) pencere yöntemiyle artçı ayıklama.
    Büyükten küçüğe: her olay, penceresi içindeki küçükleri kümeye alır;
    sahipsiz kalanlar zemin (background) kataloğudur.
    """
    evs = [e for e in (earthquakes or [])
           if e.get("timestamp") and e.get("magnitude") is not None
           and e.get("latitude") is not None and e.get("longitude") is not None]
    if len(evs) < 3:
        return list(earthquakes or [])

    by_mag = sorted(evs, key=lambda e: e["magnitude"], reverse=True)
    claimed = set()
    for i, main in enumerate(by_mag):
        t_win_days, d_win_km = _gk_windows(main["magnitude"])
        t_win = t_win_days * 86400
        for j in range(i + 1, len(by_mag)):
            cand = by_mag[j]
            if id(cand) in claimed:
                continue
            dt = abs(cand["timestamp"] - main["timestamp"])
            if dt > t_win:
                continue
            dist = _haversine_km(main["latitude"], main["longitude"],
                                 cand["latitude"], cand["longitude"])
            if dist <= d_win_km:
                claimed.add(id(cand))

    return [e for e in evs if id(e) not in claimed]


def omori_forecast(earthquakes, days_ahead=7, m_cut=3.0):
    """
    Artçı öngörüsü — Omori-Utsu azalımı + Reasenberg-Jones (1989) üretkenliği.
    R(t) = 10^[a + b·(Mm − Mkes)] / (t + c)^p

    Jenerik California parametreleri (R&J 1989): a=−1.67, b=0.91,
    p=1.08, c=0.05 gün. Marmara'ya kalibre DEĞİLDİR; mertebe tahminidir.
    Son 30 gündeki en büyük M≥4.0 olayı ana şok sayılır.

    Döner: None (uygun ana şok yok) veya sözlük.
    Kaynak: Reasenberg & Jones (1989) Science; USGS OAF dokümantasyonu.
    """
    from datetime import datetime as _dt
    now = _dt.now().timestamp()
    cands = [e for e in (earthquakes or [])
             if (e.get("magnitude") or 0) >= 4.0 and e.get("timestamp")
             and 0 <= now - e["timestamp"] <= 30 * 86400]
    if not cands:
        return None
    main = max(cands, key=lambda e: e["magnitude"])
    mm = main["magnitude"]
    t0 = max((now - main["timestamp"]) / 86400, 0.0)

    a, b, p, c = -1.67, 0.91, 1.08, 0.05
    k = 10 ** (a + b * (mm - m_cut))
    if p == 1.0:
        import math as _m
        expected = k * _m.log((t0 + days_ahead + c) / (t0 + c))
    else:
        expected = k / (1 - p) * ((t0 + days_ahead + c) ** (1 - p) - (t0 + c) ** (1 - p))
    expected = max(expected, 0.0)
    import math as _m2
    prob = 1 - _m2.exp(-expected)

    return {
        "mainshock_mag": round(mm, 1),
        "mainshock_time": main.get("occurred_at", "?"),
        "mainshock_loc": (main.get("location") or "?")[:40],
        "days_since": round(t0, 1),
        "m_cut": m_cut,
        "days_ahead": days_ahead,
        "expected_count": round(expected, 2),
        "probability": round(prob, 4),
        "generic_params": True,
    }


# ---------------------------------------------------------------------------
# Omori-Utsu Artçı Modeli
# ---------------------------------------------------------------------------

def omori_utsu_rate(t, c=0.5, p=1.0, k=1.0):
    """
    Omori-Utsu artçı sismisite oranı:
    n(t) = K / (t + c)^p
    t: ana şoktan bu yana geçen gün
    """
    return k / ((t + c) ** p)


def detect_anomalous_activity(earthquakes, lookback_days=7, z_threshold=2.0):
    """
    Anormal sismik aktivite tespiti (Z-skor yöntemi).
    Son lookback_days gündeki aktivite, önceki döneme göre anormal mi?
    """
    if not earthquakes or len(earthquakes) < 20:
        return 0.0

    now = datetime.now().timestamp()
    cutoff = now - lookback_days * 86400
    history_cutoff = now - lookback_days * 2 * 86400

    recent = [e for e in earthquakes if e.get("timestamp", 0) >= cutoff]
    historic = [e for e in earthquakes if history_cutoff <= e.get("timestamp", 0) < cutoff]

    if not historic:
        return 0.0

    # Günlük olay sayılarını karşılaştır
    recent_daily = len(recent) / lookback_days
    historic_daily = len(historic) / lookback_days

    if historic_daily <= 0:
        return 0.0

    z_score = (recent_daily - historic_daily) / (historic_daily ** 0.5 + 0.001)
    return z_score  # 2+ = anomali, 3+ = güçlü anomali


# ---------------------------------------------------------------------------
# Ana Agregasyon Fonksiyonları
# ---------------------------------------------------------------------------

def compute_weekly_stats(region="marmara"):
    """Son haftanın istatistiklerini hesapla ve kaydet."""
    now = datetime.now()
    iso = now.isocalendar()
    year, week = iso[0], iso[1]
    week_start, week_end = _week_bounds(year, week)

    since = datetime.fromisoformat(week_start)
    until = datetime.fromisoformat(week_end) + timedelta(days=1)

    quakes = get_earthquakes(since=since, until=until, region=region)

    if not quakes:
        logger.info(f"Hafta {year}-{week}: deprem verisi yok, atlanıyor.")
        return None

    mags = [q["magnitude"] for q in quakes if q.get("magnitude")]
    depths = [q["depth_km"] for q in quakes if q.get("depth_km") is not None]

    total_energy = sum(seismic_energy_joules(m) for m in mags)
    b_val, a_val, mc = calculate_b_value(mags)
    max_mag_exp = expected_max_magnitude(b_val, a_val)

    # Risk skoru (0-1)
    risk = _compute_risk_score(quakes, b_val, a_val, total_energy)

    stats = {
        "year": year,
        "week": week,
        "week_start": week_start,
        "week_end": week_end,
        "region_tag": region,
        "quake_count": len(quakes),
        "min_mag": min(mags) if mags else 0,
        "max_mag": max(mags) if mags else 0,
        "avg_mag": statistics.mean(mags) if mags else 0,
        "median_mag": statistics.median(mags) if mags else 0,
        "total_energy_j": total_energy,
        "avg_depth_km": statistics.mean(depths) if depths else 0,
        "min_depth_km": min(depths) if depths else 0,
        "max_depth_km": max(depths) if depths else 0,
        "b_value": round(b_val, 4),
        "a_value": round(a_val, 4),
        "max_mag_expected": round(max_mag_exp, 2),
        "risk_score": round(risk, 4),
    }

    save_weekly_stats(stats)
    logger.info(f"Haftalık istatistik kaydedildi: {year}-W{week}, {len(quakes)} deprem, risk={risk:.3f}")
    return stats


def compute_monthly_stats(region="marmara"):
    """Son ayın istatistiklerini hesapla ve kaydet."""
    now = datetime.now()
    year, month = now.year, now.month

    month_start, month_end = _month_bounds(year, month)

    since = datetime.fromisoformat(month_start)
    until = datetime.fromisoformat(month_end) + timedelta(days=1)

    quakes = get_earthquakes(since=since, until=until, region=region)

    if not quakes:
        logger.info(f"Ay {year}-{month}: deprem verisi yok, atlanıyor.")
        return None

    mags = [q["magnitude"] for q in quakes if q.get("magnitude")]
    depths = [q["depth_km"] for q in quakes if q.get("depth_km") is not None]

    total_energy = sum(seismic_energy_joules(m) for m in mags)
    b_val, a_val, mc = calculate_b_value(mags)
    max_mag_exp = expected_max_magnitude(b_val, a_val)
    risk = _compute_risk_score(quakes, b_val, a_val, total_energy)

    stats = {
        "year": year,
        "month": month,
        "region_tag": region,
        "quake_count": len(quakes),
        "min_mag": min(mags) if mags else 0,
        "max_mag": max(mags) if mags else 0,
        "avg_mag": statistics.mean(mags) if mags else 0,
        "median_mag": statistics.median(mags) if mags else 0,
        "total_energy_j": total_energy,
        "avg_depth_km": statistics.mean(depths) if depths else 0,
        "b_value": round(b_val, 4),
        "a_value": round(a_val, 4),
        "max_mag_expected": round(max_mag_exp, 2),
        "risk_score": round(risk, 4),
    }

    save_monthly_stats(stats)
    logger.info(f"Aylık istatistik kaydedildi: {year}-{month:02d}, {len(quakes)} deprem, risk={risk:.3f}")
    return stats


def _stats_for_quakes(quakes):
    """Deprem listesinden ortak istatistik sözlüğü (kayıt/seviye hariç)."""
    mags = [q["magnitude"] for q in quakes if q.get("magnitude")]
    depths = [q["depth_km"] for q in quakes if q.get("depth_km") is not None]
    total_energy = sum(seismic_energy_joules(m) for m in mags)
    b_val, a_val, mc = calculate_b_value(mags)
    max_mag_exp = expected_max_magnitude(b_val, a_val)
    risk = _compute_risk_score(quakes, b_val, a_val, total_energy)
    return {
        "quake_count": len(quakes),
        "min_mag": min(mags) if mags else 0,
        "max_mag": max(mags) if mags else 0,
        "avg_mag": statistics.mean(mags) if mags else 0,
        "median_mag": statistics.median(mags) if mags else 0,
        "total_energy_j": total_energy,
        "avg_depth_km": statistics.mean(depths) if depths else 0,
        "min_depth_km": min(depths) if depths else 0,
        "max_depth_km": max(depths) if depths else 0,
        "b_value": round(b_val, 4),
        "a_value": round(a_val, 4),
        "max_mag_expected": round(max_mag_exp, 2),
        "risk_score": round(risk, 4),
    }


def backfill_history(weeks=26, months=12, region="marmara"):
    """Geçmiş haftaları/ayları geriye dönük hesaplayıp kaydet.

    Sadece kayıtlı veri bulunan ve henüz tabloda olmayan dönemleri yazar.
    Döner: (yazılan_hafta, yazılan_ay)
    """
    from deprem_izleme.db import get_weekly_history, get_monthly_history
    written_w = written_m = 0
    today = date.today()

    existing_w = {(s["year"], s["week"]) for s in get_weekly_history(limit=500, region=region)}
    # ISO hafta listesi: bu haftadan geriye
    monday = today - timedelta(days=today.weekday())
    for i in range(weeks):
        ref = monday - timedelta(weeks=i)
        iso = ref.isocalendar()
        if (iso[0], iso[1]) in existing_w:
            continue
        ws, we = _week_bounds(iso[0], iso[1])
        since = datetime.fromisoformat(ws)
        until = datetime.fromisoformat(we) + timedelta(days=1)
        quakes = get_earthquakes(since=since, until=until, region=region)
        if not quakes:
            continue
        stats = {"year": iso[0], "week": iso[1], "week_start": ws,
                 "week_end": we, "region_tag": region}
        stats.update(_stats_for_quakes(quakes))
        save_weekly_stats(stats)
        written_w += 1

    existing_m = {(s["year"], s["month"]) for s in get_monthly_history(limit=500, region=region)}
    y, m = today.year, today.month
    for _ in range(months):
        if (y, m) not in existing_m:
            ms, me = _month_bounds(y, m)
            since = datetime.fromisoformat(ms)
            until = datetime.fromisoformat(me) + timedelta(days=1)
            quakes = get_earthquakes(since=since, until=until, region=region)
            if quakes:
                stats = {"year": y, "month": m, "region_tag": region}
                stats.update(_stats_for_quakes(quakes))
                # weekly'e özel alanları ele
                stats.pop("min_depth_km", None)
                stats.pop("max_depth_km", None)
                save_monthly_stats(stats)
                written_m += 1
        m -= 1
        if m == 0:
            m, y = 12, y - 1

    if written_w or written_m:
        logger.info(f"Geçmiş dolduruldu: {written_w} hafta, {written_m} ay ({region})")
    return written_w, written_m


# ---------------------------------------------------------------------------
# Risk Skoru Hesaplama (birleşik)
# ---------------------------------------------------------------------------

def _compute_risk_score(quakes, b_value, a_value, total_energy):
    """
    0-1 arası normalize risk skoru.
    Faktörler:
    1. b-değeri anomali (düşük b = yüksek stress = yüksek risk)
    2. Enerji salınım hızı (uzun dönem ortalamaya göre)
    3. Sismik moment birikimi / boşalma oranı
    4. Anormal aktivite Z-skoru
    """
    if not quakes:
        return 0.0

    scores = []

    # 1. b-değeri faktörü (referans ~1.0)
    # Düşük b (<0.7) yüksek stress göstergesi
    b_ref = 1.0
    b_anomaly = max(0, (b_ref - b_value) / b_ref)  # 0..1, b=0.5->0.5, b=0.3->0.7
    b_score = min(1.0, b_anomaly * 1.5)  # scale
    scores.append(("b_degeri", b_score, 0.25))

    # 2. Enerji salınım hızı
    # Beklenen günlük enerji (arkaplan): M2.0 ~ 6.3e7 J
    # Yüksek enerji salınımı = anomali
    timestamps = [q["timestamp"] for q in quakes if q.get("timestamp")]
    if timestamps and len(timestamps) > 1:
        span_days = (max(timestamps) - min(timestamps)) / 86400
        if span_days > 0:
            daily_energy = total_energy / span_days
            # Referans: günde ~10^8 J (arkaplan)
            energy_ratio = daily_energy / 1e8
            energy_score = min(1.0, math.log10(max(energy_ratio, 0.1)) / 3 + 0.5)
            energy_score = max(0, min(1, energy_score))
        else:
            energy_score = 0.3
    else:
        energy_score = 0.3
    scores.append(("enerji", energy_score, 0.20))

    # 3. En büyük depremin büyüklüğü (göreceli)
    # Beklenen Mmax'a ne kadar yakın?
    mags = [q["magnitude"] for q in quakes if q.get("magnitude")]
    if mags:
        max_mag = max(mags)
        if a_value > 0 and b_value > 0:
            expected_mmax = expected_max_magnitude(b_value, a_value)
            if expected_mmax > 0:
                mmax_ratio = max_mag / expected_mmax
                mmax_score = min(1.0, mmax_ratio * 1.2)  # 0.8 = 0.96 score
            else:
                mmax_score = 0.3
        else:
            mmax_score = 0.3
    else:
        mmax_score = 0.3
    scores.append(("mmax", mmax_score, 0.15))

    # 4. Anomalik aktivite (Z-skor)
    z = detect_anomalous_activity(quakes)
    z_score = min(1.0, max(0, z / 3.5))  # z=3.5 -> 1.0
    scores.append(("z_skor", z_score, 0.15))

    # 5. Derinlik anomalisi (sığ depremler daha riskli)
    depths = [q["depth_km"] for q in quakes if q.get("depth_km") is not None]
    if depths:
        avg_depth = statistics.mean(depths)
        # Sığ: <10km riskli, 10-20 orta, 20+ düşük
        depth_score = max(0, min(1, (20 - avg_depth) / 20))
    else:
        depth_score = 0.5
    scores.append(("derinlik", depth_score, 0.10))

    # 6. Poisson olasılığı (M≥4.0 olma olasılığı)
    lambda_rate = estimate_lambda(quakes, min_mag=3.0)
    poisson_prob = poisson_probability(lambda_rate, time_window_days=7)
    poisson_score = min(1.0, poisson_prob * 2.0)  # scale
    scores.append(("poisson", poisson_score, 0.15))

    # Ağırlıklı toplam
    total_weight = sum(w for _, _, w in scores)
    weighted_sum = sum(val * weight for _, val, weight in scores)

    return weighted_sum / total_weight


_report_cache = {}  # region -> (computed_at, signature, report)


def _catalog_signature(region, days=60):
    """Veri değişimini yakalayan hafif imza (adet, en yeni zaman)."""
    from datetime import datetime as _dt3
    from deprem_izleme.db import _region_clause
    cutoff = int(_dt3.now().timestamp()) - days * 86400
    rclause, rparams = _region_clause(region)
    where = f"WHERE timestamp >= ? AND {rclause}" if rclause else "WHERE timestamp >= ?"
    conn = get_db(MAIN_DB)
    try:
        row = conn.execute(
            f"SELECT COUNT(*), COALESCE(MAX(timestamp), 0) FROM earthquakes {where}",
            [cutoff] + rparams).fetchone()
        return (row[0], row[1])
    finally:
        conn.close()


def daily_risk_light(mags):
    """Günlük risk için hafif vekil skor (grafik overlay'leri için).

    Tam _compute_risk_score gün×segment başına O(N) maliyetlidir;
    bu fonksiyon O(1)'dir: 0.65·Mmax/5 + 0.35·adet/12.
    """
    if not mags:
        return 0.0
    m_score = min(1.0, max(mags) / 5.0)
    c_score = min(1.0, len(mags) / 12.0)
    return round(0.65 * m_score + 0.35 * c_score, 3)


def get_comprehensive_risk_report(region="marmara", max_age=45):
    """
    Kapsamlı risk raporu - tüm metrikleri bir arada.
    Artık fay segment analizi, tarihsel veri ve BVAL trendini de içerir.

    Aynı veri üzerinde 45 sn önbelleklidir (gösterge/ekranların
    tekrarlı ağır hesabı engellenir).
    """
    from datetime import datetime as _dt2
    now_ts = _dt2.now().timestamp()
    sig = _catalog_signature(region)
    ent = _report_cache.get(region)
    if ent and now_ts - ent[0] < max_age and ent[1] == sig:
        return ent[2]

    quakes = get_earthquakes(since=datetime.now() - timedelta(days=30), region=region)
    mags = [q["magnitude"] for q in quakes if q.get("magnitude")]

    b_val, a_val, mc = calculate_b_value(mags)
    total_energy = sum(seismic_energy_joules(m) for m in mags)
    risk = _compute_risk_score(quakes, b_val, a_val, total_energy)

    # Poisson olasılıkları: HAM oran + artçı-ayıklanmış (GK74) zemin oranı.
    # Poisson varsayımı gereği raporlanan olasılık zemin orana dayanır.
    lambda_m3 = estimate_lambda(quakes, min_mag=3.0)
    lambda_m4 = estimate_lambda(quakes, min_mag=4.0)
    lambda_m3_bg = estimate_lambda(quakes, min_mag=3.0, declustered=True)
    lambda_m4_bg = estimate_lambda(quakes, min_mag=4.0, declustered=True)
    p_m4_7days = poisson_probability(lambda_m4_bg, 7)
    p_m4_30days = poisson_probability(lambda_m4_bg, 30)

    z = detect_anomalous_activity(quakes)
    m_max_expected = expected_max_magnitude(b_val, a_val)
    max_mag = max(mags) if mags else 0
    b_std = b_uncertainty(b_val, len([m for m in mags if m >= mc]))

    bg_quakes = decluster_gardner_knopoff(quakes)
    ts_all = [q["timestamp"] for q in quakes if q.get("timestamp")]
    catalog_days = round((max(ts_all) - min(ts_all)) / 86400, 1) if len(ts_all) >= 2 else 0.0

    # Artçı öngörüsü (Omori + R&J89 jenerik)
    try:
        aftershock = omori_forecast(quakes, days_ahead=7, m_cut=3.0)
    except Exception:
        aftershock = None

    # ---- YENİ: Fay segment riski ----
    try:
        from deprem_izleme.fault_segments import compute_fault_risk_score, compute_bval_trend
        fault_risk, segment_scores = compute_fault_risk_score(quakes)
        bval_trend = compute_bval_trend(quakes)
    except ImportError:
        fault_risk = 0.5
        segment_scores = []
        bval_trend = None

    # ---- YENİ: Stress transferi ----
    try:
        from deprem_izleme.stress_transfer import get_total_stress_transfer
        stress_total, stress_segments, stress_max = get_total_stress_transfer(quakes)
    except ImportError:
        stress_total, stress_segments, stress_max = 0, [], None

    # ---- YENİ: Birleşik skor (eski risk + fay riski harmanı) ----
    enhanced_risk = 0.65 * risk + 0.35 * fault_risk
    enhanced_risk = min(1.0, max(0.0, enhanced_risk))

    report = {
        "region": region,
        "analysis_period_days": 30,
        "quake_count": len(quakes),
        "no_data": len(quakes) < 5,
        "gutenberg_richter": {
            "b_value": round(b_val, 4),
            "b_std": round(b_std, 4),
            "a_value": round(a_val, 4),
            "magnitude_completeness": round(mc, 2),
            "mc_method": "MAXC+0.2" if mc else "varsayılan",
            "expected_max_magnitude": round(m_max_expected, 2),
            "observed_max_magnitude": max_mag,
            "b_anomaly": round(b_val - 1.0, 4),
        },
        "energy": {
            "total_energy_joules": total_energy,
            "total_energy_tnt_tons": total_energy / 4.184e9,
        },
        "poisson": {
            "lambda_m3_per_day": round(lambda_m3, 4),
            "lambda_m4_per_day": round(lambda_m4, 4),
            "lambda_m4_bg_per_day": round(lambda_m4_bg, 4),
            "p_m4_7days_pct": round(p_m4_7days * 100, 2),
            "p_m4_30days_pct": round(p_m4_30days * 100, 2),
            "declustered": True,
            "background_count": len(bg_quakes),
        },
        "catalog_span_days": catalog_days,
        "aftershock": aftershock,
        "anomaly_z_score": round(z, 3),
        "composite_risk_score": round(risk, 4),
        "enhanced_risk_score": round(enhanced_risk, 4),
        "risk_level": _risk_level(risk),
        "enhanced_risk_level": _risk_level(enhanced_risk),
        # YENİ alanlar
        "fault_risk": {
            "score": round(fault_risk, 4),
            "segments": segment_scores,
        },
        "bval_trend": bval_trend,
        "stress_transfer": {
            "total_stress_bars": round(stress_total, 4),
            "segments": stress_segments,
            "max_segment": stress_max["name"] if stress_max else None,
            "max_stress": round(stress_max["stress_bars"], 4) if stress_max else 0,
        },
    }
    _report_cache[region] = (now_ts, sig, report)
    return report


def _risk_level(score):
    if score >= 0.8:
        return "ÇOK YÜKSEK"
    elif score >= 0.6:
        return "YÜKSEK"
    elif score >= 0.4:
        return "ORTA"
    elif score >= 0.2:
        return "DÜŞÜK"
    return "ÇOK DÜŞÜK"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    compute_weekly_stats()
    compute_monthly_stats()
    report = get_comprehensive_risk_report()
    for k, v in report.items():
        print(f"{k}: {v}")
