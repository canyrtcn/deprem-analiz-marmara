"""Kaynaklar-arasi olay eslestirme (duplicate birlestirme).

Problem: AFAD/Sismik, KOERI ve yerel DB ayni fiziksel depremi farkli
`event_id` ile bildirir (or. sayisal id vs `koeri_...`). Kimlik
eslesmesi yetmez; zaman + konum + buyukluk birlikte degerlendirilir.

Zaman varsayimi: karsilastirma epoch'lar uzerinden yapilir;
kaynak-saat politikalari db.to_epoch arkasinda tanimlidir (B3).

Iki AYRI eslesme duzlemi (karistirilmaz):
1. KIMLIK duzlemi: ayni guclu kaynak kimligi (sismik_id) + |dt|<=1saat
   + konum tutarliligi (<=50km). Ayri indekste, zaman penceresinden
   bagimsiz degerlendirilir.
2. GOZLEM duzlemi: zaman+konum+buyukluk birlikte aranir. Esikler:
   - ayni kurum: 30sn / 5km / 0.4 (ayni ag/islem: origin farki
     saniyeler mertebesindedir).
   - farkli kurum: 90sn / 15km / 0.7 (ag/islem gecikmesi payi).

VETO: iki kayitta FARKLI guclu kimlik varsa ASLA birlesmez.
Zincirleme onleme: yeni kayit olayin TUM uyeleriyle tam-baglantili
olmali. Determinizm: girdi (epoch, source, event_id) ile kanonik
siralanir.

Esikler (gerekceli, muhafazakar):
- ayni-kurum dar pencere: dakika-aralikli GERCEK farkli depremler
  (ozellikle ayni agin artci dizileri) birlesmez.
- kurumlar-arasi genis pencere: farkli lokasyon/origin sacilmasi payi.
Uc kosul BIRLIKTE saglanmazsa birlestirme YOK (belirsizde ayri).
Koordinat/zaman/buyuklukten biri eksikse eslesme denenmez.

Cikti olaylar: temsilci koordinat/zaman/buyukluk (medyan) + tum
kaynak olcumleri `members` icinde korunur (kayip yok).

BILIMSEL NOT (B4): temsilci buyukluk, farkli olceklerin (ML/Mw/MD)
MEDYANIDIR; olcek-oncelikli (Mw>ML>MD) secim bilimsel olarak daha
temiz olurdu ancak davranis degisikligi + keyfi varsayim yasagi
nedeniyle medyan korunmustur. Olcek-karisik kataloglarda temsilci,
fiziksel olcum degil olculer-arasi uzlasidir; analizler bu
belirsizlikle yorumlanmalidir. members icindeki ozgun olcumler
etiketlidir ve kayipsizdir.
"""
import math

# Gozlem-duzlemi esikleri
SAME_SRC_DT = 30.0
SAME_SRC_KM = 5.0
SAME_SRC_DM = 0.4
X_SRC_DT = 90.0
X_SRC_KM = 15.0
X_SRC_DM = 0.7
# Kimlik-duzlemi
ID_DT = 3600.0
ID_KM = 50.0
# Geriye uyumluluk adlari
DT_S = X_SRC_DT
DIST_KM = X_SRC_KM
DMAG = X_SRC_DM

SRC_PRIORITY = {"sismik": 0, "koeri": 1, "uygulama": 2}

# Kurum normalizasyonu: KOERI = Kandilli Rasathanesi'nin deprem
# gozlem servisi; ayni kurumun iki kanaldan gelisi bagimsiz olcum degil.
INSTITUTIONS = {"koeri": "kandilli", "kandilli": "kandilli",
                "afad": "afad", "emsc": "emsc", "noa": "noa"}


# Kanal -> kurum varsayimi (kaynak alani bossa doldurulur).
CHANNEL_INSTITUTION = {"sismik": "sismik", "koeri": "kandilli",
                       "uygulama": "uygulama"}


def institution_of(q):
    return INSTITUTIONS.get(str(q.get("source") or "").lower(),
                            str(q.get("source") or "?").lower() or "?")


def strong_id(q):
    """Guclu kaynak kimligi (toplayici/kurum olay no). Yoksa None."""
    for k in ("sismik_id", "koeri_id", "afad_id", "event_code"):
        v = q.get(k)
        if v is not None and str(v).strip() != "":
            return f"{k}:{str(v).strip()}"
    return None


_EPOCH_CACHE = {}
_EPOCH_CACHE_LIMIT = 20000
_EPOCH_MISS = object()


def to_epoch(q):
    """Kayit -> epoch sn (yoksa None). Saat dilimi kaynaga gore.

    Once occurred_at + kaynak kuraliyla hesaplar; yoksa kayitli
    timestamp alanina duser. DB'ye yazmaz, yalnizca karsilastirma icindir.
    Sonuclar kayit-imzaya gore onbelleklenir (saf fonksiyon; ayni girdi
    ayni cikti — v1.0.5.2 performans iyilestirmesi, davranis ayni).
    """
    try:
        key = (str(q.get("source") or ""), str(q.get("event_id") or ""),
               str(q.get("occurred_at") or ""), str(q.get("timestamp") or ""))
        hit = _EPOCH_CACHE.get(key, _EPOCH_MISS)
        if hit is not _EPOCH_MISS:
            return hit
    except Exception:
        key = None
    val = _to_epoch_uncached(q)
    try:
        if key is not None:
            if len(_EPOCH_CACHE) >= _EPOCH_CACHE_LIMIT:
                _EPOCH_CACHE.clear()
            _EPOCH_CACHE[key] = val
    except Exception:
        pass
    return val


def _to_epoch_uncached(q):
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


