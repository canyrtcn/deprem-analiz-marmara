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
    validate_api_base, ApiConfigError, load_settings, is_dev_mode,
)


class FetchRedirectError(ValueError):
    """API yonlendirmesi izlenmedi (token korunumu). Mesaji Guvenlidir."""
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


def build_api_request(base=None, api_key=None, params=None):
    """Merkezi istek kurucu (SEC-01): GUI testi + fetch ayni kapidan gecer.

    - URL validate_api_base ile dogrulanir (https/allowlist/port/userinfo).
    - Authorization yalnizca dogrulanmis default/onayli hosta eklenir;
      local-dev yolunda anahtar ASLA eklenmez.
    - Doner: {"url", "headers", "params", "host_kind", "key_attached"}.
    - Guvensiz yapi ApiConfigError yukseltir (mesaji anahtar icermez).
    """
    try:
        s = load_settings()
    except Exception:
        s = {}
    if not isinstance(s, dict):
        s = {}
    if base is None:
        base = s.get("api_base")
    approved = s.get("approved_hosts")
    url, kind = validate_api_base(base, approved,
                                  dev_enabled=is_dev_mode(s))
    headers = {"User-Agent": "DepremAnaliz-Marmara/1.0"}
    attach = bool(api_key) and kind != "local-dev"
    if attach:
        headers["Authorization"] = f"Bearer {api_key}"
    return {"url": url, "headers": headers, "params": dict(params or {}),
            "host_kind": kind, "key_attached": attach}


def probe_api(base, key):
    """Baglanti testi (GUI ile ayni merkezi mantik).

    Doner: (basarili: bool, mesaj: str). Mesaj anahtar icermez.
    """
    try:
        req = build_api_request(base=base, api_key=key, params={"limit": 1})
    except ApiConfigError as e:
        return False, f"Yapılandırma reddedildi: {e}"
    try:
        resp = requests.get(req["url"], params=req["params"],
                            headers=req["headers"], timeout=FETCH_TIMEOUT,
                            allow_redirects=False)
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            return False, "Sunucu yönlendirme döndürdü; izlenmedi (güvenlik)."
        resp.raise_for_status()
        n = resp.json().get("count", "?")
        anon = "" if req["key_attached"] else " (anahtarsız istek)"
        return True, f"Bağlantı OK (örnek kayıt: {n}){anon}"
    except Exception as e:
        try:
            from deprem_izleme.errors import redact
            msg = redact(str(e))
        except Exception:
            msg = "bağlantı hatası"
        return False, f"Hata: {msg}"


def _annotate_magnitudes(eq):
    """API kaydi icin K2 kanonik etiketleri (bellek-ici; DB'ye yazilmaz).

    Kural (K2 sart 3): tepe `magnitude` alani yakinliktan otomatik ML
    sayilmaz -> mag_type="unknown" (inferred). Ancak acik beyanli
    magnitude_ml/mw/md alanlari varsa kanonik secim onlardan yapilir
    (inferred=False) ve deger ayni cikar; belirsizlik kalmaz.
    is_primary yalnizca gosterge sayilir, kanit degil (K2 sart 6).
    """
    try:
        from deprem_izleme.aggregation import select_canonical
    except Exception:
        return eq
    try:
        ml = eq.get("magnitude_ml")
        mw = eq.get("magnitude_mw")
        md = eq.get("magnitude_md")
        declared = (ml is not None) or (mw is not None) or (md is not None)
        if declared:
            canon = select_canonical(ml, mw, md,
                                     source=str(eq.get("source") or "api"),
                                     inferred=False)
        else:
            top = eq.get("magnitude")
            canon = {"value": (float(top) if top is not None else None),
                     "type": "unknown" if top is not None else None,
                     "source": str(eq.get("source") or "api"),
                     "inferred": True,
                     "missing": top is None}
        eq["magnitude_canonical"] = canon.get("value")
        eq["mag_type"] = canon.get("type")
        eq["mag_inferred"] = bool(canon.get("inferred", True))
    except Exception:
        pass
    return eq


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
    try:
        req = build_api_request(api_key=get_api_key(), params=params)
    except ApiConfigError as e:
        # Guvensiz yapilandirma BOS katalog [] gibi DONMEZ: cagiran
        # bos-veri ile baglanti-hatasini ayirt edebilsin diye yukseltir.
        logger.error(f"API yapılandırması reddedildi: {e}")
        raise
    resp = requests.get(
        req["url"],
        params=req["params"],
        headers=req["headers"],
        timeout=FETCH_TIMEOUT,
        allow_redirects=False,
    )
    if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
        logger.error("API yönlendirmesi izlenmedi (token korunumu); "
                     "doğrudan https adres kullanın.")
        raise FetchRedirectError(
            "Sunucu yönlendirme döndürdü; token korunumu için izlenmedi. "
            "Doğrudan https API adresi kullanın.")
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "success":
        logger.warning(f"API yanıtı başarısız: {data}")
        return []

    earthquakes = data.get("earthquakes", [])
    # HAM sayi: bbox filtresinden ONCEki API yaniti (truncate tespiti
    # icin sart; filtre sonrasi sayi yaniltir).
    fetch_earthquakes.last_raw_count = len(earthquakes)
    logger.info(f"API'den {len(earthquakes)} deprem alındı (filtresiz)")

    # Bounding box filtrele
    filtered = []
    for eq in earthquakes:
        lat = eq.get("latitude", 0)
        lon = eq.get("longitude", 0)
        if _in_bbox(lat, lon):
            eq["region_tag"] = _region_tag(lat, lon)
            _annotate_magnitudes(eq)
            filtered.append(eq)

    logger.info(f"Marmara bounding box içinde: {len(filtered)} deprem")
    return filtered


