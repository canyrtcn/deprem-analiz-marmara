"""
Gomulu Marmara haritasi - sifir bagimlilik (sadece tkinter Canvas).

Gercek cografya: Natural Earth 10m kiyi cizgileri + raster/contour ile
cikarilmis deniz hududu (deprem_izleme.coastline / sealines).
Internet yok, ek paket yok, aninda acilir.

Etkilesim: tekerlek-zoom (imlec merkezli), surukle-kaydir, tikla-sec
(deprem + fay), katman anahtarlari (uygulama/sismik/koeri/faylar).
"""
import math
import tkinter as tk

from deprem_izleme.coastline import COAST_LINES
from deprem_izleme.sealines import SEA_RING, ISLANDS
from deprem_izleme.fault_segments import FAULT_SEGMENTS, get_nearest_fault

K = math.cos(math.radians(40.8))  # boylam duzeltmesi
KM_PER_LON = 111.32 * K

LAND_COLOR = "#0E141F"
SEA_COLOR = "#0D2136"
COAST_LINE = "#49687F"
COAST_CASING = "#04070C"
GRID_COLOR = "#182234"
TEXT_DIM = "#7E8BA0"
TEXT_CITY = "#AEB9CC"
SEL_OUTLINE = "white"
LBL_FG = "white"
LBL_HALO = "black"
WATER_LBL = "#33506B"
CITY_DOT = "#5B6B82"
SCALE_FG = "#E6EBF4"
SCALE_BG = "#0A0E15"
COLOR_NORTH = "#26314A"


_DARK_MAP = {
    "LAND_COLOR": "#0E141F",
    "SEA_COLOR": "#0D2136",
    "COAST_LINE": "#49687F",
    "COAST_CASING": "#04070C",
    "GRID_COLOR": "#182234",
    "TEXT_DIM": "#7E8BA0",
    "TEXT_CITY": "#AEB9CC",
    "SEL_OUTLINE": "white",
    "LBL_FG": "white",
    "LBL_HALO": "black",
    "WATER_LBL": "#33506B",
    "CITY_DOT": "#5B6B82",
    "SCALE_FG": "#E6EBF4",
    "SCALE_BG": "#0A0E15",
    "COLOR_NORTH": "#26314A",
}
_LIGHT_MAP = {
    "LAND_COLOR": "#EDF1F6",
    "SEA_COLOR": "#D8E7F5",
    "COAST_LINE": "#5B7A99",
    "COAST_CASING": "#FFFFFF",
    "GRID_COLOR": "#D3DCE7",
    "TEXT_DIM": "#5B6B82",
    "TEXT_CITY": "#334155",
    "SEL_OUTLINE": "#0F172A",
    "LBL_FG": "#0F172A",
    "LBL_HALO": "white",
    "WATER_LBL": "#7FA3C4",
    "CITY_DOT": "#64748B",
    "SCALE_FG": "#0F172A",
    "SCALE_BG": "#FFFFFF",
    "COLOR_NORTH": "#94A3B8",
}


def _apply_map_theme():
    try:
        from deprem_izleme.config import load_settings
        light = (load_settings().get("appearance") or "dark") == "light"
        g = globals()
        g.update(_LIGHT_MAP if light else _DARK_MAP)
    except Exception:
        pass


_apply_map_theme()

CITIES = [
    ("İstanbul", 41.03, 28.97, 1),
    ("Tekirdağ", 40.98, 27.52, 1),
    ("Silivri", 41.07, 28.25, 0),
    ("Yalova", 40.65, 29.27, 0),
    ("İzmit", 40.77, 29.94, 1),
    ("Bursa", 40.20, 29.06, 1),
    ("Bandırma", 40.35, 27.97, 0),
    ("Çanakkale", 40.15, 26.41, 1),
]

SRC_COLORS = {
    "uygulama": "#2DD4BF",
    "sismik": "#FBBF24",
    "koeri": "#60A5FA",
}


def _mag_color(mag):
    if mag >= 5.0:
        return "#C084FC"
    if mag >= 4.0:
        return "#F87171"
    if mag >= 3.0:
        return "#FBBF24"
    if mag >= 2.0:
        return "#FB9236"
    return "#34D399"