def _coords(q):
    try:
        la = float(q.get("latitude"))
        lo = float(q.get("longitude"))
        return la, lo
    except (TypeError, ValueError):
        return None


def _id_match(a, b):
    """Kimlik duzlemi: ayni guclu kimlik + zaman + konum tutarliligi."""
    sa, sb = strong_id(a), strong_id(b)
    if not sa or not sb or sa != sb:
        return False
    ta, tb = to_epoch(a), to_epoch(b)
    if ta is None or tb is None or abs(ta - tb) > ID_DT:
        return False
    ca, cb = _coords(a), _coords(b)
    if ca is None or cb is None:
        return False
    try:
        if haversine_km(ca[0], ca[1], cb[0], cb[1]) > ID_KM:
            return False
    except (TypeError, ValueError):
        return False
    return True


def _id_conflict(a, b):
    """Iki kayitta FARKLI guclu kimlik var mi? (veto)."""
    sa, sb = strong_id(a), strong_id(b)
    return bool(sa and sb and sa != sb)


def _obs_match(a, b):
    """Gozlem duzlemi: esikler + kurum kurali. Veto dahili."""
    if _id_conflict(a, b):
        return False
    ta, tb = to_epoch(a), to_epoch(b)
    ma, mb = _mag(a), _mag(b)
    ca, cb = _coords(a), _coords(b)
    if ta is None or tb is None or ma is None or mb is None:
        return False
    if ca is None or cb is None:
        return False
    same_inst = institution_of(a) == institution_of(b)
    if same_inst:
        dt, km, dm = SAME_SRC_DT, SAME_SRC_KM, SAME_SRC_DM
    else:
        dt, km, dm = X_SRC_DT, X_SRC_KM, X_SRC_DM
    try:
        if abs(ta - tb) > dt:
            return False
        if haversine_km(ca[0], ca[1], cb[0], cb[1]) > km:
            return False
        if abs(ma - mb) > dm:
            return False
    except (TypeError, ValueError):
        return False
    return True


def is_same_event(a, b, dt_s=X_SRC_DT, km=X_SRC_KM, dmag=X_SRC_DM):
    """Iki kayit ayni fiziksel deprem mi?

    Uyumluluk sarmalayici: once kimlik duzlemi, sonra gozlem duzlemi.
    Parametreler yalnizca gozlem-duzlemi kurum-disi esiklerini ezer
    (ozel testler icin); varsayilan davranis sabitlere uyar.
    """
    if _id_conflict(a, b):
        return False
    if _id_match(a, b):
        return True
    ta, tb = to_epoch(a), to_epoch(b)
    ma, mb = _mag(a), _mag(b)
    ca, cb = _coords(a), _coords(b)
    if ta is None or tb is None or ma is None or mb is None:
        return False
    if ca is None or cb is None:
        return False
    same_inst = institution_of(a) == institution_of(b)
    if same_inst:
        dt, kk, dm = SAME_SRC_DT, SAME_SRC_KM, SAME_SRC_DM
    else:
        dt, kk, dm = dt_s, km, dmag
    try:
        if abs(ta - tb) > dt:
            return False
        if haversine_km(ca[0], ca[1], cb[0], cb[1]) > kk:
            return False
        if abs(ma - mb) > dm:
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


def _canon_key(q):
    try:
        t = to_epoch(q)
    except Exception:
        t = None
    return (t if t is not None else 0,
            str(q.get("source") or ""),
            str(q.get("event_id") or ""))


def _fits_event(q, members):
    """Kayit olayin TUM uyeleriyle eslesiyor mu? (tam baglanti).

    Once kimlik duzlemi (tek uye yeterli), sonra gozlem duzlemi
    (tum uyeler gerekli). Veto her duzeyde gecerli.
    """
    for m in members:
        if _id_conflict(q, m):
            return False
    for m in members:
        if _id_match(q, m):
            return True
    for m in members:
        if not _obs_match(q, m):
            return False
    return True


def dedupe_records(records):
    """[kayit] -> [olay]. Her olay: temsilci + members (kayipsiz).

    Kanonik sira + tam-baglanti yerlestirme: deterministik, zincirleme
    birlesme yok. Guclu kimlikler ayri indekste izlenir.
    """
    events = []  # {"members": [...]}
    id_index = {}  # strong_id -> event
    try:
        records = sorted(records or [], key=_canon_key)
    except Exception:
        records = list(records or [])
    for q in records:
        tq = to_epoch(q)
        placed = False
        sid = strong_id(q)
        if sid and sid in id_index:
            ev = id_index[sid]
            if _fits_event(q, ev["members"]):
                ev["members"].append(q)
                placed = True
        if not placed:
            for ev in reversed(events):
                try:
                    te = to_epoch(ev["members"][-1])
                except Exception:
                    te = None
                # Kimliksiz kisa-pencere budamasi: kimlikli kayitlar
                # her zaman degerlendirilir (indeks disindaki olaylar).
                if (tq is not None and te is not None
                        and te < tq - X_SRC_DT and not sid):
                    break
                if _fits_event(q, ev["members"]):
                    ev["members"].append(q)
                    if sid:
                        id_index[sid] = ev
                    placed = True
                    break
        if not placed:
            ev = {"members": [q]}
            events.append(ev)
            if sid:
                id_index[sid] = ev
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
                q["source"] = CHANNEL_INSTITUTION.get(src, src)
            if "_channel" not in q:
                q = dict(q)
                q["_channel"] = src
            recs.append(q)
    recs.sort(key=_canon_key)
    return dedupe_records(recs)


def representatives(events):
    """Analiz girisi: olay basina tek temsilci (cift sayim yok)."""
    return [dict(e) for e in events or [] if e.get("members")]
