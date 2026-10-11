"""Kaynaklar-arasi olay eslestirme (duplicate birlestirme).

Problem: AFAD/Sismik, KOERI ve yerel DB ayni fiziksel depremi farkli
`event_id` ile bildirir (or. sayisal id vs `koeri_...`). Kimlik
eslesmesi yetmez; zaman + konum + buyukluk birlikte degerlendirilir.

Zaman varsayimi: tum kaynaklar Turkiye duvar saatini yazar
(KOERI listesi yerel saat; Sismik API `YYYY-MM-DD HH:MM:SS` duvar
saati). Karsilastirma ayni varsayimla parse edilen epoch'lar
uzerinden yapilir; mutlak UTC dogrulugu degil, kaynaklar-arasi
tutarlilik aranir.

Esikler (gerekceli, muhafazakar):
- |dt| <= 90sn: ayni depremin kurumlar-arasi origin farki saniyeler
  mertebesindedir; artci dizilerdeki dakika-aralikli GERCEK farkli
  depremler birlesmez.
- uzaklik <= 15km: aglar-arasi lokasyon sacilmasi (ozellikle Buyuk
  Marmara disi zayif kapsama) icin guvenli ust sinir.
- |dmag| <= 0.7: olcek farki (ML/Mw) + yuvarlama payi.
Uc kosul BIRLIKTE saglanmazsa birlestirme YOK (belirsizde ayri).
Koordinat/zaman/buyuklukten biri eksikse eslesme denenmez.

Cikti olaylar: temsilci koordinat/zaman/buyukluk (medyan) + tum
kaynak olcumleri `members` icinde korunur (kayip yok).
"""
import math

DT_S = 90.0
DIST_KM = 15.0
DMAG = 0.7

SRC_PRIORITY = {"sismik": 0, "koeri": 1, "uygulama": 2}

# Kurum normalizasyonu: KOERI = Kandilli Rasathanesi'nin deprem
# gozlem servisi; ayni kurumun iki kanaldan gelisi bagimsiz olcum degil.
INSTITUTIONS = {"koeri": "kandilli", "kandilli": "kandilli",
                "afad": "afad", "emsc": "emsc", "noa": "noa"}


def institution_of(q):
    return INSTITUTIONS.get(str(q.get("source") or "").lower(),
                            str(q.get("source") or "?").lower() or "?")


def to_epoch(q):
    """Kayit -> epoch sn (yoksa None). Saat dilimi kaynaga gore.

    Once occurred_at + kaynak kuraliyla hesaplar (eski satirlarin
    3saatlik donem farkini duzeltir); yoksa kayitli timestamp alanina
    duser. DB'ye yazmaz, yalnizca karsilastirma icindir.
    """
    try:
        from deprem_izleme.db import _parse_occurred_ts
        ts = _parse_occurred_ts(q.get("occurred_at", ""),
                                q.get("source"), q.get("event_id"))
        if ts:
            return ts
    except Exception:
        pass
    ts = q.get("timestamp")
    if ts:
        try:
            return int(ts)
        except (TypeError, ValueError):
            pass
    return None


def haversine_km(la1, lo1, la2, lo2):
    r = 6371.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp = math.radians(la2 - la1)
    dl = math.radians(lo2 - lo1)
    a = (math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2)
         * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _mag(q):
    m = q.get("magnitude")
    try:
        return float(m) if m is not None else None
    except (TypeError, ValueError):
        return None


def is_same_event(a, b, dt_s=DT_S, km=DIST_KM, dmag=DMAG):
    """Iki kayit ayni fiziksel deprem mi? Eksik veri -> False.

    Guclu anahtar: iki kayitta da ayni `sismik_id` (toplayici olay
    kimligi) varsa ve zamanlar 1saatten yakin ise aynidir.
    Yoksa zaman+konum+buyukluk kapilari birlikte aranir.
    """
    sa, sb = a.get("sismik_id"), b.get("sismik_id")
    if sa and sb and sa == sb:
        ta, tb = to_epoch(a), to_epoch(b)
        if ta is not None and tb is not None and abs(ta - tb) <= 3600:
            return True
    ta, tb = to_epoch(a), to_epoch(b)
    ma, mb = _mag(a), _mag(b)
    la, lo = a.get("latitude"), a.get("longitude")
    lb, ob = b.get("latitude"), b.get("longitude")
    if ta is None or tb is None or ma is None or mb is None:
        return False
    if la is None or lo is None or lb is None or ob is None:
        return False
    try:
        if abs(ta - tb) > dt_s:
            return False
        if haversine_km(float(la), float(lo), float(lb), float(ob)) > km:
            return False
        if abs(ma - mb) > dmag:
            return False
    except (TypeError, ValueError):
        return False
    return True


