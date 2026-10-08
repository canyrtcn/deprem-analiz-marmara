"""
KOERI (Kandilli) veri kaynağı çekici
http://www.koeri.boun.edu.tr/scripts/lst0.asp
"""
import re
import hashlib
import logging
import requests
from datetime import datetime, timedelta
from deprem_izleme.config import MARMARA_BBOX, ISTANBUL_BBOX, KOERI_TIMEOUT

logger = logging.getLogger(__name__)

KOERI_URL = "http://www.koeri.boun.edu.tr/scripts/lst0.asp"


def _in_bbox(lat, lon):
    return (MARMARA_BBOX["min_lat"] <= lat <= MARMARA_BBOX["max_lat"]
            and MARMARA_BBOX["min_lon"] <= lon <= MARMARA_BBOX["max_lon"])


def _region_tag(lat, lon):
    if (ISTANBUL_BBOX["min_lat"] <= lat <= ISTANBUL_BBOX["max_lat"]
            and ISTANBUL_BBOX["min_lon"] <= lon <= ISTANBUL_BBOX["max_lon"]):
        return "istanbul"
    return "marmara"


def parse_koeri_line(line):
    """
    KOERI sabit-kolon formatını parse et.
    Format:
    Tarih      Saat      Enlem(N)  Boylam(E) Derinlik(km)  MD   ML   Mw    Yer
    2026.06.22 03:06:14  39.4470   25.8643        8.6      -.-  2.6  -.-   YERADI
    """
    if not line or line.strip().startswith("-") or not line.strip():
        return None
    if not re.match(r'\d{4}\.\d{2}\.\d{2}', line):
        return None

    try:
        tarih = line[0:10].strip()
        saat = line[11:19].strip()
        enlem = line[21:29].strip()
        boylam = line[30:38].strip()
        derinlik = line[41:52].strip()

        md_raw = line[53:58].strip()
        ml_raw = line[58:63].strip()
        mw_raw = line[63:68].strip()

        yer = line[68:].strip()

        # Temizle
        if not enlem or not boylam:
            return None

        lat = float(enlem)
        lon = float(boylam)
        depth = float(derinlik) if derinlik and derinlik != "-.-" else 0.0

        def parse_mag(s):
            s = s.strip().replace("*", "")
            try:
                return float(s) if s and s != "-.-" else None
            except:
                return None

        ml = parse_mag(ml_raw)
        md = parse_mag(md_raw)
        mw = parse_mag(mw_raw)
        mag = ml or mw or md or 0.0

        occurred = f"{tarih.replace('.', '-')} {saat}"
        # Aynı saniyede iki deprem çakışmasın diye koordinat da id'ye girer
        event_id = (f"koeri_{tarih.replace('.','')}_{saat.replace(':','')}"
                    f"_{enlem.replace('.','')}_{boylam.replace('.','')}")
        # Deterministik id (Python hash() her çalışta değişir - kullanma)
        det_id = int(hashlib.md5(event_id.encode()).hexdigest()[:8], 16) % (10**9)

        return {
            "id": det_id,
            "event_id": event_id,
            "occurred_at": occurred,
            "latitude": lat,
            "longitude": lon,
            "depth_km": depth,
            "magnitude": mag,
            "magnitude_ml": ml,
            "magnitude_mw": mw,
            "magnitude_md": md,
            "location": yer[:60],
            "source": "koeri",
        }
    except (ValueError, IndexError):
        return None


def fetch_koeri():
    """
    KOERI sayfasından son depremleri çek.
    """
    try:
        resp = requests.get(KOERI_URL, timeout=KOERI_TIMEOUT,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        # KOERI charset bildirmez; requests ISO-8859-1 varsayar ve Türkçe
        # karakterler bozulur. Önce UTF-8 dene, olmazsa ISO-8859-9.
        try:
            text = resp.content.decode("utf-8")
        except UnicodeDecodeError:
            text = resp.content.decode("iso-8859-9", errors="replace")

        earthquakes = []
        for line in text.splitlines():
            eq = parse_koeri_line(line)
            if eq and _in_bbox(eq["latitude"], eq["longitude"]):
                eq["region_tag"] = _region_tag(eq["latitude"], eq["longitude"])
                earthquakes.append(eq)

        logger.info(f"KOERI: {len(earthquakes)} Marmara depremi bulundu.")
        return earthquakes
    except Exception as e:
        logger.error(f"KOERI çekilemedi: {e}")
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    quakes = fetch_koeri()
    for q in quakes[:10]:
        occ = q.get("occurred_at", "?")
        print(f"M{q['magnitude']:.1f} {occ} {q['location']}")
