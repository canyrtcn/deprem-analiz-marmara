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
from deprem_izleme.aggregation import select_canonical, legacy_magnitude

logger = logging.getLogger(__name__)

KOERI_URL = "http://www.koeri.boun.edu.tr/scripts/lst0.asp"

# Tasima katmani DOGRULANMAMIS (duz HTTP). Bu etiket olayin sahte oldugu
# anlamina GELMEZ; yalnizca ag uzerinde mudahale ihtimaline karsi
# kaynagin tek basina otorite sayilmamasini soyler (SEC-08/K1).
TRANSPORT_VERIFIED = False

# Bilinen revizyon belirtecleri (KOERI son sutun). Liste disi -> "unknown";
# belirsiz durum ASLA revize sayilmaz.
_REVISION_TOKENS = {"ILKSEL": "preliminary", "REVIZE": "revised"}


def _norm_token(tok):
    try:
        return tok.strip().upper().replace("İ", "I")
    except Exception:
        return ""


def _split_revision(tail):
    """Yer-metin + revizyon belirtecini ayir.

    Doner: (yer, revizyon). Yalnizca bilinen belirtec kirpilir;
    bilinmeyen kuyruk yer metninde birakilir, revizyon "unknown" olur.
    """
    try:
        parts = (tail or "").rstrip().rsplit(None, 1)
    except Exception:
        return tail, "unknown"
    if len(parts) == 2 and _norm_token(parts[1]) in _REVISION_TOKENS:
        return parts[0], _REVISION_TOKENS[_norm_token(parts[1])]
    return tail, "unknown"


def _in_bbox(lat, lon):
    return (MARMARA_BBOX["min_lat"] <= lat <= MARMARA_BBOX["max_lat"]
            and MARMARA_BBOX["min_lon"] <= lon <= MARMARA_BBOX["max_lon"])


def _region_tag(lat, lon):
    if (ISTANBUL_BBOX["min_lat"] <= lat <= ISTANBUL_BBOX["max_lat"]
            and ISTANBUL_BBOX["min_lon"] <= lon <= ISTANBUL_BBOX["max_lon"]):
        return "istanbul"
    return "marmara"


