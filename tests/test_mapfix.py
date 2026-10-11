"""Tasimabilirlik oneki (otomatik eklendi): TESTTMP sentetik dizin, REPO_ROOT repo koku."""
import os as _os
TESTTMP = _os.environ.get("DEPREM_TESTTMP") or _os.getcwd()
REPO_ROOT = (_os.environ.get("DEPREM_REPO_ROOT")
             or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
"""Harita/duplicate duzeltmeleri regresyon bataryasi (sentetik, headless).

Kapsam: dedup eslestirme, zaman/kaynak ayrimi, isabet-testi siralama,
projeksiyon gidis-donus + surukleme tutarliligi, deniz halkasi
gecerliligi ve kontrol noktalari, canli yenileme nesil disiplini,
buyuk katalog performansi.
"""
import math
import os
import sys
import time
os.environ["DEPREM_SKIP_DB_INIT"] = "1"
sys.path.insert(0, TESTTMP)
import db_guard
db_guard.install()
sys.path.insert(0, REPO_ROOT)

ok = []
def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))

from deprem_izleme.dedup import (
    dedupe_layers, dedupe_records, is_same_event, haversine_km, to_epoch,
    pick_candidates, _event_key)
from deprem_izleme.osm_map import (_mag_color, ESRI_LIGHT, ESRI_DARK,
                                    CITY_LABELS, MAX_MARKERS,
                                    is_placeholder_tile, purge_retired_tile_cache,
                                    PLACEHOLDER_MD5)

T0 = 1788000000


def Q(src, eid, ts, la, lo, mag, utc=None, **kw):
    """ts: gercek an (epoch). utc bos ise kaynaga gore: API kanallari UTC
    duvar saatiyle yazar (Sismik API davranisi), KOERI yerel yazar."""
    from datetime import datetime as _dt
    if utc is None:
        utc = str(src or "").lower() != "koeri"
    wall = ts if not utc else ts - 10800
    d = {"source": src, "event_id": eid, "timestamp": ts,
         "occurred_at": _dt.fromtimestamp(wall).strftime("%Y-%m-%d %H:%M:%S"),
         "latitude": la, "longitude": lo, "magnitude": mag}
    d.update(kw)
    return d


# 1. ayni deprem farkli kimliklerle birlesir
a = Q("sismik", "123", T0, 40.70, 28.50, 2.3)
b = Q("koeri", "koeri_x", T0 + 20, 40.705, 28.505, 2.1,
      magnitude_ml=2.1, mag_type="ML")
evs = dedupe_records([a, b])
check("D1: ayni deprem tek olay", len(evs) == 1 and evs[0]["member_count"] == 2,
      len(evs))
check("D1: uyeler korunur",
      {m["event_id"] for m in evs[0]["members"]} == {"123", "koeri_x"})
check("D1: kurumlar etikette (normalize)",
      set(evs[0]["member_sources"]) == {"sismik", "kandilli"})

# 2. gercekten farkli yakin depremler ayri kalir
c = Q("sismik", "124", T0 + 300, 40.71, 28.51, 2.4)   # 5dk sonra
d = Q("sismik", "125", T0, 40.90, 28.90, 2.4)          # ~40km otede
e = Q("sismik", "126", T0 + 10, 40.701, 28.501, 4.5)   # buyukluk farki
evs2 = dedupe_records([a, c, d, e])
check("D2: yakin-farkli depremler birlesmez", len(evs2) == 4, len(evs2))
check("D2: zaman kapisi", is_same_event(a, c) is False)
check("D2: uzaklik kapisi", is_same_event(a, d) is False)
check("D2: buyukluk kapisi", is_same_event(a, e) is False)
# artci siniri: 200sn arayla ayni konum/buyukluk ayri olay kalir
a1 = Q("sismik", "a1", T0, 40.70, 28.50, 3.0)
a2 = Q("sismik", "a2", T0 + 200, 40.701, 28.501, 3.1)
check("D2: artci (200sn) birlesmez", is_same_event(a1, a2) is False)
# ayni depremin tipik kurum farki (<30sn) birlesir
a3 = Q("koeri", "a3", T0 + 25, 40.702, 28.503, 2.9)
check("D2: kurum farki (25sn) birlesir", is_same_event(a1, a3) is True)

# 3. eksik veride otomatik birlesme yok
f = Q("koeri", "k2", T0 + 5, None, 28.50, 2.3)
g = Q("sismik", "124", T0, 40.70, 28.50, None)
check("D3: eksik koordinat birlesmez", is_same_event(a, f) is False)
check("D3: eksik buyukluk birlesmez", is_same_event(a, g) is False)

