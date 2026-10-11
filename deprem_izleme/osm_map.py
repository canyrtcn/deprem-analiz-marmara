"""OSM tabanli harita bileseni (TkinterMapView + CustomTkinter).

MarmaraMap ile ayni dis arayuzu sunar (set_events, set_layer_visible,
set_faults_visible, layer_count, total_count, unique_count, fit);
ic projeksiyon/pan/zoom TkinterMapView tarafindan yonetilir.

- Altlik: aydinlik temada Esri Physical, karanlik temada Esri Dark Gray.
- Karolar data/osm_tiles.db'de onbelleklenir (cevrimdisi gosterebilir).
- Gorunur atif: Esri + veri saglayicilar (kullanim politikasi geregi).
- Ag yoksa cokmez; durum geri-bildirimi status_cb ile verilir.
"""
import os
import threading
import time

import customtkinter as ctk

try:
    from tkintermapview import TkinterMapView
except Exception:  # pragma: no cover
    TkinterMapView = None

from deprem_izleme.dedup import dedupe_layers

# Esri anahtarsiz altliklar (nitelik sarti: atif gorunur).
# Isik: Light Gray Canvas (z13'e kadar gercek veri, etiketsiz; ince beyaz
#   yol cizgileri olabilir). World Physical z11+ 'veri yok' dondurdugu ve
#   2028'de emekliye ayrildigi icin birakildi.
# Koyu: Dark Gray Canvas (z13 dogrulandi; etiketsiz sayilir).
# Sablon sirasi Esri duzenindedir: /tile/{z}/{y}/{x}.
ESRI_LIGHT = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
              "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}")
ESRI_DARK = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
             "Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}")
TILE_ATTRIB = "Harita: © Esri, HERE, Garmin, OpenStreetMap"
# Bilinen 'veri yok' yer-tutucu karo parmak izleri (ham bayt MD5).
# Fiziksel kanit: World_Physical z11/z13 bu baytlari dondurdu.
PLACEHOLDER_MD5 = frozenset({
    "f27d9de7f80c13501f470595e327aa6d",
})

RETIRED_TILE_SERVERS = (
    "World_Physical_Map",
)


def is_placeholder_tile(raw):
    """'Map data not yet available' yer-tutucusu mu? HTTP 200 tek basina yetmez."""
    try:
        import hashlib
        if hashlib.md5(raw).hexdigest() in PLACEHOLDER_MD5:
            return True
    except Exception:
        pass
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(raw)).convert("RGB").resize((32, 32))
        px = list(img.getdata())
        n = len(px)
        if not n:
            return False
        # acik-tema yer-tutucu: (204,204,204) zeminde koyu yazi
        dom = max(set(px), key=px.count)
        if 195 <= dom[0] <= 215 and dom[1] == dom[2] and abs(dom[0] - dom[1]) <= 6:
            dark = sum(1 for c in px if c[0] < 120 and c[1] < 120 and c[2] < 120)
            if dark / n > 0.005:
                return True
    except Exception:
        pass
    return False


def purge_retired_tile_cache(db_path):
    """Emekli/hatali karo girdilerini secici temizle. Donus: silinen satir."""
    import hashlib
    import sqlite3
    removed = 0
    try:
        if not db_path or not os.path.exists(db_path):
            return 0
        con = sqlite3.connect(db_path)
        try:
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "tiles" not in tables:
                return 0
            for (srv,) in list(con.execute("SELECT DISTINCT server FROM tiles")):
                if any(k in (srv or "") for k in RETIRED_TILE_SERVERS):
                    cur = con.execute("DELETE FROM tiles WHERE server=?", (srv,))
                    removed += cur.rowcount
            for (z, x, y, srv, blob) in list(con.execute(
                    "SELECT zoom,x,y,server,tile_image FROM tiles")):
                try:
                    if hashlib.md5(bytes(blob)).hexdigest() in PLACEHOLDER_MD5:
                        con.execute(
                            "DELETE FROM tiles WHERE zoom=? AND x=? AND y=? AND server=?",
                            (z, x, y, srv))
                        removed += 1
                except Exception:
                    pass
            con.commit()
        finally:
            con.close()
    except Exception:
        pass
    return removed

