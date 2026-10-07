"""
Marmara Denizi Fay Segmentleri - Koordinatlar, parametreler ve risk hesaplamaları
Akademik kaynaklara dayalı: Armijo (2002,2005), MARSITE D7.2, Le Pichon (2001,2016)
"""
import math
from datetime import datetime, timedelta
from deprem_izleme.db import get_earthquakes

# =====================================================================
# MARMARA FAY SEGMENTLERİ
# Kaynak: Armijo et al. (2005), MARSITE D7.2, Le Pichon et al. (2016)
# Güncel: Science (Martínez-Garzón 2025), GFZ (Bohnhoff 2025), Temblor (Stein 2025)
# =====================================================================

# Her segment: {parametreler, koordinatlar, tekrarlama aralığı, kitlenme durumu}
# Recurrence intervals based on: Nishenko & Buland (1987), Parsons (2004),
# Rockwell et al. (2009), Meghraoui et al. (2012), Science 2025
FAULT_SEGMENTS = [
    {
        "name": "Ganos",
        "name_tr": "Ganos Fayı",
        "coords": [
            [40.615, 26.450], [40.655, 26.600], [40.685, 26.750],
            [40.700, 26.900], [40.715, 27.050], [40.740, 27.200],
        ],
        "type": "SSF",
        "slip_rate": 20.0,
        "last_rupture": 1912,
        "last_rupture_mag": 7.3,
        "max_magnitude": 7.3,
        "length_km": 55,
        "color": "#10b981",
        "risk_factor": 0.4,
        "recurrence_years": 250,
        "recurrence_source": "Rockwell et al. (2009) BSSA",
        "locked_status": "recently_ruptured",
        "seismic_gap_years": None,
    },
    {
        "name": "Tekirdag",
        "name_tr": "Tekirdağ Segmenti",
        "coords": [
            [40.762, 27.200], [40.770, 27.225], [40.778, 27.250],
            [40.785, 27.280], [40.792, 27.310], [40.798, 27.340],
            [40.803, 27.370], [40.807, 27.400], [40.811, 27.430],
            [40.814, 27.460], [40.816, 27.490], [40.818, 27.520],
            [40.820, 27.550], [40.821, 27.580], [40.822, 27.610],
            [40.823, 27.640], [40.824, 27.670], [40.825, 27.700],
            [40.826, 27.730], [40.828, 27.755],
        ],
        "type": "SSF",
        "slip_rate": 22.0,
        "last_rupture": 1766,
        "last_rupture_mag": 7.0,
        "max_magnitude": 7.1,
        "length_km": 50,
        "color": "#ef4444",
        "risk_factor": 0.85,
        "recurrence_years": 300,
        "recurrence_source": "Parsons (2004) JGR; Kutoğlu (2025)",
        "locked_status": "locked",
        "seismic_gap_years": 260,
    },
    {
        "name": "Central",
        "name_tr": "Orta Marmara Sırtı",
        "coords": [
            [40.829, 27.755], [40.830, 27.780], [40.832, 27.805],
            [40.834, 27.830], [40.836, 27.855], [40.838, 27.880],
            [40.841, 27.905], [40.844, 27.930], [40.847, 27.955],
            [40.850, 27.975], [40.853, 27.995], [40.856, 28.015],
            [40.860, 28.035], [40.864, 28.055], [40.868, 28.075],
            [40.872, 28.095], [40.875, 28.110],
        ],
        "type": "SSF",
        "slip_rate": 20.0,
        "last_rupture": 2025,
        "last_rupture_mag": 6.2,
        "max_magnitude": 7.0,
        "length_km": 35,
        "color": "#f59e0b",
        "risk_factor": 0.65,
        "recurrence_years": 350,
        "recurrence_source": "Science (Martínez-Garzón 2025)",
        "locked_status": "transitional",
        "seismic_gap_years": None,
    },
    {
        "name": "Kumburgaz",
        "name_tr": "Kumburgaz Segmenti",
        "coords": [
            [40.876, 28.110], [40.878, 28.130], [40.880, 28.150],
            [40.881, 28.170], [40.882, 28.190], [40.883, 28.205],
            [40.884, 28.220], [40.885, 28.235], [40.886, 28.250],
            [40.887, 28.265], [40.888, 28.280], [40.888, 28.295],
            [40.889, 28.310], [40.889, 28.325], [40.890, 28.340],
            [40.891, 28.350],
        ],
        "type": "SSF",
        "slip_rate": 20.0,
        "last_rupture": 2025,
        "last_rupture_mag": 6.2,
        "last_rupture_note": "23.04.2025 M6.2 kısmi kırılma (Kumburgaz batısı)",
        "max_magnitude": 7.2,
        "length_km": 30,
        "color": "#eab308",
        "risk_factor": 0.80,
        "recurrence_years": 350,
        "recurrence_source": "Armijo (2005), Science (2025)",
        "locked_status": "locked",
        "seismic_gap_years": 500,
    },
    {
        "name": "Avcilar",
        "name_tr": "Avcılar Segmenti",
        "coords": [
            [40.892, 28.350], [40.893, 28.365], [40.894, 28.380],
            [40.896, 28.395], [40.897, 28.410], [40.899, 28.425],
            [40.901, 28.440], [40.903, 28.455], [40.905, 28.470],
            [40.907, 28.485], [40.909, 28.500], [40.911, 28.515],
            [40.913, 28.530], [40.915, 28.545], [40.917, 28.555],
            [40.920, 28.565],
        ],
        "type": "SSF",
        "slip_rate": 18.0,
        "last_rupture": 1509,
        "last_rupture_mag": 7.2,
        "max_magnitude": 7.3,
        "length_km": 30,
        "color": "#f97316",
        "risk_factor": 0.75,
        "recurrence_years": 500,
        "recurrence_source": "Ambraseys (2002), Science (2025)",
        "locked_status": "locked",
        "seismic_gap_years": 517,
    },
    {
        "name": "Adalar",
        "name_tr": "Adalar Segmenti",
        "coords": [
            [40.922, 28.565], [40.924, 28.580], [40.926, 28.595],
            [40.928, 28.610], [40.930, 28.625], [40.932, 28.640],
            [40.934, 28.655], [40.936, 28.670], [40.938, 28.690],
            [40.940, 28.710], [40.943, 28.730], [40.946, 28.750],
            [40.949, 28.770], [40.952, 28.790], [40.955, 28.810],
            [40.958, 28.830], [40.961, 28.855], [40.964, 28.880],
            [40.967, 28.905], [40.970, 28.930], [40.973, 28.955],
            [40.976, 28.980], [40.979, 29.000], [40.982, 29.020],
            [40.985, 29.040], [40.988, 29.060], [40.990, 29.080],
            [40.992, 29.095],
        ],
        "type": "SSF",
        "slip_rate": 18.0,
        "last_rupture": 1766,
        "last_rupture_mag": 7.3,
        "max_magnitude": 7.4,
        "length_km": 55,
        "color": "#f59e0b",
        "risk_factor": 0.70,
        "recurrence_years": 260,
        "recurrence_source": "Parsons (2004), Temblor (Stein 2025)",
        "locked_status": "locked",
        "seismic_gap_years": 260,
    },
    {
        "name": "Cinarcik",
        "name_tr": "Çınarcık Segmenti",
        "coords": [
            [40.993, 29.095], [40.994, 29.115], [40.995, 29.135],
            [40.996, 29.155], [40.997, 29.175], [40.998, 29.195],
            [40.999, 29.215], [41.000, 29.235], [41.001, 29.255],
            [41.002, 29.275], [41.003, 29.295], [41.004, 29.315],
            [41.005, 29.335], [41.006, 29.355], [41.007, 29.375],
            [41.008, 29.395], [41.009, 29.410], [41.010, 29.425],
            [41.011, 29.440], [41.012, 29.455],
        ],
        "type": "SSF",
        "slip_rate": 17.0,
        "last_rupture": 1894,
        "last_rupture_mag": 7.0,
        "max_magnitude": 7.0,
        "length_km": 35,
        "color": "#e67e22",
        "risk_factor": 0.60,
        "recurrence_years": 200,
        "recurrence_source": "Ambraseys (2002)",
        "locked_status": "transitional",
        "seismic_gap_years": 132,
    },
    {
        "name": "Guney_Kol",
        "name_tr": "Güney Kol (Orta Kol)",
        "coords": [
            [40.280, 27.400], [40.300, 27.700], [40.325, 28.000],
            [40.335, 28.300], [40.345, 28.600], [40.355, 28.900],
            [40.375, 29.150], [40.400, 29.450], [40.430, 29.750],
        ],
        "type": "SSF",
        "slip_rate": 5.0,
        "last_rupture": 1953,
        "last_rupture_mag": 7.2,
        "max_magnitude": 7.2,
        "length_km": 160,
        "color": "#a78bfa",
        "risk_factor": 0.45,
        "recurrence_years": 800,
        "recurrence_source": "Ambraseys (2002)",
        "locked_status": "transitional",
        "seismic_gap_years": None,
    },
    {
        "name": "Hersek",
        "name_tr": "Hersek Bendi",
        "coords": [
            [40.722, 29.340], [40.725, 29.420], [40.735, 29.500],
            [40.750, 29.580], [40.765, 29.650],
        ],
        "type": "SSF",
        "slip_rate": 20.0,
        "last_rupture": 1999,
        "last_rupture_mag": 7.4,
        "last_rupture_note": "1999 İzmit kırılmasının batı ucu",
        "max_magnitude": 7.2,
        "length_km": 30,
        "color": "#EC4899",
        "risk_factor": 0.60,
        "recurrence_years": 300,
        "recurrence_source": "Parsons (2004)",
        "locked_status": "transitional",
        "seismic_gap_years": None,
    },
]