def _try_parse(line):
    """Satir ayristirma + gerekce (K1 tani).

    Doner: (kayit|None, gerekce). Gerekceler: "ok", "ok-ilksel",
    "ok-revize", "ok-revizyon-bilinmiyor", "bos", "tarih-yok",
    "kisa-satir", "koordinat-yok/hatali", "aralik-disi",
    "beklenmedik-hata".
    """
    try:
        if not line or not line.strip():
            return None, "bos"
        if line.strip().startswith("-"):
            return None, "bos"
        if not re.match(r'\d{4}\.\d{2}\.\d{2}', line):
            return None, "tarih-yok"
        if len(line) < 68:
            return None, "kisa-satir"

        tarih = line[0:10].strip()
        saat = line[11:19].strip()
        enlem = line[21:29].strip()
        boylam = line[30:38].strip()
        derinlik = line[41:52].strip()

        md_raw = line[53:58].strip()
        ml_raw = line[58:63].strip()
        mw_raw = line[63:68].strip()

        yer_ham = line[68:].strip()

        if not enlem or not boylam:
            return None, "koordinat-yok"

        try:
            lat = float(enlem)
            lon = float(boylam)
        except ValueError:
            return None, "koordinat-hatali"
        try:
            depth = float(derinlik) if derinlik and derinlik != "-.-" else 0.0
        except ValueError:
            return None, "derinlik-hatali"

        def parse_mag(s):
            s = s.strip().replace("*", "")
            try:
                return float(s) if s and s != "-.-" else None
            except ValueError:
                return None

        ml = parse_mag(ml_raw)
        md = parse_mag(md_raw)
        mw = parse_mag(mw_raw)
        # Uretim alani: eski davranis birebir korunur (K2 kural 7).
        mag = legacy_magnitude(ml, mw, md)
        # Kanonik model (bellek-ici; DB'ye yazilmaz): tur + kaynak + revizyon
        # korunur; tum turler eksikse value None (0.0 degil).
        canon = select_canonical(ml, mw, md, source="koeri",
                                 inferred=False)
        mag_missing = bool(canon.get("missing", False))

        # Fiziksel olabilirlik (bozuk satir elenir; supheli ama mumkun
        # degerler bayrakla gecer, sessizce mesrulastirilmaz).
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return None, "aralik-disi-koordinat"
        if not (0.0 <= depth <= 700.0):
            return None, "aralik-disi-derinlik"
        if not (-2.0 <= mag <= 10.5):
            return None, "aralik-disi-buyukluk"

        yer, revision = _split_revision(yer_ham)
        occurred = f"{tarih.replace('.', '-')} {saat}"
        # Aynı saniyede iki deprem çakışmasın diye koordinat da id'ye girer
        event_id = (f"koeri_{tarih.replace('.','')}_{saat.replace(':','')}"
                    f"_{enlem.replace('.','')}_{boylam.replace('.','')}")
        # Deterministik id (Python hash() her çalışta değişir - kullanma)
        det_id = int(hashlib.md5(event_id.encode()).hexdigest()[:8], 16) % (10**9)

        rec = {
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
            # K1 etiketleri (henuz DB'ye kalici yazilmiyor; bkz. K3):
            "transport_verified": TRANSPORT_VERIFIED,
            "revision": revision,
            "magnitude_missing": mag_missing,
            # K2 kanonik model (bellek-ici; DB'ye yazilmaz):
            "magnitude_canonical": canon.get("value"),
            "mag_type": canon.get("type"),
            "mag_inferred": False,
        }
        reason = {"preliminary": "ok-ilksel", "revised": "ok-revize"}.get(
            revision, "ok-revizyon-bilinmiyor")
        return rec, reason
    except Exception:
        return None, "beklenmedik-hata"


def parse_koeri_line(line):
    """KOERI sabit-kolon formatını parse et (geriye uyumlu sarmalayici).

    Format:
    Tarih      Saat      Enlem(N)  Boylam(E) Derinlik(km)  MD   ML   Mw    Yer
    2026.06.22 03:06:14  39.4470   25.8643        8.6      -.-  2.6  -.-   YERADI
    Doner: kayit sozlugu veya None. Yeni K1 etiketleri
    (transport_verified/revision/magnitude_missing) kayitta tasinir ancak
    henuz DB'ye kalici yazilmaz (K3'e kadar yalnizca bellek-ici tani).
    """
    rec, _reason = _try_parse(line)
    return rec


def fetch_koeri():
    """KOERI sayfasından son depremleri çek.

    Doner: {"quakes": [...], "ok": bool, "error": str|None}.
    Ag/parse basarisizliginda BOS katalog [] ile karistirilmamasi icin
    ok=False doner; cagiran bunu "kaynak erisilemedi" diye gosterir.
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
                eq["raw_line"] = line
                eq["raw_status"] = "present"
                earthquakes.append(eq)

        logger.info(f"KOERI: {len(earthquakes)} Marmara depremi bulundu.")
        return {"quakes": earthquakes, "ok": True, "error": None}
    except Exception as e:
        try:
            from deprem_izleme.errors import redact
            msg = redact(str(e)).split("\n")[0][:160]
        except Exception:
            msg = "baglanti hatasi"
        logger.error(f"KOERI çekilemedi: {msg}")
        return {"quakes": [], "ok": False, "error": msg}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = fetch_koeri()
    if not res["ok"]:
        print(f"KOERI erisilemedi: {res['error']}")
    for q in res["quakes"][:10]:
        occ = q.get("occurred_at", "?")
        print(f"M{q['magnitude']:.1f} {occ} {q['location']}")
