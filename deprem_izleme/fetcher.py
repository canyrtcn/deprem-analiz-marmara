"""
API Fetcher - Sismik Harita API'sinden deprem verilerini çeker
Marmara Denizi ve İstanbul bounding box filtresi uygular
"""
import requests
import time
import logging
from datetime import datetime, timedelta
from deprem_izleme.config import (
    MARMARA_BBOX, ISTANBUL_BBOX,
    API_LIMIT, DAILY_LIMIT, FETCH_TIMEOUT,
    get_api_endpoint, get_api_key,
)
from deprem_izleme.db import insert_earthquake, bulk_insert_earthquakes, get_db, MAIN_DB, _parse_occurred_ts

logger = logging.getLogger(__name__)

# Basit in-memory request sayacı (günlük limit takibi)
_last_reset = datetime.now().date()
_request_count = 0


def _check_limit():
    global _last_reset, _request_count
    today = datetime.now().date()
    if today != _last_reset:
        _last_reset = today
        _request_count = 0
    # Kalıcı sayaç da kontrol edilir (aksi halde her yeniden başlatmada
    # limit sıfırlanır ve günlük kota aşılır).
    persisted = 0
    try:
        from deprem_izleme.config import load_settings
        s = load_settings()
        if s.get("api_date") == today.isoformat():
            persisted = int(s.get("api_used", 0) or 0)
    except Exception:
        pass
    if max(_request_count, persisted) >= DAILY_LIMIT:
        raise RuntimeError(f"Günlük API limiti aşıldı ({DAILY_LIMIT})")
    _request_count += 1


def _in_bbox(lat, lon):
    """Marmara bounding box içinde mi kontrol et."""
    return (MARMARA_BBOX["min_lat"] <= lat <= MARMARA_BBOX["max_lat"]
            and MARMARA_BBOX["min_lon"] <= lon <= MARMARA_BBOX["max_lon"])


def _region_tag(lat, lon):
    """İstanbul içinde mi, yoksa genel Marmara mı?"""
    if (ISTANBUL_BBOX["min_lat"] <= lat <= ISTANBUL_BBOX["max_lat"]
            and ISTANBUL_BBOX["min_lon"] <= lon <= ISTANBUL_BBOX["max_lon"]):
        return "istanbul"
    return "marmara"


def fetch_earthquakes(days_back=7, min_magnitude=0.0, sources=None):
    """
    Sismik Harita API'sinden depremleri çek.
    İstemci tarafında bounding box filtreleme uygular.
    """
    _check_limit()
    date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    date_to = datetime.now().strftime("%Y-%m-%d")

    params = {
        "date_from": date_from,
        "date_to": date_to,
        "min_magnitude": min_magnitude,
        "limit": API_LIMIT,
        "sources": sources or "kandilli,afad",
    }

    logger.info(f"API isteği: {days_back}g geri, M>={min_magnitude}, limit={API_LIMIT}")
    headers = {"User-Agent": "DepremAnaliz-Marmara/1.0"}
    api_key = get_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.get(
        get_api_endpoint(),
        params=params,
        headers=headers,
        timeout=FETCH_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "success":
        logger.warning(f"API yanıtı başarısız: {data}")
        return []

    earthquakes = data.get("earthquakes", [])
    logger.info(f"API'den {len(earthquakes)} deprem alındı (filtresiz)")

    # Bounding box filtrele
    filtered = []
    for eq in earthquakes:
        lat = eq.get("latitude", 0)
        lon = eq.get("longitude", 0)
        if _in_bbox(lat, lon):
            eq["region_tag"] = _region_tag(lat, lon)
            filtered.append(eq)

    logger.info(f"Marmara bounding box içinde: {len(filtered)} deprem")
    return filtered


def fetch_and_store(days_back=7, min_magnitude=0.0, sources=None):
    """Depremleri çek ve veritabanına kaydet.

    Yan etki: fetch_and_store.truncated — API 1000 limitine takılındıysa
    True (katalog eksik olabilir, istatistikler yanlı olur).
    """
    quakes = fetch_earthquakes(days_back, min_magnitude, sources)
    fetch_and_store.truncated = len(quakes) >= API_LIMIT
    if fetch_and_store.truncated:
        logger.warning(f"API {API_LIMIT} limitine takıldı ({len(quakes)} kayıt) - katalog eksik olabilir.")
    if not quakes:
        logger.info("Kaydedilecek yeni deprem yok.")
        return 0

    # Önce veritabanında son kaydın timestamp'ini al, ondan yenilerini filtrele
    conn = get_db(MAIN_DB)
    last_ts = conn.execute("SELECT MAX(timestamp) FROM earthquakes").fetchone()[0] or 0
    conn.close()

    new_quakes = [q for q in quakes
                  if q.get("occurred_at", "") and
                  _parse_occurred_ts(q["occurred_at"]) > last_ts]

    if not new_quakes:
        logger.info("Yeni deprem yok (hepsi kayıtlı).")
        return 0

    count = bulk_insert_earthquakes(new_quakes)
    logger.info(f"{count} yeni deprem kaydedildi.")
    return count


def fetch_recent_and_store(min_magnitude=1.0):
    """Son 24 saat verisini çek ve ekle - cron için ideal."""
    return fetch_and_store(days_back=1, min_magnitude=min_magnitude)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = fetch_and_store(days_back=7, min_magnitude=0.0)
    print(f"{n} deprem kaydedildi.")