def fetch_and_store(days_back=7, min_magnitude=0.0, sources=None, db_path=None):
    """Depremleri çek ve veritabanına kaydet.

    Yan etki: fetch_and_store.truncated — API 1000 limitine takılındıysa
    True (katalog eksik olabilir, istatistikler yanlı olur).
    """
    quakes = fetch_earthquakes(days_back, min_magnitude, sources)
    _raw = getattr(fetch_earthquakes, "last_raw_count", len(quakes))
    if not isinstance(_raw, int):
        _raw = len(quakes)  # yamali/test cagrilarinda ham sayi yoksa filtreli sayi
    fetch_and_store.truncated = _raw >= API_LIMIT
    if fetch_and_store.truncated:
        logger.warning(f"API {API_LIMIT} limitine takıldı (ham yanıt {_raw} kayıt) - katalog eksik olabilir.")
    if not quakes:
        logger.info("Kaydedilecek yeni deprem yok.")
        return 0

    # Yinelenenleri event_id ile ele (zaman damgasına göre değil: geç
    # yayınlanan eski depremler de kaçırılmamalı; tarih formatı ne olursa
    # olsun tüm tablo taranır.
    _mpath = db_path or MAIN_DB
    conn = get_db(_mpath)
    try:
        from deprem_izleme.db import _is_v2_conn as _isv2
        _v2mode = _isv2(conn)
        if _v2mode:
            existing = {r[0] for r in
                        conn.execute("SELECT source || '|' || source_event_id FROM observations").fetchall() if r[0]}
        else:
            existing = {r[0] for r in
                        conn.execute("SELECT event_id FROM earthquakes").fetchall() if r[0]}
    finally:
        conn.close()

    def _dkey(q):
        if _v2mode:
            return f"{q.get('source') or 'unknown'}|{q.get('event_id') or ''}"
        return q.get("event_id")

    def _v2hash(q):
        try:
            from deprem_izleme.db import content_hash_v1, _obs_measurements
            _m = _obs_measurements(q)
            return content_hash_v1(
                q.get("occurred_at", ""), q.get("latitude"), q.get("longitude"),
                q.get("depth_km"), _m["ml"], _m["mw"], _m["md"], _m["revision"])
        except Exception:
            return None

    seen = set()
    new_quakes = []
    cur_hashes = {}
    if _v2mode:
        try:
            from deprem_izleme.db import get_db as _gdb2
            _cc = _gdb2(_mpath)
            try:
                cur_hashes = {
                    r[0]: r[1] for r in _cc.execute(
                        "SELECT o.source || '|' || o.source_event_id, v.fetched_hash"
                        " FROM observations o JOIN observation_versions v"
                        " ON v.version_id = o.current_version_id").fetchall()}
            finally:
                _cc.close()
        except Exception:
            cur_hashes = {}
    for q in quakes:
        eid = q.get("event_id")
        if not eid or not q.get("occurred_at", ""):
            continue
        key = _dkey(q)
        if key in seen:
            continue
        if key in existing:
            # v2: icerik degismisse revizyon olarak gecir (yeni surum uretir)
            if _v2mode and _v2hash(q) != cur_hashes.get(key):
                seen.add(key)
                new_quakes.append(q)
            continue
        seen.add(key)
        new_quakes.append(q)

    if not new_quakes:
        logger.info("Yeni deprem yok (hepsi kayıtlı).")
        return 0

    count = bulk_insert_earthquakes(new_quakes, db_path=_mpath)
    logger.info(f"{count} yeni deprem kaydedildi.")
    return count


def fetch_recent_and_store(min_magnitude=1.0):
    """Son 24 saat verisini çek ve ekle - cron için ideal."""
    return fetch_and_store(days_back=1, min_magnitude=min_magnitude)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = fetch_and_store(days_back=7, min_magnitude=0.0)
    print(f"{n} deprem kaydedildi.")