# Gercek izler varsa uygula (MTA sayisallastirma); yoksa sematik koordinatlar kalir.
try:
    from deprem_izleme.fault_traces import apply_traces
    apply_traces(FAULT_SEGMENTS)
except Exception:
    pass


def get_segment_coordinates(segment_name=None):
    """Fay segment koordinatlarını döndür."""
    if segment_name:
        for s in FAULT_SEGMENTS:
            if s["name"].lower() == segment_name.lower():
                return s["coords"]
        return []
    return {s["name"]: s["coords"] for s in FAULT_SEGMENTS}


def point_to_segment_distance(lat, lon, segment_coords):
    """Noktanın fay segmentine olan yaklaşık mesafesi (km)."""
    min_dist = float('inf')
    for i in range(len(segment_coords) - 1):
        lat1, lon1 = segment_coords[i]
        lat2, lon2 = segment_coords[i + 1]
        d = _point_line_distance(lat, lon, lat1, lon1, lat2, lon2)
        if d < min_dist:
            min_dist = d
    return min_dist


def _point_line_distance(plat, plon, lat1, lon1, lat2, lon2):
    """Nokta-doğru parçası mesafesi (Haversine tabanlı)."""
    # Projeksiyon için boylamı km'ye çevir
    from math import sin, cos, sqrt, radians, atan2

    # Lat/lon'u yaklaşık km'ye çevir
    def to_km(lat, lon):
        return lon * 111.32 * cos(radians(lat)), lat * 111.32

    px, py = to_km(plat, plon)
    x1, y1 = to_km(lat1, lon1)
    x2, y2 = to_km(lat2, lon2)

    # Vektör projeksiyonu
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return sqrt((px - x1) ** 2 + (py - y1) ** 2)

    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)


