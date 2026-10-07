"""
Deprem haritası oluşturucu - Folium tabanlı interaktif HTML harita
Birincil harita çözümü: tıklanabilir, zoom yapılabilir, popup'lı
"""
import os
import logging
import webbrowser
import tempfile
from datetime import datetime, timedelta

from deprem_izleme.db import get_earthquakes
from deprem_izleme.fault_segments import FAULT_SEGMENTS, HISTORICAL_EARTHQUAKES

logger = logging.getLogger(__name__)

try:
    import folium
    from folium import plugins
    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False


def _mag_color(mag):
    if mag >= 5.0: return "#8e44ad"
    if mag >= 4.0: return "#ef4444"
    if mag >= 3.0: return "#f59e0b"
    if mag >= 2.0: return "#f97316"
    return "#2ecc71"


def _mag_radius(mag):
    return max(4, min(18, mag * 3.5))


def _make_popup_html(eq):
    """Deprem popup HTML'i."""
    mag = eq.get("magnitude", 0) or 0
    depth = eq.get("depth_km", 0) or 0
    lat = eq.get("latitude", 0)
    lon = eq.get("longitude", 0)
    loc = eq.get("location", "?")
    time = eq.get("occurred_at", "?")
    src = eq.get("source", "?")
    tag = eq.get("region_tag", "?")
    ml = eq.get("magnitude_ml", "")
    mw = eq.get("magnitude_mw", "")

    ml_str = f"ML: {ml}" if ml else ""
    mw_str = f"Mw: {mw}" if mw else ""

    return f"""
    <div style="min-width:220px; font-family:sans-serif; background:#1a1a2e; color:#e0e0e0; padding:12px; border-radius:8px;">
        <h3 style="margin:0 0 6px 0; font-size:18px; color:#3b82f6;">M{mag:.1f}</h3>
        <table style="font-size:12px; line-height:1.6;">
            <tr><td style="color:#888;padding-right:8px;">📍 Yer:</td><td>{loc}</td></tr>
            <tr><td style="color:#888;">🕐 Zaman:</td><td>{time}</td></tr>
            <tr><td style="color:#888;">📏 Derinlik:</td><td>{depth:.1f} km</td></tr>
            <tr><td style="color:#888;">🌐 Koordinat:</td><td>{lat:.4f}, {lon:.4f}</td></tr>
            <tr><td style="color:#888;">📡 Kaynak:</td><td>{src.upper()}</td></tr>
            <tr><td style="color:#888;">🏷️ Bölge:</td><td>{tag.upper()}</td></tr>
            {f'<tr><td style="color:#888;">{ml_str.split(":")[0]}:</td><td>{ml}</td></tr>' if ml_str else ''}
            {f'<tr><td style="color:#888;">{mw_str.split(":")[0]}:</td><td>{mw}</td></tr>' if mw_str else ''}
        </table>
    </div>
    """