# 4. katman birlestirme + sayim ayrimi
layers = {"uygulama": [a, c], "sismik": [dict(a, event_id="999")],
          "koeri": [b]}
evs3 = dedupe_layers(layers)
n_raw = sum(len(v) for v in layers.values())
check("D4: 4 kayit 2 olaya iner", len(evs3) == 2 and n_raw == 4,
      f"{n_raw}->{len(evs3)}")

# 5. isabet testi: siralama + tolerans
ev1 = {"latitude": 40.70, "longitude": 28.50, "magnitude": 2.0}
ev2 = {"latitude": 40.71, "longitude": 28.51, "magnitude": 3.0}
proj = lambda lo, la: (lo * 100.0, la * 100.0)
cands = pick_candidates([ev1, ev2], proj, 2850.0, 4070.0, tol=16.0)
check("D5: en yakin once", len(cands) == 2 and cands[0][1] is ev1,
      [round(c[0], 1) for c in cands])
cands0 = pick_candidates([ev1, ev2], proj, 0.0, 0.0, tol=16.0)
check("D5: tolerans disi bos", cands0 == [])
check("D5: anahtar kararli", _event_key(ev1) == _event_key(dict(ev1)))

# 6. OSM motoru: buyukluk-renk, fay sirasi, tile/atif politikasi
from deprem_izleme.fault_segments import FAULT_SEGMENTS
check("D6: renk olcegi", _mag_color(5.5) == "#C084FC" and _mag_color(4.2) == "#F87171"
      and _mag_color(3.1) == "#FBBF24" and _mag_color(2.0) == "#FB9236"
      and _mag_color(1.0) == "#34D399" and _mag_color(None) == "#34D399")
_bad_seg = [s.get("name", "?") for s in FAULT_SEGMENTS
            if not s.get("coords") or len(s["coords"]) < 2
            or any(not (39.0 <= la <= 42.5 and 25.5 <= lo <= 31.5)
                   for la, lo in s["coords"])]
check("D6: fay koordinat sirasi (lat,lon) Marmara kutusunda", not _bad_seg,
      _bad_seg[:3])
check("D6: tile URL sablonlari (Esri anahtarsiz altlik)", "{z}/{y}/{x}" in ESRI_LIGHT
      and "arcgisonline" in ESRI_LIGHT and "{z}/{y}/{x}" in ESRI_DARK,
      ESRI_LIGHT[:60])
check("D6: sehir etiketleri az ve kutuda",
      3 <= len(CITY_LABELS) <= 6 and all(
          39.5 <= la <= 41.5 and 26.5 <= lo <= 30.5 for _, la, lo in CITY_LABELS),
      len(CITY_LABELS))
# IPGP dogrulanmis geometri
from deprem_izleme.fault_ipgp import IPGP_PATHS, IPGP_EXTRA, IPGP_SOURCE, IPGP_N_TOTAL
from deprem_izleme.fault_segments import _seg_paths, get_nearest_fault as _gnf
_n_ipgp = sum(len(v) for v in IPGP_PATHS.values())
check("D6: IPGP parca sayisi", _n_ipgp >= 200, _n_ipgp)
check("D6: IPGP butunlugu (350/350 kayipsiz)", _n_ipgp + len(IPGP_EXTRA) == IPGP_N_TOTAL == 350,
      f"{_n_ipgp}+{len(IPGP_EXTRA)}")
check("D6: IPGP kaynagi", "Armijo" in IPGP_SOURCE, IPGP_SOURCE)
_ipgp_named = [s for s in FAULT_SEGMENTS if s.get("trace_source") == IPGP_SOURCE]
check("D6: IPGP atamali segmentler", len(_ipgp_named) >= 6, len(_ipgp_named))
check("D6: parcalar ayri (yapay birlestirme yok)",
      all(isinstance(s.get("paths"), list) and len(s["paths"]) >= 1
          for s in _ipgp_named))
_sematik = sorted(s["name"] for s in FAULT_SEGMENTS
                  if (s.get("trace_source") or "") == "şematik")
check("D6: sematik kalanlar kara segmentleri", _sematik == ["Ganos", "Guney_Kol"],
      _sematik)
_s, _d = _gnf(40.72, 29.28)  # Yalova acigi: cizilen geometriye yakinlik
check("D6: yakin fay cizilen geometriden", _s is not None and _d < 15.0,
      f"{_s['name'] if _s else None} {_d:.1f}")
