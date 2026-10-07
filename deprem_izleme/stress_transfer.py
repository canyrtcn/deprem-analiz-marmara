"""
Coulomb Stress Transfer (ΔCFF)
King, Stein & Lin (1994) — Okada (1992) yaklaşımı
Gerçek formüller: Stein vd. (1997), Toda & Stein (2005), Parsons (2004)

ΔCFF = Δτ + μ' * Δσn
  Δτ: kayma stressi değişimi
  Δσn: normal stress değişimi (+ = fayı açar)
  μ': efektif sürtünme katsayısı (0.4 varsayılan)
"""
import math
import logging
import numpy as np
from deprem_izleme.fault_segments import FAULT_SEGMENTS, point_to_segment_distance

logger = logging.getLogger(__name__)

MU_PRIME = 0.4      # Efektif sürtünme (Stein vd. 1997)
SHEAR_MOD = 32e9    # Shear modulus (Pa)
POISSON = 0.25      # Poisson oranı
LAME1 = 32e9        # Lamé λ (≈ μ)


def coulomb_stress(sxx, syy, szz, sxy, sxz, syz,
                    strike, dip, rake, mu_prime=MU_PRIME):
    """
    Stress tensörünü alıcı fay düzlemine yansıtıp ΔCFF hesaplar.

    Formül: ΔCFF = Δτ + μ' * Δσn

    Parametreler:
        sxx..syz: stress tensörü bileşenleri (Pa)
        strike, dip, rake: alıcı fay parametreleri (derece)
        mu_prime: efektif sürtünme katsayısı

    Dönüş: (delta_cff, delta_shear, delta_normal) — bar cinsinden
    """
    rad = math.pi / 180.0
    st, di, ra = strike * rad, dip * rad, rake * rad

    cos_st = math.cos(st); sin_st = math.sin(st)
    cos_di = math.cos(di); sin_di = math.sin(di)
    cos_ra = math.cos(ra); sin_ra = math.sin(ra)

    # Fay normal vektörü (n)
    nx = -sin_di * sin_st
    ny =  sin_di * cos_st
    nz = -cos_di

    # Kayma yönü vektörü (s)
    sx = cos_di * cos_st * cos_ra - sin_st * sin_ra
    sy = cos_di * sin_st * cos_ra + cos_st * sin_ra
    sz = sin_di * cos_ra

    # Stress tensör matrisi
    stress = np.array([
        [sxx, sxy, sxz],
        [sxy, syy, syz],
        [sxz, syz, szz]
    ])

    n = np.array([nx, ny, nz])
    s = np.array([sx, sy, sz])

    # Normal gerilme: σn = n·σ·n^T
    sn = np.dot(n, np.dot(stress, n))

    # Kayma gerilmesi: τ = s·σ·n^T
    tau = np.dot(s, np.dot(stress, n))

    # Coulomb gerilim değişimi (Pa → bar: / 1e5)
    dcff_pa = tau + mu_prime * sn
    dcff_bar = dcff_pa / 1e5
    tau_bar = tau / 1e5
    sn_bar = sn / 1e5

    return dcff_bar, tau_bar, sn_bar


def moment_magnitude_to_moment(mw):
    """Sismik moment (Nm): M0 = 10^(1.5 * Mw + 9.1)"""
    return 10 ** (1.5 * mw + 9.1)


def magnitude_to_slip(mw, area_km2=100):
    """
    Slip miktarı (m) — Wells & Coppersmith (1994)
    M0 = μ * A * D
    D = M0 / (μ * A)
    """
    M0 = moment_magnitude_to_moment(mw)
    area_m2 = area_km2 * 1e6
    return M0 / (SHEAR_MOD * area_m2)


def magnitude_to_rupture_length(mw):
    """
    Kırık uzunluğu (km) — Wells & Coppersmith (1994)
    Strike-slip: log10(L) = 0.74 * Mw - 3.55
    """
    return 10 ** (0.74 * mw - 3.55)


def magnitude_to_rupture_width(mw):
    """
    Kırık genişliği (km) — Wells & Coppersmith (1994)
    Strike-slip: log10(W) = 0.28 * Mw - 0.74
    """
    return 10 ** (0.28 * mw - 0.74)