# Kendi sehir etiketlerimiz (altlik etiketsiz oldugu icin; az ve kucuk).
CITY_LABELS = [
    ("İstanbul", 41.01, 28.98),
    ("İzmit", 40.77, 29.93),
    ("Yalova", 40.65, 29.27),
    ("Tekirdağ", 40.98, 27.51),
    ("Bursa", 40.19, 29.06),
]

CENTER = (40.75, 28.45)  # (lat, lon)
DEFAULT_ZOOM = 8
MAX_MARKERS = 2000

_NODATA_CACHE = {}


def _nodata_icon(light):
    key = "acik" if light else "koyu"
    if key not in _NODATA_CACHE:
        try:
            from PIL import Image, ImageTk
            col = (232, 232, 230, 255) if light else (31, 41, 55, 255)
            _NODATA_CACHE[key] = ImageTk.PhotoImage(Image.new("RGBA", (256, 256), col))
        except Exception:
            return None
    return _NODATA_CACHE[key]


_CITY_ICON_CACHE = {}


def _city_icon():
    if "dot" not in _CITY_ICON_CACHE:
        try:
            from PIL import Image, ImageTk
            img = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
            from PIL import ImageDraw
            ImageDraw.Draw(img).ellipse([10, 10, 14, 14], fill=(110, 110, 110, 255))
            _CITY_ICON_CACHE["dot"] = ImageTk.PhotoImage(img)
        except Exception:
            return None
    return _CITY_ICON_CACHE["dot"]


_ICON_CACHE = {}


