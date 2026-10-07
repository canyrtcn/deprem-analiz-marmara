"""
Uygulama içi interaktif harita - tkintermapview tabanlı
Özellikler: zoom, pan, tıklanabilir marker'lar, fay hatları
"""
import logging
import math
from datetime import datetime, timedelta
from tkinter import messagebox

try:
    import tkintermapview
    TKMAP_AVAILABLE = True
except ImportError:
    TKMAP_AVAILABLE = False

from deprem_izleme.db import get_earthquakes
from deprem_izleme.fault_segments import FAULT_SEGMENTS, HISTORICAL_EARTHQUAKES

logger = logging.getLogger(__name__)


# CartoDB Dark Matter tile sunucusu
DARK_TILES = "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
SATELLITE_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"


def create_interactive_map(parent_frame, days=7, earthquakes=None,
                            show_faults=False, show_historical=True):
    """
    tkintermapview tabanlı interaktif harita oluştur.
    Döner: tkintermapview.TkinterMapView
    """
    if not TKMAP_AVAILABLE:
        logger.error("tkintermapview gerekli: pip install tkintermapview")
        return None

    if earthquakes is None:
        earthquakes = get_earthquakes(
            since=datetime.now() - timedelta(days=days),
            region="marmara", limit=500
        )

    # Harita widget'ı
    map_widget = tkintermapview.TkinterMapView(
        parent_frame,
        width=800, height=600,
        corner_radius=8
    )

    # Merkez: Marmara Denizi
    map_widget.set_position(40.8, 28.5)
    map_widget.set_zoom(9)

    # Tile sunucu: CartoDB Dark Matter
    map_widget.set_tile_server(DARK_TILES, max_zoom=18)

    # Genel bakış haritasını kapat (2 renkli parça)
    try:
        # tkintermapview v1.29+
        if hasattr(map_widget, 'set_overviewmap'):
            map_widget.set_overviewmap(False)
    except Exception:
        pass

    # ===== FAY HATLARI (PolyLine) — isteğe bağlı =====
    if show_faults:
        for seg in FAULT_SEGMENTS:
            coords = [(c[0], c[1]) for c in seg["coords"]]
            seg_name = seg["name_tr"]
            locked = seg.get("locked_status", "?").replace("_", " ").title()
            rec = seg.get("recurrence_years", "?")
            last_rup = seg.get("last_rupture", "?")
            gap = seg.get("seismic_gap_years", "?")
            mag = seg["max_magnitude"]
            slide_rate = seg["slip_rate"]

            poly = map_widget.set_path(
                coords,
                color=seg["color"],
                width=3,
            )

            # Orta noktaya marker (isim + bilgi)
            mid_idx = len(seg["coords"]) // 2
            mid_lat, mid_lon = seg["coords"][mid_idx]

            info_text = (
                f"{seg_name}\n"
                f"━━━━━━━━━━━━━━\n"
                f"Durum: {locked}\n"
                f"Mmax: M{mag}\n"
                f"Boy: {seg['length_km']} km\n"
                f"Kayma: {slide_rate} mm/yıl\n"
                f"Tekrarlama: ~{rec} yıl\n"
                f"Son kırılma: {last_rup}\n"
                f"Boşluk: {gap} yıl\n"
                f"Kaynak: {seg.get('recurrence_source', '?')}"
            )

            # Alt alta görünen özel marker (polyline ortasına bilgi etiketi)
            map_widget.set_marker(
                mid_lat, mid_lon,
                text=f"  {seg_name}  ",
                text_color="#e0e0e0",
                marker_color_circle=seg["color"],
                marker_color_outside="black",
                font=("Segoe UI", 7, "normal"),
            )

    # ===== TARİHSEL DEPREMLER — isteğe bağlı =====
    if show_historical:
        for hist_eq in HISTORICAL_EARTHQUAKES:
            year, lat, lon, mag, desc = hist_eq
            map_widget.set_marker(
                lat, lon,
                text=f" {year} ",
                text_color="#c084fc",
                marker_color_circle="#7c3aed",
                marker_color_outside="black",
                font=("Segoe UI", 7, "normal"),
            )

    # ===== GÜNCEL DEPREMLER =====
    for eq in earthquakes:
        lat = eq.get("latitude", 0)
        lon = eq.get("longitude", 0)
        mag = eq.get("magnitude", 0) or 0
        depth = eq.get("depth_km", 0) or 0
        loc = eq.get("location", "?")[:40]
        time_str = eq.get("occurred_at", "?")
        src = eq.get("source", "?")
        tag = eq.get("region_tag", "?")

        # Magnitüde göre renk
        if mag >= 4.0:
            marker_color = "#ef4444"
        elif mag >= 3.0:
            marker_color = "#f59e0b"
        elif mag >= 2.0:
            marker_color = "#f97316"
        else:
            marker_color = "#2ecc71"

        # Popup metni
        popup_text = (
            f"📍 M{mag:.1f}\n"
            f"🕐 {time_str}\n"
            f"📏 {depth:.0f} km derinlik\n"
            f"🌐 {lat:.4f}, {lon:.4f}\n"
            f"🏠 {loc}\n"
            f"📡 {src.upper()} | {tag.upper()}"
        )

        # Marker (tıklanabilir, popup gösterir)
        from tkinter import messagebox
        def show_detail(m=mag, t=time_str, d=depth, l=loc, s=src, lat=lat, lon=lon):
            risk_info = ""
            try:
                from deprem_izleme.aggregation import get_comprehensive_risk_report
                r = get_comprehensive_risk_report()
                risk_info = f"📊 Risk: {r['composite_risk_score']:.3f} ({r['risk_level']})"
            except:
                pass
            messagebox.showinfo(
                f"Deprem M{m:.1f}",
                f"🕐 {t}\n📍 {l}\n📏 {d:.0f} km derinlik\n🌐 {lat:.4f}, {lon:.4f}\n📡 {s.upper()}\n{risk_info}"
            )

        marker = map_widget.set_marker(
            lat, lon,
            text=f"M{mag:.1f}",
            text_color="#ffffff",
            marker_color_circle=marker_color,
            marker_color_outside="black",
            font=("Segoe UI", 8, "bold"),
            command=show_detail,
        )

    logger.info(f"Interaktif harita: {len(earthquakes)} deprem, {len(FAULT_SEGMENTS)} fay")
    return map_widget