def okada_simplified_stress(magnitude, lat, lon, depth_km,
                              obs_lat, obs_lon, obs_depth_km,
                              strike=90, dip=90, rake=0):
    """
    Basitleştirilmiş Okada yaklaşımı ile stress tensörü.

    Tam Okada (1992) çözümü ~70 sayfa formül içerir.
    Bu fonksiyon, nokta kaynak + uzak alan Green fonksiyonu
    yaklaşımı kullanır. Yakın alan (< rupture_length) için
    OkadaPy veya cutde kütüphanesi önerilir.

    Döner: (sxx, syy, szz, sxy, sxz, syz) — Pa
    """
    # Mesafe (km)
    from math import cos, radians, sqrt
    dlat = (obs_lat - lat) * 111.32
    dlon = (obs_lon - lon) * 111.32 * cos(radians((lat + obs_lat) / 2))
    dz = obs_depth_km - depth_km

    r_km = sqrt(dlat**2 + dlon**2 + dz**2)
    if r_km < 1:
        r_km = 1

    # Sismik moment
    M0 = moment_magnitude_to_moment(magnitude)

    # Uzak alan stress tensörü (basitleştirilmiş)
    # Gerçek Okada çözümünde Green fonksiyonları çok daha karmaşık
    C = 3 * M0 / (4 * math.pi * (r_km * 1000)**3)

    # Yön kosinüsleri
    cos_theta = dz / r_km if r_km > 0 else 0
    sin_theta = sqrt(1 - cos_theta**2) if abs(cos_theta) <= 1 else 0
    cos_phi = dlon / (r_km * sin_theta + 1e-10)
    sin_phi = dlat / (r_km * sin_theta + 1e-10)

    # Nokta kaynak radyasyon paterni (basit)
    # Daha doğru için moment tensörü + Green fonk. gerekir
    rad = math.pi / 180.0
    strike_r = strike * rad
    rake_r = rake * rad

    sxx = C * (sin_phi * cos_phi * math.sin(2 * strike_r) * math.cos(rake_r))
    syy = C * (-sin_phi * cos_phi * math.sin(2 * strike_r) * math.cos(rake_r))
    szz = C * 0.3 * (sin_phi * cos_phi * math.sin(rake_r))
    sxy = C * (cos_phi**2 * math.cos(strike_r) * math.cos(rake_r))
    sxz = C * (sin_theta * cos_theta * sin_phi * math.cos(rake_r))
    syz = C * (sin_theta * cos_theta * cos_phi * math.cos(rake_r))

    return sxx, syy, szz, sxy, sxz, syz


def compute_segment_cff(earthquakes):
    """
    Son depremlerin her fay segmentinde yarattığı
    Coulomb stress değişimini hesapla.

    Döner: [{segment_adı, stress_bar, status, ...}]
    """
    if not earthquakes:
        return []

    results = []
    for seg in FAULT_SEGMENTS:
        total_cff = 0.0
        nearby_events = []
        # Segment orta noktası
        mid_idx = len(seg["coords"]) // 2
        seg_lat = seg["coords"][mid_idx][0]
        seg_lon = seg["coords"][mid_idx][1]

        # Segment strike (yaklaşık)
        if len(seg["coords"]) >= 2:
            dx = seg["coords"][-1][1] - seg["coords"][0][1]
            dy = seg["coords"][-1][0] - seg["coords"][0][0]
            strike = math.degrees(math.atan2(dx, dy)) % 360
        else:
            strike = 90

        for eq in earthquakes:
            eq_mag = eq.get("magnitude", 0) or 0
            if eq_mag < 2.5:
                continue

            eq_lat = eq.get("latitude", 0)
            eq_lon = eq.get("longitude", 0)
            eq_depth = eq.get("depth_km", 10) or 10

            dist = point_to_segment_distance(eq_lat, eq_lon, seg["coords"])
            if dist > 80:
                continue

            # Basitleştirilmiş stress hesabı
            sxx, syy, szz, sxy, sxz, syz = okada_simplified_stress(
                eq_mag, eq_lat, eq_lon, eq_depth,
                seg_lat, seg_lon, 8.0,
                strike=strike, dip=85, rake=0
            )

            dcff_bar, tau_bar, sn_bar = coulomb_stress(
                sxx, syy, szz, sxy, sxz, syz,
                strike=strike, dip=85, rake=0
            )

            total_cff += dcff_bar
            nearby_events.append({
                "mag": eq_mag,
                "dist_km": round(dist, 1),
                "dcff_bar": round(dcff_bar, 6),
            })

        # Threshold: 0.1 bar önemli eşik
        locked_status = seg.get("locked_status", "transitional")
        if locked_status == "locked":
            total_cff *= 1.3
        elif locked_status == "recently_ruptured":
            total_cff *= 0.5

        results.append({
            "name": seg["name_tr"],
            "name_en": seg["name"],
            "stress_bars": round(total_cff, 6),
            "status": locked_status,
            "events": len(nearby_events),
            "threshold_exceeded": total_cff >= 0.1,
        })

    return results


def get_total_stress_transfer(earthquakes):
    """Toplam stress transferi raporu."""
    seg_stress = compute_segment_cff(earthquakes)
    if not seg_stress:
        return 0, [], None

    total = sum(s["stress_bars"] for s in seg_stress)
    max_seg = max(seg_stress, key=lambda x: x["stress_bars"])
    return round(total, 6), seg_stress, max_seg


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_eqs = [
        {"latitude": 40.85, "longitude": 28.15, "magnitude": 5.8, "depth_km": 12},
        {"latitude": 40.82, "longitude": 28.05, "magnitude": 6.2, "depth_km": 11},
    ]
    stress, segs, mx = get_total_stress_transfer(test_eqs)
    print(f"Toplam stress: {stress:.6f} bar")
    for s in segs:
        flag = "⚠️" if s.get("threshold_exceeded") else "✅"
        print(f"  {flag} {s['name']}: {s['stress_bars']:.6f} bar [{s['status']}]")