import inspect as _insp
from deprem_izleme import osm_map as _OM
_src = _insp.getsource(_OM)
check("D6: gorunur atif", "Esri" in _src)
# yer-tutucu tanima + secici purge (sentetik; ag yok)
import io as _io
from PIL import Image as _PILImage
_flat = _io.BytesIO()
_PILImage.new("RGB", (256, 256), (170, 170, 168)).save(_flat, format="PNG")
check("D6: duz deniz karosu bayrak yemez", not is_placeholder_tile(_flat.getvalue()))
_fake = _PILImage.new("RGB", (256, 256), (204, 204, 204))
from PIL import ImageDraw as _IDD
_d = _IDD.Draw(_fake)
_d.rectangle([60, 100, 196, 156], fill=(60, 60, 60))
_fb = _io.BytesIO()
_fake.save(_fb, format="PNG")
check("D6: yazi-icerikli gri yer-tutucu yakalanir", is_placeholder_tile(_fb.getvalue()))
check("D6: bilinen yer-tutucu parmak izi kayitli",
      "f27d9de7f80c13501f470595e327aa6d" in PLACEHOLDER_MD5)
import sqlite3 as _sq, tempfile as _tf, os as _os
_pdb = _os.path.join(_tf.mkdtemp(), "t.db")
_c = _sq.connect(_pdb)
_c.execute("CREATE TABLE tiles (zoom INTEGER, x INTEGER, y INTEGER, server VARCHAR(300), tile_image BLOB, PRIMARY KEY (zoom,x,y,server))")
_c.execute("INSERT INTO tiles VALUES (11,1,1,'https://x/World_Physical_Map/a',?)", (b"v",))
_c.execute("INSERT INTO tiles VALUES (12,2,2,'https://y/World_Light_Gray_Base/a',?)", (b"v",))
_c.commit()
_c.close()
_n = purge_retired_tile_cache(_pdb)
_left = _sq.connect(_pdb).execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
check("D6: purge yalnizca emekli servisi siler", _n == 1 and _left == 1, f"{_n}/{_left}")
check("D6: purge olmayan dosyada cokusuz", purge_retired_tile_cache(
    _os.path.join(_tf.mkdtemp(), "yok.db")) == 0)
check("D6: onbellek data/ altinda", "osm_tiles.db" in _src)
check("D6: marker ust siniri", isinstance(MAX_MARKERS, int) and MAX_MARKERS >= 1000,
      MAX_MARKERS)

# 7. OSM altligi: gercek koordinatlar dogrudan motora verilir (ozel
# halka/poligon uretimi yok). Eski ozel motor testleri kaldirildi:
# halka/poligon validasyonu OSM servis verisine tasindi.
import deprem_izleme.marmara_canvas as _MC  # geriye uyumluluk importu
check("D7: eski motor modulu yuklenir (olu kod, cizimde kullanilmaz)",
      hasattr(_MC, "MarmaraMap"))

# 8. canli yenileme nesil disiplini (basliksiz GUI stub)
from unittest import mock
from types import SimpleNamespace
import deprem_izleme.gui as _G
ns = SimpleNamespace(map_cache={"sismik": [], "koeri": []}, map_days=7,
                     _map_live_gen=0, map_status=mock.Mock(),
                     embedded_map=mock.Mock())
posted = []
ns._post_ui = lambda fn: posted.append(fn)
with mock.patch("deprem_izleme.fetcher.fetch_earthquakes",
                return_value=[{"latitude": 40.7, "longitude": 28.5,
                               "magnitude": 1.0, "timestamp": T0,
                               "occurred_at": "2026-09-01 10:00:00"}]), \
     mock.patch("deprem_izleme.fetcher_koeri.fetch_koeri",
                return_value={"quakes": [], "ok": False, "error": "ag yok"}):
    _G.DepremGUI._map_live_worker(ns)
check("D8: istekte nesil artar", ns._map_live_gen == 1, ns._map_live_gen)
check("D8: basarili kaynak yazilir",
      len(ns.map_cache["sismik"]) == 1, len(ns.map_cache["sismik"]))
check("D8: basarisiz kaynak eskiyi silmez", ns.map_cache["koeri"] == [])
ns._map_live_gen = 99  # daha yeni istek geldi (gonderilen gen=1 bayat)
ns._apply_map_live = lambda ok, errs, gen=None: _G.DepremGUI._apply_map_live(
    ns, ok, errs, gen)
for fn in posted:
    fn()