def get_nearest_fault(lat, lon):
    """Noktaya en yakın fay segmentini bul."""
    min_dist = float('inf')
    nearest = None
    for seg in FAULT_SEGMENTS:
        d = point_to_segment_distance(lat, lon, seg["coords"])
        if d < min_dist:
            min_dist = d
            nearest = seg
    return nearest, min_dist


def compute_fault_risk_score(earthquakes, region="marmara"):
    """
    Fay segmentlerine göre risk skoru hesaplama.
    Faktörler:
    1. Segment bazında yakınlık ve aktivite
    2. Son kırılma yılı (ne kadar eski = o kadar riskli)
    3. Kayma hızı (yüksek = yüksek risk)
    4. Deprem yoğunluğu (segment çevresinde)
    5. Kilitli/kreep oranı
    """
    if not earthquakes:
        return 0.5, []

    segment_scores = []
    now_year = datetime.now().year

    for seg in FAULT_SEGMENTS:
        score = seg["risk_factor"]  # base from literature

        # 1. Son kırılma faktörü: 250+ yıl = yüksek risk
        if seg["last_rupture"] is not None:
            elapsed = now_year - seg["last_rupture"]
            time_factor = min(1.0, elapsed / 300.0)  # 300 yılda normalize
        else:
            time_factor = 0.9  # hiç kırılmamış = çok yüksek

        # 2. Bu segmente yakın deprem sayısı
        nearby_count = 0
        nearby_max_mag = 0
        for eq in earthquakes:
            lat = eq.get("latitude", 0)
            lon = eq.get("longitude", 0)
            d = point_to_segment_distance(lat, lon, seg["coords"])
            if d < 20:  # 20km yakınlık
                nearby_count += 1
                mag = eq.get("magnitude", 0) or 0
                if mag > nearby_max_mag:
                    nearby_max_mag = mag

        # Aktivite faktörü (çok yakın deprem = o segmentte stres var)
        activity_factor = min(1.0, nearby_count / 20.0)

        # 3. En büyük yakın deprem faktörü
        mag_factor = min(1.0, nearby_max_mag / 4.0)

        # 4. Kayma hızı faktörü
        slip_factor = seg["slip_rate"] / 25.0  # normalize ~23mm/yr

        # 5. KİTLİ FAY / SİSMİK BOŞLUK FAKTÖRÜ (YENİ)
        locked_map = {"locked": 1.0, "transitional": 0.6, "recently_ruptured": 0.2}
        locked_factor = locked_map.get(seg.get("locked_status", "transitional"), 0.5)

        # 6. Sismik boşluk / tekrarlama aralığı oranı
        gap_years = seg.get("seismic_gap_years")
        rec_years = seg.get("recurrence_years")
        if gap_years is not None and rec_years and rec_years > 0:
            gap_ratio = gap_years / rec_years  # 1.0 = tekrarlama zamanı gelmiş
            gap_factor = min(1.0, gap_ratio * 1.5)  # scale, 0.67 → 1.0
        else:
            gap_factor = 0.3

        # Birleşik segment skoru
        combined = (
            0.20 * score +
            0.20 * time_factor +
            0.10 * activity_factor +
            0.05 * mag_factor +
            0.10 * slip_factor +
            0.10 * (seg["max_magnitude"] / 8.0) +
            0.15 * locked_factor +        # YENİ: kitli fay
            0.10 * gap_factor              # YENİ: sismik boşluk
        )
        combined = min(1.0, max(0.0, combined))

        segment_scores.append({
            "name": seg["name_tr"],
            "name_en": seg["name"],
            "score": round(combined, 4),
            "time_since_last": seg["last_rupture"],
            "max_magnitude": seg["max_magnitude"],
            "nearby_quakes": nearby_count,
            "nearby_max_mag": round(nearby_max_mag, 1),
            "color": seg["color"],
            "locked_status": seg.get("locked_status", "?"),
            "recurrence_years": seg.get("recurrence_years"),
            "seismic_gap_years": seg.get("seismic_gap_years"),
            "gap_ratio": round(gap_ratio, 2) if gap_years is not None and rec_years else None,
        })

    # Genel fay bazlı risk: en yüksek 3 segmentin ortalaması
    sorted_scores = sorted(segment_scores, key=lambda x: x["score"], reverse=True)
    top3_avg = sum(s["score"] for s in sorted_scores[:3]) / 3

    return round(top3_avg, 4), segment_scores