def _event_key(ev):
    """Olay anahtari: zaman + yuvarlanmis koordinat (kaynak bagimsiz)."""
    try:
        ts = int(ev.get("timestamp") or 0)
    except (TypeError, ValueError):
        ts = 0
    try:
        la = round(float(ev.get("latitude") or 0), 3)
        lo = round(float(ev.get("longitude") or 0), 3)
    except (TypeError, ValueError):
        la, lo = 0, 0
    return f"{ts}_{la:.3f}_{lo:.3f}"


def pick_candidates(events, project_fn, x, y, tol=16.0):
    """Tiklama noktasi yakinindaki olaylar (mesafeye gore sirali).

    Saf fonksiyon (test edilebilir): [(mesafe_px, olay)] doner.
    Harita motorundan bagimsizdir (OSM ve canvas ayni kullanir).
    """
    out = []
    for ev in events or []:
        try:
            la = float(ev.get("latitude"))
            lo = float(ev.get("longitude"))
        except (TypeError, ValueError):
            continue
        try:
            px, py = project_fn(lo, la)
        except Exception:
            continue
        d = math.hypot(px - x, py - y)
        if d <= tol:
            out.append((d, ev))
    out.sort(key=lambda t: t[0])
    return out


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def dedupe_records(records):
    """[kayit] -> [olay]. Her olay: temsilci + members (kayipsiz).

    Zaman-sirali tek gecis: adaylar yeniden eskiye taranir, pencere
    disina cikilinca durulur (buyuk kataloglarda hizli).
    """
    events = []
    try:
        records = sorted(records or [], key=lambda q: (to_epoch(q) or 0))
    except Exception:
        records = list(records or [])
    for q in records:
        tq = to_epoch(q)
        placed = False
        for ev in reversed(events):
            te = to_epoch(ev["_rep"])
            if tq is not None and te is not None and te < tq - DT_S:
                break
            if is_same_event(q, ev["_rep"]):
                ev["members"].append(q)
                placed = True
                break
        if not placed:
            events.append({"members": [q], "_rep": dict(q)})
    out = []
    for ev in events:
        ms = ev["members"]
        lats = [m.get("latitude") for m in ms
                if m.get("latitude") is not None]
        lons = [m.get("longitude") for m in ms
                if m.get("longitude") is not None]
        mags = [m for m in (_mag(m) for m in ms) if m is not None]
        tss = [t for t in (to_epoch(m) for m in ms) if t is not None]
        first = sorted(ms, key=lambda m: SRC_PRIORITY.get(
            str(m.get("source") or ""), 9))[0]
        rep = dict(first)
        if lats and lons:
            rep["latitude"] = _median(lats)
            rep["longitude"] = _median(lons)
        if mags:
            rep["magnitude"] = _median(mags)
        rep["members"] = list(ms)
        rep["member_count"] = len(ms)
        rep["member_sources"] = sorted({institution_of(m) for m in ms})
        rep["member_channels"] = sorted({str(m.get("_channel")
                                             or m.get("source") or "?")
                                        for m in ms})
        if tss:
            rep["timestamp"] = int(_median(tss))
        out.append(rep)
    return out


def dedupe_layers(layers):
    """{kaynak: [kayit]} -> [olay] (uyeler kaynak etiketini korur).

    Sozluk anahtari VERI KANALIDIR (uygulama/sismik/koeri); kaydın
    `source` alani sismolojik kurumdur (kandilli/afad/emsc...). Kanal,
    `_channel` olarak ayrica islenir; gorunurluk kanala, gosterim
    kuruma gore yapilir. Ikisi karistirilmaz.
    """
    recs = []
    for src, items in (layers or {}).items():
        for q in items or []:
            if "source" not in q or not q.get("source"):
                q = dict(q)
                q["source"] = src
            if "_channel" not in q:
                q = dict(q)
                q["_channel"] = src
            recs.append(q)
    recs.sort(key=lambda q: (to_epoch(q) or 0))
    return dedupe_records(recs)


def representatives(events):
    """Analiz girisi: olay basina tek temsilci (cift sayim yok)."""
    return [dict(e) for e in events or [] if e.get("members")]