check("D8: eski sonuc uygulanmaz",
      ns.embedded_map.set_events.call_count == 0,
      ns.embedded_map.set_events.call_count)

# 9. buyuk katalog performansi
big = []
for i in range(2000):
    big.append(Q("sismik", f"s{i}", T0 - (i % 30) * 86400,
                 40.3 + (i % 80) * 0.01, 27.0 + (i % 300) * 0.01,
                 1.0 + (i % 40) * 0.1))
t0 = time.perf_counter()
evs_big = dedupe_layers({"uygulama": big})
dt = time.perf_counter() - t0
check("D9: 2000 kayit < 5sn", dt < 5.0, f"{dt:.2f}sn/{len(evs_big)} olay")

# 10. Yalova M3.5 vakasi: API UTC vs KOERI yerel ayni an (3sa farkli duvar)
# Ayni fiziksel deprem tek olay; kurumlar tekil gosterilir.
from deprem_izleme.dedup import institution_of
api_rec = {"source": "kandilli", "event_id": "sis001",
           "occurred_at": "2026-10-10 19:08:49", "timestamp": 1791642529,
           "latitude": 40.6980, "longitude": 29.2563, "magnitude": 3.5,
           "magnitude_ml": 3.5, "sismik_id": "S99-TR2610-A01",
           "sources": [{"name": "kandilli", "magnitude": 3.5}],
           "quality": "Revize"}
koeri_rec = {"source": "koeri", "event_id": "koeri_20261010_220849",
             "occurred_at": "2026-10-10 22:08:49", "timestamp": 1791642529,
             "latitude": 40.6797, "longitude": 29.2567, "magnitude": 3.5,
             "magnitude_ml": 3.5, "mag_type": "ML"}
check("D10: UTC/TR ayni an esitlenir",
      to_epoch(api_rec) == to_epoch(koeri_rec),  # ikisi de gercek ani verir
      (to_epoch(api_rec), to_epoch(koeri_rec)))
evs10 = dedupe_records([api_rec, koeri_rec])
check("D10: M3.5 teki olay", len(evs10) == 1 and evs10[0]["member_count"] == 2,
      len(evs10))
check("D10: kurum tekil (koeri=kandilli)",
      evs10[0]["member_sources"] == ["kandilli"],
      evs10[0]["member_sources"])
check("D10: olcumler kayipsiz",
      {m["event_id"] for m in evs10[0]["members"]} == {"sis001", "koeri_20261010_220849"})
check("D10: institution norm", institution_of(koeri_rec) == "kandilli"
      and institution_of(api_rec) == "kandilli")
# sismik_id guclu anahtar
api_rec2 = dict(api_rec, event_id="farkli-id", latitude=40.70, longitude=29.26,
                magnitude=3.6)
check("D10: sismik_id eslesir", is_same_event(api_rec, api_rec2) is True)
api_rec3 = dict(api_rec, sismik_id="BASKA-ID")
check("D10: farkli sismik_id ama fizik tutarsa birlesir",
      is_same_event(api_rec3, koeri_rec) is True)  # zaman/konum yine tutar
# revizyon: ayni kimlik, guncel olcum satiri gunceller
import tempfile as _tf
import deprem_izleme.fetcher as F
_tdb = _os.path.join(TESTTMP, "rev_v1.db")
for _s in ("", "-wal", "-shm", "-journal"):
    if _os.path.exists(_tdb + _s):
        _os.remove(_tdb + _s)
import deprem_izleme.db as _DB9
_old_main = _DB9.MAIN_DB
_DBM9 = _DB9
_DBM9.MAIN_DB = _tdb
try:
    _DB9.init_main_db()
    _DB9.insert_earthquake(dict(api_rec, magnitude=3.2), db_path=_tdb)
    with mock.patch.object(F, "fetch_earthquakes", return_value=[api_rec]):
        from deprem_izleme.fetcher import fetch_and_store as _fas
        n = _fas(days_back=1, db_path=_tdb)
    _row = _DB9.get_db(_tdb).execute(
        "SELECT magnitude FROM earthquakes WHERE event_id='sis001'").fetchone()
    check("D10: revizyon satiri gunceller", n >= 1 and abs(_row[0] - 3.5) < 1e-9,
          (_row[0] if _row else None, n))
finally:
    _DBM9.MAIN_DB = _old_main

print()
print("SONUC:", "TUMU PASS" if all(ok) else f"{ok.count(False)} FAIL")
sys.exit(0 if all(ok) else 1)