def update_map(map_widget, days=7, earthquakes=None,
                show_faults=False, show_historical=True):
    """Mevcut haritayı güncelle (eski marker'ları temizle, yenilerini ekle)."""
    if not map_widget:
        return None

    if earthquakes is None:
        earthquakes = get_earthquakes(
            since=datetime.now() - timedelta(days=days),
            region="marmara", limit=500
        )

    # Temizle (tüm marker ve path'leri kaldır)
    map_widget.clear_markers()
    map_widget.clear_path()

    # Fay hatları (isteğe bağlı)
    if show_faults:
        for seg in FAULT_SEGMENTS:
            coords = [(c[0], c[1]) for c in seg["coords"]]
            path = map_widget.set_path(coords, color=seg["color"], width=3)

            mid_idx = len(seg["coords"]) // 2
            mid_lat, mid_lon = seg["coords"][mid_idx]
            map_widget.set_marker(
                mid_lat, mid_lon,
                text=f"  {seg['name_tr']}  ",
                text_color="#e0e0e0",
                marker_color_circle=seg["color"],
                marker_color_outside="black",
                font=("Segoe UI", 7, "normal"),
            )

    # Tarihsel depremler (isteğe bağlı)
    if show_historical:
        for hist_eq in HISTORICAL_EARTHQUAKES:
            year, lat, lon, mag, desc = hist_eq
            map_widget.set_marker(
                lat, lon,
                text=f" {year} ",
                text_color="#c084fc",
                marker_color_circle="#7c3aed",
                marker_color_outside="black",
                font=("Segoe UI", 7, "normal"),
            )

    # Güncel depremler
    for eq in earthquakes:
        lat = eq.get("latitude", 0)
        lon = eq.get("longitude", 0)
        mag = eq.get("magnitude", 0) or 0
        depth = eq.get("depth_km", 0) or 0
        loc = eq.get("location", "?")[:40]
        time_str = eq.get("occurred_at", "?")
        src = eq.get("source", "?")

        if mag >= 4.0: mc = "#ef4444"
        elif mag >= 3.0: mc = "#f59e0b"
        elif mag >= 2.0: mc = "#f97316"
        else: mc = "#2ecc71"

        marker = map_widget.set_marker(
            lat, lon,
            text=f"M{mag:.1f}",
            text_color="#ffffff",
            marker_color_circle=mc,
            marker_color_outside="black",
            font=("Segoe UI", 8, "bold"),
        )

    return map_widget