# =====================================================================
# TARİHSEL DEPREM VERİLERİ (Marmara Bölgesi)
# Aletsel dönem (≥1894): aletsel büyüklükler. Tarihsel dönem: Ambraseys
# (2002) makrosismik kataloğu; büyüklükler ±0.3-0.5 belirsizlik taşır.
# =====================================================================

HISTORICAL_EARTHQUAKES = [
    # (yıl, enlem, boylam, magnitüd, yer)
    (1509, 40.90, 28.55, 7.2, "İstanbul depremi - Avcılar segmenti kırıldı"),
    (1556, 40.70, 28.00, 6.8, "Marmara Denizi"),
    (1646, 40.80, 27.50, 6.5, "Tekirdağ"),
    (1719, 40.85, 29.00, 6.8, "İzmit Körfezi"),
    (1754, 40.90, 28.80, 6.6, "İstanbul"),
    (1766, 40.95, 28.75, 7.3, "Büyük İstanbul depremi - Adalar segmenti"),
    (1855, 40.80, 27.30, 6.4, "Marmara Denizi Batı"),
    (1878, 40.75, 27.60, 6.0, "Marmara Denizi"),
    (1894, 41.00, 29.20, 7.0, "İzmit Körfezi - Çınarcık segmenti"),
    (1912, 40.73, 27.05, 7.3, "Şarköy-Mürefte - Ganos segmenti"),
    (1935, 40.65, 27.20, 6.4, "Erdek Körfezi"),
    (1953, 40.02, 27.53, 7.2, "Yenice-Gönen - güney kol (karada)"),
    (1963, 40.83, 29.18, 6.3, "Çınarcık (Ms 6.3)"),
    (1964, 40.15, 27.90, 6.8, "Manyas - güney kol (karada)"),
    (1999, 40.70, 29.99, 7.4, "İzmit depremi - Doğu Marmara"),
    (2019, 40.85, 28.15, 5.8, "Silivri depremi (Mw 5.7-5.8)"),
    (2025, 40.82, 28.05, 6.2, "Kumburgaz batısı - kısmi kırılma"),
]