def generate_map(earthquakes=None, days=7, title=None, filename=None,
                 show_faults=True, show_historical=True):
    """
    İnteraktif Folium haritası oluştur.
    Tıklanabilir deprem noktaları, fay hatları, katman seçimi.
    """
    if not FOLIUM_AVAILABLE:
        logger.error("Lütfen folium yükleyin: pip install folium")
        return None

    if earthquakes is None:
        earthquakes = get_earthquakes(
            since=datetime.now() - timedelta(days=days),
            region="marmara", limit=500
        )

    # Harita merkezi
    center = [40.8, 28.5]

    m = folium.Map(
        location=center, zoom_start=9,
        control_scale=True,
    )

    # ===== KATMANLAR =====

    # 1. Dark Matter taban haritası
    folium.TileLayer(
        tiles="https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        name="Karanlık (CartoDB)",
        attr='&copy; <a href="https://carto.com/">CARTO</a>',
        control=True,
    ).add_to(m)

    # 2. OpenStreetMap
    folium.TileLayer(
        tiles="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        name="OpenStreetMap",
        attr='&copy; <a href="https://www.openstreetmap.org/">OSM</a>',
        control=True,
    ).add_to(m)

    # 3. Uydu
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        name="Uydu (ESRI)",
        attr='&copy; ESRI',
        control=True,
    ).add_to(m)

    # ===== FAY HATLARI =====
    if show_faults:
        for seg in FAULT_SEGMENTS:
            coords = [[c[0], c[1]] for c in seg["coords"]]
            seg_name = seg["name_tr"]
            locked = seg.get("locked_status", "?").replace("_", " ").title()
            rec_years = seg.get("recurrence_years", "?")
            last_rup = seg.get("last_rupture", "?")
            gap = seg.get("seismic_gap_years", "?")

            popup_text = f"""
            <div style="min-width:180px;">
                <b style="color:{seg['color']}; font-size:14px;">{seg_name}</b><br>
                <span style="color:#888;">Durum:</span> {locked}<br>
                <span style="color:#888;">Mmax:</span> M{seg['max_magnitude']}<br>
                <span style="color:#888;">Uzunluk:</span> {seg['length_km']} km<br>
                <span style="color:#888;">Kayma:</span> {seg['slip_rate']} mm/yıl<br>
                <span style="color:#888;">Tekrarlama:</span> ~{rec_years} yıl<br>
                <span style="color:#888;">Son kırılma:</span> {last_rup}<br>
                <span style="color:#888;">Boşluk:</span> {gap} yıl<br>
                <span style="color:#888;">Kaynak:</span> {seg.get('recurrence_source', '?')}
            </div>
            """

            folium.PolyLine(
                coords,
                color=seg["color"],
                weight=2.5,
                opacity=0.85,
                popup=folium.Popup(popup_text, max_width=300),
                tooltip=f"{seg_name} (Mmax:{seg['max_magnitude']})",
                name=seg_name,
            ).add_to(m)

    # ===== TARİHSEL DEPREMLER =====
    if show_historical:
        fg_hist = folium.FeatureGroup(name="Tarihsel Depremler", show=True)
        for hist_eq in HISTORICAL_EARTHQUAKES:
            year, lat, lon, mag, desc = hist_eq
            popup_html = f"""
            <div style="min-width:200px;">
                <b style="color:#8b5cf6; font-size:16px;">{year}</b><br>
                <span style="color:#888;">Magnitüd:</span> M{mag:.1f}<br>
                <span style="color:#888;">Yer:</span> {desc}<br>
                <span style="color:#888;">Koordinat:</span> {lat:.2f}, {lon:.2f}
            </div>
            """
            folium.CircleMarker(
                [lat, lon],
                radius=mag * 1.5,
                color="#8b5cf6",
                fill=True,
                fill_color="#8b5cf6",
                fill_opacity=0.4,
                weight=0,
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=f"{year} M{mag:.1f}",
            ).add_to(fg_hist)
        fg_hist.add_to(m)

    # ===== GÜNCEL DEPREMLER =====
    fg_eq = folium.FeatureGroup(name=f"Depremler (son {days}gün)", show=True)

    if earthquakes:
        for eq in earthquakes:
            lat = eq.get("latitude", 0)
            lon = eq.get("longitude", 0)
            mag = eq.get("magnitude", 0) or 0

            folium.CircleMarker(
                [lat, lon],
                radius=_mag_radius(mag),
                color=_mag_color(mag),
                fill=True,
                fill_color=_mag_color(mag),
                fill_opacity=0.75,
                weight=1,
                popup=folium.Popup(_make_popup_html(eq), max_width=300),
                tooltip=f"M{mag:.1f} — {(eq.get('location') or '?')[:30]}",
            ).add_to(fg_eq)

    fg_eq.add_to(m)

    # ===== KONTROLLER =====
    # Katman kontrol
    folium.LayerControl(collapsed=False).add_to(m)

    # Tam ekran
    plugins.Fullscreen(
        position="topleft",
        title="Tam Ekran",
        title_cancel="Çıkış"
    ).add_to(m)

    # Ölçüm aracı
    plugins.MeasureControl(
        position="bottomleft",
        primary_length_unit="kilometers",
        primary_area_unit="sq kilometers",
    ).add_to(m)

    # Fare koordinatları
    plugins.MousePosition(
        position="bottomright",
        separator=" | ",
        num_digits=4,
    ).add_to(m)

    # ===== BAŞLIK =====
    title = title or f"Son {days} Gün - Marmara Deprem Haritası"
    title_html = f'''
    <div style="position:fixed; top:12px; left:50px; z-index:9999;
                background:rgba(15,15,30,0.85); color:#e0e0e0;
                padding:6px 14px; border-radius:6px; font-family:sans-serif;
                border-left:3px solid #3b82f6; font-size:13px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.3);">
        <b>{title}</b> — {len(earthquakes)} deprem
    </div>
    '''
    m.get_root().html.add_child(folium.Element(title_html))

    # Bilgi notu
    info_html = '''
    <div style="position:fixed; bottom:20px; left:10px; z-index:9999;
                background:rgba(15,15,30,0.7); color:#888;
                padding:4px 10px; border-radius:4px; font-size:10px;
                font-family:sans-serif;">
        🖱️ Noktalara tıklayın → detay • Zoom +/- • Katman seçin
    </div>
    '''
    m.get_root().html.add_child(folium.Element(info_html))

    # Kaydet
    if filename is None:
        fd, filename = tempfile.mkstemp(suffix=".html", prefix="deprem_")
        os.close(fd)

    m.save(filename)
    logger.info(f"Harita kaydedildi: {filename}")
    return filename


def open_interactive_map(days=7, earthquakes=None):
    """Interaktif haritayı tarayıcıda aç."""
    path = generate_map(days=days, earthquakes=earthquakes)
    if path:
        webbrowser.open(f"file://{os.path.abspath(path)}")
        return True
    return False


def open_mta_website():
    """MTA Diri Fay haritasını tarayıcıda aç."""
    webbrowser.open("https://yerbilimleri.mta.gov.tr/anasayfa.aspx")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    open_interactive_map(days=7)
