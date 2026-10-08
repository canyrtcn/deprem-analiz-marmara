"""
Deprem ön-tahmin modülü - Kısa vadeli olasılık tahminleri
"""
import math
import logging
from datetime import datetime, timedelta
from collections import deque

from deprem_izleme.db import get_earthquakes
from deprem_izleme.aggregation import (
    calculate_b_value, seismic_energy_joules, detect_anomalous_activity,
)

logger = logging.getLogger(__name__)


class EarthquakePredictor:
    """
    Kısa vadeli deprem olasılık tahminleyicisi.

    Yöntemler:
    1. Poisson zaman-serisi modeli (kısa vadeli)
    2. Gutenberg-Richter b-değeri trend analizi
    3. Sismik moment birikimi / bölgesel stress modeli
    4. Artçı şok istatistiksel modeli (Reasenberg & Jones)
    5. Anomali tespiti (öncü sismisite)
    """

    def __init__(self, region="marmara"):
        self.region = region

    def predict_short_term(self, days_ahead=7, min_mag_of_interest=4.0):
        """
        Kısa vadeli (1-30 gün) deprem olasılık tahmini.

        Döner: {
            "composite_index": 0-1 arasi boyutsuz gosterge (kalibre edilmemis)
                               veya None (yetersiz veri),
            "poisson_probability": kalibre edilmemis Poisson olasiligi
                                   veya None (yetersiz veri),
            "expected_count": N veya None,
            "max_likely_magnitude": M veya None,
            "risk_trend": "increasing|stable|decreasing",
            "warning_level": "green|yellow|orange|red" veya None (yetersiz veri)
        }
        """
        now = datetime.now()

        # Son 30 günlük veri
        quakes_30d = get_earthquakes(
            since=now - timedelta(days=30),
            region=self.region
        )
        # Son 90 günlük veri (trend)
        quakes_90d = get_earthquakes(
            since=now - timedelta(days=90),
            region=self.region
        )
        # Son 7 gün
        quakes_7d = get_earthquakes(
            since=now - timedelta(days=7),
            region=self.region
        )

        mags_30d = [q["magnitude"] for q in quakes_30d if q.get("magnitude")]
        mags_90d = [q["magnitude"] for q in quakes_90d if q.get("magnitude")]
        mags_7d = [q["magnitude"] for q in quakes_7d if q.get("magnitude")]

        # --- 1. Poisson bileşeni: TEK servis (raporla birebir aynı) ---
        from deprem_izleme.aggregation import forecast_poisson
        fc = forecast_poisson(quakes_30d, threshold=min_mag_of_interest,
                              forecast_days=days_ahead, t_obs_days=30.0,
                              region=self.region)
        p_poisson = fc["p_forecast"]  # None: yetersiz veri
        suff = fc["sufficient"]

        # --- 2. Gutenberg-Richter trend (servis a/b'yi yeniden kullan) ---
        b_30, a_30, mc_30 = fc["b_value"], fc["a_value"], fc["mc"]
        b_90, a_90, mc_90 = calculate_b_value(mags_90d)

        # b-değeri trendi: düşüş = stress artışı
        b_trend = b_30 - b_90 if mags_90d else 0

        # --- 3. Sismik moment birikimi ---
        # Günlük enerji salınım hızı karşılaştırması (gün başına Joule)
        energy_30d = sum(seismic_energy_joules(m) for m in mags_30d)
        energy_90d = sum(seismic_energy_joules(m) for m in mags_90d) if mags_90d else energy_30d

        if energy_90d > 0 and len(mags_90d) > 0:
            # DÜZELTME (önceki sürüm olay başına enerjiyi karşılaştırıyordu):
            # oran, gün başına enerjiden kurulur.
            daily_energy_30 = energy_30d / 30.0
            daily_energy_90 = energy_90d / 90.0
            energy_ratio = daily_energy_30 / max(daily_energy_90, 0.001)
        else:
            energy_ratio = 1.0

        # --- 4. Anomalı skoru ---
        z_score = detect_anomalous_activity(quakes_90d)

        # --- 5. Artçı/öncü model ---
        # Son 7 günde M≥3.0 artış varsa öncü sismisite olabilir
        mags_7d_above_3 = [m for m in mags_7d if m >= 3.0]
        foreshock_ratio = len(mags_7d_above_3) / max(len(mags_7d), 1) if mags_7d else 0

        # --- 6. Birleşik olasılık ---
        # Ağırlıklı bileşenler
        weights = {
            "poisson": 0.30,
            "b_trend": 0.20,
            "energy_ratio": 0.15,
            "z_score": 0.20,
            "foreshock": 0.15,
        }

        # Her bileşeni normalize et (0-1)
        p_poisson = p_poisson if p_poisson is not None else 0.0

        # b trend: -0.2 ve altı = riskli
        b_trend_score = max(0, min(1, (-b_trend * 5)))

        # energy ratio: 2x+ = riskli
        energy_score = max(0, min(1, (energy_ratio - 0.5) / 2.0))

        # z-score normalization
        z_score_norm = max(0, min(1, z_score / 4.0))

        # foreshock ratio
        foreshock_score = max(0, min(1, foreshock_ratio * 3))

        if suff:
            composite_index = (
                weights["poisson"] * p_poisson +
                weights["b_trend"] * b_trend_score +
                weights["energy_ratio"] * energy_score +
                weights["z_score"] * z_score_norm +
                weights["foreshock"] * foreshock_score
            )
        else:
            # Yetersiz veri: uydurma skor yok (None → "— / yetersiz veri")
            composite_index = None

        # Beklenen maksimum magnitüd (yalnızca yeterli veride)
        if suff and b_30 > 0:
            max_likely_mag = max(1.5, min(7.5, a_30 / max(b_30, 0.01)))
        else:
            max_likely_mag = None

        # Trend yönü
        if b_trend < -0.1 and energy_ratio > 1.5:
            trend = "increasing"
        elif b_trend > 0.1 and energy_ratio < 0.8:
            trend = "decreasing"
        else:
            trend = "stable"

        # Uyarı seviyesi (yalnızca yeterli veride; yoksa None)
        if not suff:
            warning = None
        elif composite_index >= 0.65 or z_score >= 4.0:
            warning = "red"
        elif composite_index >= 0.45 or z_score >= 2.5:
            warning = "orange"
        elif composite_index >= 0.25:
            warning = "yellow"
        else:
            warning = "green"

        exp_count = (round(fc["lambda_eff"] * days_ahead, 2)
                     if suff else None)

        return {
            "prediction_window_days": days_ahead,
            "min_magnitude_of_interest": min_mag_of_interest,
            "no_data": len(quakes_30d) < 5,
            "sufficient": suff,
            "sufficiency": fc["sufficiency"],
            "composite_index": (round(composite_index, 4)
                                if composite_index is not None else None),
            "poisson_probability": (round(p_poisson, 4)
                                    if fc["p_forecast"] is not None else None),
            "poisson_source": fc["rate_source"],
            "expected_quake_count": exp_count,
            "max_likely_magnitude": (round(max_likely_mag, 2)
                                     if max_likely_mag is not None else None),
            "trend": trend,
            "warning_level": warning,
            "b_trend": round(b_trend, 4),
            "energy_ratio": round(energy_ratio, 3),
            "anomaly_z_score": round(z_score, 3),
            "foreshock_ratio": round(foreshock_ratio, 4),
            "components": {
                "poisson": (round(p_poisson, 4)
                            if fc["p_forecast"] is not None else None),
                "b_trend_score": round(b_trend_score, 4),
                "energy_score": round(energy_score, 4),
                "z_score": round(z_score_norm, 4),
                "foreshock_score": round(foreshock_score, 4),
            }
        }


def predict_marmara():
    """Marmara için hızlı tahmin."""
    predictor = EarthquakePredictor(region="marmara")
    return predictor.predict_short_term(days_ahead=7, min_mag_of_interest=4.0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pred = predict_marmara()
    for k, v in pred.items():
        print(f"{k}: {v}")