def _circle_icon(color, radius):
    """Büyüklük-sınıfı daire ikonu (Pillow, 4x SSAA, merkezli).

    Beyaz kontrast çerçeveli; tıklama alanı dairenin kendisidir.
    """
    key = (color, radius)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    try:
        from PIL import Image, ImageDraw, ImageTk
        S = 4
        r = max(3, int(radius))
        size = (r * 2 + 6) * S
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        m = 3 * S
        dr.ellipse([m, m, size - m, size - m], fill=color,
                   outline="white", width=max(2, S // 2))
        img = img.resize((size // S, size // S), Image.LANCZOS)
        icon = ImageTk.PhotoImage(img)
        _ICON_CACHE[key] = icon
        return icon
    except Exception:
        return None


def _mag_radius(mag):
    try:
        m = float(mag)
    except (TypeError, ValueError):
        m = 0.0
    return int(6 + max(0.0, m) * 2.2)


def _mag_color(mag):
    try:
        mag = float(mag)
    except (TypeError, ValueError):
        return "#34D399"
    if mag >= 5.0:
        return "#C084FC"
    if mag >= 4.0:
        return "#F87171"
    if mag >= 3.0:
        return "#FBBF24"
    if mag >= 2.0:
        return "#FB9236"
    return "#34D399"


def _event_key(ev):
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


class OsmMap(ctk.CTkFrame):
    """Harita sayfasina gomulen OSM bileseni."""

    def __init__(self, master, on_quake=None, on_fault=None, data_dir=None,
                 status_cb=None, **kw):
        super().__init__(master, **kw)
        self.on_quake = on_quake
        self.on_fault = on_fault
        self._status_cb = status_cb
        self._events = []
        self._visible = {}
        self._faults_visible = True
        self._selected = None
        self._markers = {}  # event_key -> marker
        self._paths = []
        self._light = False
        # Karo isitici: kutuphane is-parcaciklarinda PhotoImage uretimi
        # Windows'ta takilabiliyor; ham bayt indirilir, PhotoImage ana
        # thread'de uretilir. _tile_gen sunucu degisiminde eskir.
        self._tile_gen = 0
        self._tile_pending = []
        self._tile_noinfo = []  # yer-tutucu/eksik karo anahtarlari
        self._tile_warming = False
        self._online = None

        db_path = None
        try:
            if data_dir:
                os.makedirs(data_dir, exist_ok=True)
                db_path = os.path.join(data_dir, "osm_tiles.db")
        except Exception:
            db_path = None
        if TkinterMapView is None:
            raise RuntimeError("tkintermapview kurulu degil")
        self.map = TkinterMapView(self, database_path=db_path,
                                  use_database_only=False)
        try:
            # emekli servis + hata karosu girdilerini secici temizle
            purge_retired_tile_cache(db_path)
        except Exception:
            pass
        self.map.pack(fill="both", expand=True)
        self.map.set_position(*CENTER)
        self.map.set_zoom(DEFAULT_ZOOM)
        try:
            self.map.canvas.bind("<ButtonRelease-1>",
                                 lambda e: self.after(400, self._warm_tiles),
                                 add="+")
            for _seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                try:
                    self.map.canvas.bind(
                        _seq, lambda e: self.after(600, self._warm_tiles),
                        add="+")
                except Exception:
                    pass
        except Exception:
            pass
        # NOT: ilk kurulumda widget henuz 1x1 px olabilir -> karo dizisi bos
        # kalir ve sonraki boyut degisimleri (draw_move) bos diziyi doldurmaz.
        # Yerlesim oturduktan sonra konumu yeniden uygula (gercek boyutla).
        try:
            self.after(300, self._initial_tiles)
        except Exception:
            pass
        try:
            from deprem_izleme.config import load_settings
            _light = (load_settings().get("appearance") or "dark") == "light"
        except Exception:
            _light = False
        self.apply_theme(_light)
        self._attr = ctk.CTkLabel(
            self, text=TILE_ATTRIB,
            font=ctk.CTkFont(size=9), text_color=("gray60", "gray50"))
        self._attr.place(relx=1.0, rely=1.0, anchor="se", x=-6, y=-4)
        self._conn = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=9),
                                  text_color=("gray60", "gray50"))
        self._conn.place(relx=0.0, rely=1.0, anchor="sw", x=6, y=-4)
        self._probe_connection()

    def _initial_tiles(self):
        try:
            if not getattr(self.map, "canvas_tile_array", None):
                self.map.set_position(*CENTER)
        except Exception:
            pass
        self._warm_tiles()

    def _warm_tiles(self):
        """Gorunur karo eksiklerini ana-thread guvencesiyle kapat.

        B5: Tkinter durumuna (canvas_tile_array, zoom, cache) YALNIZCA
        ana thread dokunur. Worker'a salt-veri snapshot (pos listesi)
        verilir; sonuclar thread-safe kuyruk (_tile_pending) ile doner;
        PhotoImage uretimi ana thread'dedir (_warm_tick).
        """
        try:
            arr = getattr(self.map, "canvas_tile_array", None) or []
            zoom = round(self.map.zoom)
            server = self.map.tile_server
            # Ana thread snapshot'i: eksik karo anahtarlari (tekil).
            want = []
            seen = set()
            for col in arr:
                for ct in list(col or []):
                    try:
                        pos = ct.tile_name_position
                        k = f"{zoom}{pos[0]}{pos[1]}"
                        if k not in seen:
                            seen.add(k)
                            if k not in self.map.tile_image_cache:
                                want.append((zoom, pos[0], pos[1]))
                    except Exception:
                        pass
        except Exception:
            return
        if not want:
            return  # eksik yok
        try:
            self._tile_gen += 1
        except Exception:
            return
        if self._tile_warming:
            return
        self._tile_warming = True
        try:
            import threading
            import queue as _queue
            if not hasattr(self, "_tile_queue") or self._tile_queue is None:
                self._tile_queue = _queue.Queue()
            threading.Thread(target=self._warm_fetch, daemon=True,
                             args=(self._tile_gen, server, want)).start()
        except Exception:
            self._tile_warming = False
            return
        try:
            self.after(120, self._warm_tick)
        except Exception:
            pass

    def _warm_fetch(self, gen, server, want):
        """Worker: SADECE ag indirme + bayt isleme (Tkinter'a dokunmaz).

        Girdi salt-veri snapshot'tir (ana thread uretir). Sonuclar
        thread-safe kuyruga gider. Karo basi tek deneme + kisa backoff;
        sonsuz retry YOK (basarisiz karo bir sonraki tetiklemeye kalir).
        """
        try:
            import requests
        except Exception:
            self._tile_warming = False
            return
        try:
            import queue as _queue
            q = getattr(self, "_tile_queue", None)
            if q is None:
                q = _queue.Queue()
                self._tile_queue = q
            for zoom, x, y in want:
                if gen != self._tile_gen:
                    break
                try:
                    url = (server.replace("{x}", str(x))
                                 .replace("{y}", str(y))
                                 .replace("{z}", str(zoom)))
                    r = requests.get(
                        url, timeout=12,
                        headers={"User-Agent": "DepremAnaliz-Marmara/1.0"})
                    if r.status_code == 200 and r.content:
                        if is_placeholder_tile(r.content):
                            q.put(("noinfo", gen, zoom, x, y, None))
                        else:
                            q.put(("tile", gen, zoom, x, y, r.content))
                    else:
                        time.sleep(0.2)
                except Exception:
                    time.sleep(0.2)
        except Exception:
            pass
        finally:
            self._tile_warming = False

    def _warm_tick(self):
        # Ana thread: kuyrugu bosalt, PhotoImage uret, canvas'a bas.
        # Eski jenerasyon sonuclari o anki gorunumu EZEMEZ (gen + zoom
        # cift kontrolu). Pencere kapandiysa sessizce dur (after-yarisi).
        try:
            try:
                if not self.winfo_exists():
                    return
            except Exception:
                return
            my_gen = self._tile_gen
            from PIL import Image, ImageTk
            import io
            try:
                q = getattr(self, "_tile_queue", None)
                pend = []
                if q is not None:
                    while True:
                        try:
                            pend.append(q.get_nowait())
                        except Exception:
                            break
            except Exception:
                pend = []
            cur_zoom = None
            try:
                cur_zoom = round(self.map.zoom)
            except Exception:
                pass
            noinfo = []
            for kind, gen, zoom, x, y, raw in pend:
                if gen != my_gen or (cur_zoom is not None and zoom != cur_zoom):
                    continue
                key = f"{zoom}{x}{y}"
                try:
                    if kind == "noinfo":
                        noinfo.append((zoom, x, y))
                        continue
                    if key in self.map.tile_image_cache:
                        continue
                    img = Image.open(io.BytesIO(raw))
                    self.map.tile_image_cache[key] = ImageTk.PhotoImage(img)
                except Exception:
                    pass
            # yer-tutucu/eksik karolar: kutuphanenin hata karosunu ort,
            # notr geri-donus goster + durumu acikla
            try:
                if noinfo:
                    nd = _nodata_icon(self._light)
                    for zoom, x, y in noinfo:
                        key = f"{zoom}{x}{y}"
                        try:
                            if nd is not None:
                                self.map.tile_image_cache[key] = nd
                        except Exception:
                            pass
                    self._set_conn(
                        "Bu yakınlaştırma düzeyinde bazı altlık karoları yok")
            except Exception:
                pass
            try:
                arr = getattr(self.map, "canvas_tile_array", None) or []
                zoom = round(self.map.zoom)
                for col in arr:
                    for ct in list(col or []):
                        try:
                            pos = ct.tile_name_position
                            img = self.map.tile_image_cache.get(
                                f"{zoom}{pos[0]}{pos[1]}")
                            if img is not None:
                                ct.set_image(img)
                        except Exception:
                            pass
            except Exception:
                pass
            missing = 0
            try:
                arr = getattr(self.map, "canvas_tile_array", None) or []
                zoom = round(self.map.zoom)
                for col in arr:
                    for ct in list(col or []):
                        try:
                            pos = ct.tile_name_position
                            if f"{zoom}{pos[0]}{pos[1]}" not in self.map.tile_image_cache:
                                missing += 1
                        except Exception:
                            pass
            except Exception:
                pass
            if missing and my_gen == self._tile_gen:
                if not self._tile_warming:
                    self._warm_tiles()
                else:
                    try:
                        self.after(300, self._warm_tick)
                    except Exception:
                        pass
        except Exception:
            pass

    # ---------- tema / durum ----------
    def apply_theme(self, light):
        self._light = bool(light)
        try:
            if light:
                self.map.set_tile_server(ESRI_LIGHT)
            else:
                self.map.set_tile_server(ESRI_DARK)
        except Exception:
            pass
        try:
            self.after(400, self._warm_tiles)
        except Exception:
            pass
        try:
            self._rebuild_markers()
        except Exception:
            pass

    def _set_conn(self, text):
        try:
            self._conn.configure(text=text)
        except Exception:
            pass
        try:
            if self._status_cb:
                self._status_cb(text)
        except Exception:
            pass

    def _probe_connection(self):
        def _run():
            ok = False
            try:
                import requests
                r = requests.head("https://server.arcgisonline.com/",
                                  timeout=6,
                                  headers={"User-Agent": "DepremAnaliz-Marmara/1.0"})
                ok = r.status_code < 500
            except Exception:
                ok = False
            self._online = ok
            try:
                self.after(0, self._set_conn,
                           "" if ok else "Çevrimdışı: önbellektekiler gösteriliyor")
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def refresh_status(self):
        self._probe_connection()

    # ---------- veri ----------
    def set_events(self, events):
        self._events = list(events or [])
        for ev in self._events:
            for s in (ev.get("member_channels")
                      or ev.get("member_sources") or []):
                self._visible.setdefault(s, True)
        self._rebuild()

    def set_data(self, sources):
        try:
            self.set_events(dedupe_layers(sources))
        except Exception:
            self._events = []
            self._rebuild()

    def _event_channels(self, ev):
        ch = ev.get("member_channels") or ev.get("member_sources") or []
        return ch if ch else []

    def _event_visible(self, ev):
        srcs = self._event_channels(ev)
        if not srcs:
            return True
        return any(self._visible.get(s, True) for s in srcs)

    def set_layer_visible(self, src, visible):
        self._visible[src] = bool(visible)
        self._rebuild_markers()

    def set_faults_visible(self, visible):
        self._faults_visible = bool(visible)
        self._build_faults()

    def layer_count(self, src):
        return sum(1 for ev in self._events
                   if src in (ev.get("member_channels")
                              or ev.get("member_sources") or []))

    def total_count(self):
        return sum(1 for ev in self._events if self._event_visible(ev))

    def unique_count(self):
        return len(self._events)

    def fit(self, lon0=26.4, lon1=30.6, lat0=40.0, lat1=41.6):
        try:
            self.map.fit_bounding_box((lat1, lon0), (lat0, lon1))
        except Exception:
            try:
                self.map.set_position((lat0 + lat1) / 2, (lon0 + lon1) / 2)
                self.map.set_zoom(DEFAULT_ZOOM)
            except Exception:
                pass
        try:
            self.after(500, self._warm_tiles)
        except Exception:
            pass

    # ---------- cizim ----------
    def _clear_markers(self):
        try:
            self.map.delete_all_marker()
        except Exception:
            pass
        self._markers = {}

    def _clear_faults(self):
        for p in self._paths:
            try:
                p.delete()
            except Exception:
                pass
        self._paths = []

    def _build_faults(self):
        self._clear_faults()
        if not self._faults_visible:
            return
        try:
            from deprem_izleme.fault_segments import FAULT_SEGMENTS, _seg_paths
            for seg in FAULT_SEGMENTS:
                _w = 1 if seg.get("name") == "IPGP-ek" else 2
                _col = "#94A3B8" if seg.get("name") == "IPGP-ek" else seg.get("color", "#F87171")
                for _path in _seg_paths(seg):
                    pts = [(la, lo) for la, lo in _path]
                    if len(pts) < 2:
                        continue
                    try:
                        self._paths.append(self.map.set_path(
                            pts, color=_col, width=_w,
                            command=lambda _m, _s=seg: self._select_fault(_s)))
                    except Exception:
                        continue
        except Exception:
            pass

    def _rebuild_markers(self):
        self._clear_markers()
        try:
            _ci = _city_icon()
            _tc = "#3F3F46" if self._light else "#D4D4D8"
            for _name, _la, _lo in CITY_LABELS:
                self.map.set_marker(_la, _lo, text=_name, text_color=_tc,
                                    marker_color_circle="#6B7280",
                                    marker_color_outside="#6B7280",
                                    icon=_ci, icon_anchor="center",
                                    command=lambda _m: None)
        except Exception:
            pass
        vis = [ev for ev in self._events if self._event_visible(ev)]
        vis.sort(key=lambda e: (e.get("magnitude")
                                if e.get("magnitude") is not None else 0))
        if len(vis) > MAX_MARKERS:
            vis = vis[-MAX_MARKERS:]
        for ev in vis:
            try:
                la = float(ev.get("latitude"))
                lo = float(ev.get("longitude"))
            except (TypeError, ValueError):
                continue
            mag = ev.get("magnitude")
            try:
                magf = float(mag) if mag is not None else None
            except (TypeError, ValueError):
                magf = None
            key = _event_key(ev)
            show_txt = (magf is not None and magf >= 4.0) or key == self._selected
            txt = f"M{magf:.1f}" if show_txt and magf is not None else None
            try:
                mk = self.map.set_marker(
                    la, lo, text=txt,
                    marker_color_circle=_mag_color(magf),
                    marker_color_outside=_mag_color(magf),
                    icon=_circle_icon(_mag_color(magf), _mag_radius(magf)),
                    icon_anchor="center",
                    command=self._on_marker, data=ev)
                self._markers[key] = mk
            except Exception:
                continue

    def _rebuild(self):
        self._rebuild_markers()
        self._build_faults()

    # ---------- secim ----------
    def _select_event(self, ev):
        self._selected = _event_key(ev)
        self._rebuild_markers()
        if self.on_quake:
            q = dict(ev)
            try:
                from deprem_izleme.fault_segments import get_nearest_fault
                seg, d = get_nearest_fault(ev.get("latitude"),
                                           ev.get("longitude"))
                info = {"fault": seg["name_tr"] if seg else "?",
                        "fault_dist_km": round(d, 1)}
            except Exception:
                info = {"fault": "?", "fault_dist_km": None}
            self.on_quake(q, info)

    def _select_fault(self, seg):
        if self.on_fault:
            self.on_fault(seg)

    def _nearby(self, ref_ev, tol_px=18.0):
        try:
            ref = self._markers.get(_event_key(ref_ev))
            if ref is None:
                return [ref_ev]
            rx, ry = ref.get_canvas_pos(ref.position)
        except Exception:
            return [ref_ev]
        out = []
        for ev in self._events:
            if not self._event_visible(ev):
                continue
            try:
                mk = self._markers.get(_event_key(ev))
                if mk is None:
                    continue
                x, y = mk.get_canvas_pos(mk.position)
            except Exception:
                continue
            import math
            if math.hypot(x - rx, y - ry) <= tol_px:
                out.append(ev)
        return out or [ref_ev]

    def _on_marker(self, marker):
        try:
            ev = marker.data
        except Exception:
            return
        cands = self._nearby(ev)
        if len(cands) <= 1:
            self._select_event(ev)
            return
        self._popup_event_list(cands)

    def _popup_event_list(self, cands):
        import tkinter as tk
        try:
            pop = tk.Toplevel(self)
            pop.wm_overrideredirect(True)
            try:
                x, y = self.winfo_pointerx(), self.winfo_pointery()
            except Exception:
                x, y = 200, 200
            pop.geometry(f"+{x + 10}+{y + 10}")
            lb = tk.Listbox(pop, font=("Segoe UI", 9),
                            height=min(len(cands), 8), width=44)
            lb.pack()
            for ev in cands:
                mag = ev.get("magnitude")
                mag_s = f"M{mag:.1f}" if mag is not None else "M?"
                srcs = "+".join(ev.get("member_sources") or ["?"])
                loc = (ev.get("location") or "?")[:24]
                lb.insert("end", f"{mag_s} • {loc} • {srcs}")

            def _pick(_e=None):
                try:
                    self._select_event(cands[lb.curselection()[0]])
                except Exception:
                    pass
                try:
                    pop.destroy()
                except Exception:
                    pass
            lb.bind("<Double-Button-1>", _pick)
            lb.bind("<Return>", _pick)
            lb.bind("<FocusOut>", lambda _e: pop.destroy())
            lb.selection_set(0)
            lb.focus_set()
        except Exception:
            self._select_event(cands[0])