# =====================================================================
# B-VALUE ZAMANSAL ANALİZİ (BVAL Metodu)
# =====================================================================

def compute_bval_trend(earthquakes, window_days=90, step_days=30):
    """
    BVAL metodunun basit uygulaması.
    Zaman pencereleri boyunca b-değeri değişimini hesapla.
    Düşen b = artan stress.
    """
    if not earthquakes or len(earthquakes) < 20:
        return None

    from deprem_izleme.aggregation import calculate_b_value

    timestamps = sorted([e["timestamp"] for e in earthquakes if e.get("timestamp")])
    mags = {e["timestamp"]: e["magnitude"] for e in earthquakes if e.get("timestamp") and e.get("magnitude")}

    if not timestamps:
        return None

    t_min = timestamps[0]
    t_max = timestamps[-1]
    span = t_max - t_min

    if span < window_days * 86400:
        return None

    windows = []
    t = t_min
    while t + window_days * 86400 <= t_max:
        t_end = t + window_days * 86400
        window_mags = [m for ts, m in mags.items() if t <= ts <= t_end]

        if len(window_mags) >= 10:
            b_val, a_val, mc = calculate_b_value(window_mags)
            windows.append({
                "start": datetime.fromtimestamp(t).isoformat(),
                "end": datetime.fromtimestamp(t_end).isoformat(),
                "b_value": b_val,
                "quake_count": len(window_mags),
            })
        t += step_days * 86400

    # Trend: son b vs ilk b
    if len(windows) >= 2:
        b_first = windows[0]["b_value"]
        b_last = windows[-1]["b_value"]
        b_trend = b_last - b_first
        b_min = min(w["b_value"] for w in windows)
        b_min_idx = min(range(len(windows)), key=lambda i: windows[i]["b_value"])
    else:
        b_trend = 0
        b_min = 0
        b_min_idx = 0

    return {
        "windows": windows,
        "b_first": round(b_first, 4) if windows else None,
        "b_last": round(b_last, 4) if windows else None,
        "b_trend": round(b_trend, 4),
        "b_min": round(b_min, 4),
        "b_min_index": b_min_idx,
    }


if __name__ == "__main__":
    import json
    print(f"Toplam segment: {len(FAULT_SEGMENTS)}")
    for s in FAULT_SEGMENTS:
        print(f"  {s['name_tr']}: Mmax={s['max_magnitude']}, son={s['last_rupture']}, risk={s['risk_factor']}")
    print(f"\nTarihsel deprem: {len(HISTORICAL_EARTHQUAKES)}")