class MarmaraMap(tk.Canvas):
    """Kartografik Marmara haritasi."""

    def __init__(self, master, on_quake=None, on_fault=None, **kw):
        kw.setdefault("bg", LAND_COLOR)
        kw.setdefault("highlightthickness", 0)
        super().__init__(master, **kw)
        self.on_quake = on_quake
        self.on_fault = on_fault
        self._sources = {}
        self._visible = {}
        self._faults_visible = True
        self._selected = None
        self._cx, self._cy = 28.45, 40.75
        self._span_x = 4.6
        self._press_xy = None
        self._moved = False
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Button-4>", lambda e: self.zoom_at(1.2, e.x, e.y))
        self.bind("<Button-5>", lambda e: self.zoom_at(1 / 1.2, e.x, e.y))
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    # ---------- gorunum ----------
    def _scales(self):
        w = self.winfo_width() or 800
        h = self.winfo_height() or 500
        sx = w / self._span_x
        span_y = self._span_x * h / w
        sy = h / span_y
        return w, h, sx, sy

    def project(self, lon, lat):
        # Gerçek en-boy: boylam derecesi cos(40.8°) ile kısalır (K ile düzeltme)
        w, h, sx, sy = self._scales()
        return (w / 2 + (lon - self._cx) * K * sx,
                h / 2 - (lat - self._cy) * sy)

    def unproject(self, x, y):
        w, h, sx, sy = self._scales()
        return (self._cx + (x - w / 2) / (K * sx),
                self._cy - (y - h / 2) / sy)

    def zoom(self, factor):
        self._span_x = min(8.0, max(0.35, self._span_x / factor))
        self.redraw()

    def zoom_at(self, factor, x, y):
        lon, lat = self.unproject(x, y)
        self._span_x = min(8.0, max(0.35, self._span_x / factor))
        lon2, lat2 = self.unproject(x, y)
        self._cx += lon - lon2
        self._cy += lat - lat2
        self.redraw()

    def _on_wheel(self, e):
        self.zoom_at(1.2 if e.delta > 0 else 1 / 1.2, e.x, e.y)

    def _on_press(self, e):
        self._press_xy = (e.x, e.y)
        self._moved = False

    def _on_drag(self, e):
        if not self._press_xy:
            return
        px, py = self._press_xy
        if abs(e.x - px) + abs(e.y - py) > 4:
            self._moved = True
        w, h, sx, sy = self._scales()
        self._cx -= (e.x - px) / sx
        self._cy += (e.y - py) / sy
        self._press_xy = (e.x, e.y)
        self.redraw()

    def _on_release(self, e):
        if self._moved or not self._press_xy:
            self._press_xy = None
            return
        self._press_xy = None
        items = self.find_overlapping(e.x - 13, e.y - 13, e.x + 13, e.y + 13)
        # Üstten alta: görünen (en üstteki) öğe seçilir
        for it in reversed(items):
            tags = self.gettags(it)
            for t in tags:
                if t.startswith("q:"):
                    _, src, eid = t.split(":", 2)
                    self._select_quake(src, eid)
                    return
                if t.startswith("f:"):
                    self._select_fault(t[2:])
                    return

    def fit(self, lon0=26.4, lon1=30.6, lat0=40.0, lat1=41.6):
        self._cx = (lon0 + lon1) / 2
        self._cy = (lat0 + lat1) / 2
        self._span_x = (lon1 - lon0) * 1.05
        self.redraw()

    # ---------- veri ----------
    def set_data(self, sources):
        """sources: {kaynak_adi: [quake, ...]}."""
        self._sources = {k: (v or []) for k, v in (sources or {}).items()}
        for k in self._sources:
            self._visible.setdefault(k, True)
        self.redraw()

    def set_layer_visible(self, src, visible):
        self._visible[src] = bool(visible)
        self.redraw()

    def set_faults_visible(self, visible):
        self._faults_visible = bool(visible)
        self.redraw()

    def layer_count(self, src):
        return len(self._sources.get(src, []))

    def total_count(self):
        return sum(len(v) for k, v in self._sources.items() if self._visible.get(k, True))

    # ---------- secim ----------
    def _select_quake(self, src, eid):
        self._selected = (src, eid)
        self.redraw()
        if self.on_quake:
            for q in self._sources.get(src, []):
                if str(q.get("event_id", id(q))) == eid:
                    try:
                        seg, d = get_nearest_fault(q.get("latitude"), q.get("longitude"))
                        info = {"fault": seg["name_tr"] if seg else "?",
                                "fault_dist_km": round(d, 1)}
                    except Exception:
                        info = {"fault": "?", "fault_dist_km": None}
                    self.on_quake(q, info)
                    return

    def _select_fault(self, name):
        if self.on_fault:
            for seg in FAULT_SEGMENTS:
                if seg["name"] == name:
                    self.on_fault(seg)
                    return

    # ---------- cizim ----------
    def redraw(self):
        _apply_map_theme()
        try:
            self.configure(bg=LAND_COLOR)
        except Exception:
            pass
        w, h, sx, sy = self._scales()
        self.delete("all")
        x0 = self._cx - self._span_x / 2
        x1 = self._cx + self._span_x / 2

        # deniz
        sea_xy = []
        for lon, lat in SEA_RING:
            px, py = self.project(lon, lat)
            sea_xy += [px, py]
        if sea_xy:
            self.create_polygon(sea_xy, fill=SEA_COLOR, outline="", tags=("base",))
        for isl in ISLANDS:
            ixy = []
            for lon, lat in isl:
                px, py = self.project(lon, lat)
                ixy += [px, py]
            if ixy:
                self.create_polygon(ixy, fill=LAND_COLOR, outline=COAST_LINE, tags=("base",))

        # su etiketi (orta basen üstü)
        lx, ly = self.project(28.0, 40.70)
        if 0 <= lx <= w and 0 <= ly <= h and self._span_x > 1.2:
            self.create_text(lx, ly, text="Marmara Denizi", fill=WATER_LBL,
                             font=("Segoe UI", 11, "italic"), tags=("base",))

        # kiyi (kasa + cizgi): parça-bazlı kırpma — görünüm dışına taşan
        # parçanın iki ucu da elenirse kiriş artefaktı oluşurdu; komşusu
        # görünür olan nokta korunur.
        for ln in COAST_LINES:
            pts = []
            keep = [(x0 - 0.5 <= lo <= x1 + 0.5) for _, lo in ln]
            for i, (lon, lat) in enumerate(ln):
                if keep[i] or (i > 0 and keep[i - 1]) or (i + 1 < len(ln) and keep[i + 1]):
                    pts += list(self.project(lon, lat))
            if len(pts) >= 4:
                self.create_line(pts, fill=COAST_CASING, width=4,
                                 capstyle="round", joinstyle="round", tags=("base",))
        for ln in COAST_LINES:
            pts = []
            keep = [(x0 - 0.5 <= lo <= x1 + 0.5) for _, lo in ln]
            for i, (lon, lat) in enumerate(ln):
                if keep[i] or (i > 0 and keep[i - 1]) or (i + 1 < len(ln) and keep[i + 1]):
                    pts += list(self.project(lon, lat))
            if len(pts) >= 4:
                self.create_line(pts, fill=COAST_LINE, width=1.3, tags=("base",))

        # grid
        step = 1.0 if self._span_x > 3 else (0.5 if self._span_x > 1.4 else 0.25)
        lon = math.floor(x0 / step) * step
        while lon <= x1:
            px, _ = self.project(lon, self._cy)
            self.create_line(px, 0, px, h, fill=GRID_COLOR, dash=(2, 5), tags=("base",))
            self.create_text(px + 3, h - 6, text=f"{lon:g}°D", fill=TEXT_DIM,
                             font=("Segoe UI", 7), anchor="sw", tags=("base",))
            lon += step
        span_y = self._span_x * h / w
        lat = math.floor((self._cy - span_y / 2) / step) * step
        while lat <= self._cy + span_y / 2:
            _, py = self.project(self._cx, lat)
            self.create_line(0, py, w, py, fill=GRID_COLOR, dash=(2, 5), tags=("base",))
            self.create_text(5, py - 2, text=f"{lat:g}°K", fill=TEXT_DIM,
                             font=("Segoe UI", 7), anchor="nw", tags=("base",))
            lat += step

        # sehirler
        for name, la, lo, major in CITIES:
            if not (x0 <= lo <= x1):
                continue
            px, py = self.project(lo, la)
            if not (-20 <= px <= w + 20 and -20 <= py <= h + 20):
                continue
            r = 3 if major else 2
            self.create_oval(px - r, py - r, px + r, py + r,
                             fill=CITY_DOT, outline="", tags=("base",))
            if major or self._span_x < 2.2:
                self.create_text(px + 6, py - 6, text=name, fill=TEXT_CITY,
                                 font=("Segoe UI", 8 if major else 7), anchor="sw",
                                 tags=("base",))

        # faylar (kesik cizgi = sematik iz, duz = MTA sayisallastirma)
        if self._faults_visible:
            for seg in FAULT_SEGMENTS:
                pts = []
                for la, lo in seg["coords"]:
                    pts += list(self.project(lo, la))
                dash = None if seg.get("trace_source") == "MTA sayısallaştırma" else (6, 4)
                if len(pts) >= 4:
                    self.create_line(pts, fill=seg["color"], width=2.2, dash=dash,
                                     tags=("lyr_fault", f"f:{seg['name']}"))
                for splay in seg.get("splays", []):
                    spts = []
                    for la, lo in splay:
                        spts += list(self.project(lo, la))
                    if len(spts) >= 4:
                        self.create_line(spts, fill=seg["color"], width=1.0, dash=(3, 3),
                                         tags=("lyr_fault", f"f:{seg['name']}"))
            if self._span_x < 3.0:
                for seg in FAULT_SEGMENTS:
                    la = sum(c[0] for c in seg["coords"]) / len(seg["coords"])
                    lo = sum(c[1] for c in seg["coords"]) / len(seg["coords"])
                    px, py = self.project(lo, la)
                    if 0 <= px <= w and 0 <= py <= h:
                        self.create_text(px, py - 9, text=seg["name_tr"],
                                         fill=TEXT_CITY, font=("Segoe UI", 7),
                                         tags=("lyr_fault",))

        # depremler (kaynak katmanli)
        for src, items in self._sources.items():
            if not self._visible.get(src, True):
                continue
            scol = SRC_COLORS.get(src, "#E6EBF4")
            for q in sorted(items, key=lambda e: ((e.get("magnitude")) or 0)):
                la, lo = q.get("latitude"), q.get("longitude")
                if la is None or lo is None:
                    continue
                if not (x0 <= lo <= x1):
                    continue
                px, py = self.project(lo, la)
                if not (0 <= px <= w and 0 <= py <= h):
                    continue
                mag = q.get("magnitude") or 0
                r = 3.2 + mag * 1.7
                eid = str(q.get("event_id", id(q)))
                tag = f"q:{src}:{eid}"
                sel = self._selected == (src, eid)
                self.create_oval(px - r, py - r, px + r, py + r,
                                 fill=_mag_color(mag), outline=SEL_OUTLINE if sel else scol,
                                 width=2 if sel else 1, tags=("lyr_q", tag))
                # Gorunmez genis vuruş alani (tiklamayi kolaylastirir)
                self.create_oval(px - r - 9, py - r - 9, px + r + 9, py + r + 9,
                                 fill="", outline="", tags=("lyr_q", tag))
                if sel:
                    self.create_oval(px - r - 4, py - r - 4, px + r + 4, py + r + 4,
                                     outline=SEL_OUTLINE, width=1, tags=("lyr_q",))
                if mag >= 2.5 and (mag >= 3.0 or self._span_x < 3.0):
                    lx, ly = px, py - r - 8
                    self.create_text(lx + 1, ly + 1, text=f"M{mag:.1f}", fill=LBL_HALO,
                                     font=("Segoe UI", 7, "bold"), tags=("lyr_q",))
                    self.create_text(lx, ly, text=f"M{mag:.1f}", fill=LBL_FG,
                                     font=("Segoe UI", 7, "bold"), tags=("lyr_q",))

        self._draw_scalebar(w, h)
        self._draw_north(w)

    def _draw_scalebar(self, w, h):
        px_per_km = (w / self._span_x) / KM_PER_LON
        best = 10
        for km in (10, 20, 50, 100, 200, 500):
            if km * px_per_km <= 130:
                best = km
        bw = best * px_per_km
        x1, y1 = w - 14, h - 14
        x0 = x1 - bw
        self.create_rectangle(x0, y1 - 5, x1, y1, fill=SCALE_FG, outline="", tags=("base",))
        self.create_rectangle(x0, y1 - 5, x0 + bw / 2, y1, fill=SCALE_BG, outline="", tags=("base",))
        self.create_text(x0 - 4, y1 - 3, text=f"{best} km", fill=TEXT_DIM,
                         font=("Segoe UI", 8), anchor="e", tags=("base",))

    def _draw_north(self, w):
        cx, cy = 30, 32
        self.create_oval(cx - 13, cy - 13, cx + 13, cy + 13,
                         fill=SCALE_BG, outline=COLOR_NORTH, tags=("base",))
        self.create_polygon([cx, cy - 8, cx - 5, cy + 5, cx + 5, cy + 5],
                            fill=SCALE_FG, outline="", tags=("base",))
        self.create_text(cx, cy + 9, text="K", fill=TEXT_DIM,
                         font=("Segoe UI", 7, "bold"), tags=("base",))
