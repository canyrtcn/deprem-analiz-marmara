"""
Grafik modülü - Risk trendi, günlük deprem sayısı, b-değeri trendi
"""
import logging
import math
from datetime import datetime, timedelta
from collections import Counter, defaultdict

from deprem_izleme.db import get_earthquakes, get_weekly_history
from deprem_izleme.aggregation import calculate_b_value, seismic_energy_joules, _compute_risk_score

logger = logging.getLogger(__name__)

COLOR_BG = "#0B1220"
# Grafik renkleri (açık temada üzerine yazılır)
CH_TXT = "#D7DEE9"
CH_DIM = "#7E8BA0"
CH_BRD = "#26314A"
CH_GRID = "#1B2740"
CH_INFO = "#38BDF8"
CH_TEAL = "#2DD4BF"
CH_PANEL = "#0B1220"


_DARK_CHART = {
    "COLOR_BG": "#0B1220",
    "CH_TXT": "#D7DEE9",
    "CH_DIM": "#7E8BA0",
    "CH_BRD": "#26314A",
    "CH_GRID": "#1B2740",
    "CH_INFO": "#38BDF8",
    "CH_TEAL": "#2DD4BF",
    "CH_PANEL": "#0B1220",
}
_LIGHT_CHART = {
    "COLOR_BG": "#FFFFFF",
    "CH_TXT": "#0F172A",
    "CH_DIM": "#64748B",
    "CH_BRD": "#CBD5E1",
    "CH_GRID": "#E2E8F0",
    "CH_INFO": "#0284C7",
    "CH_TEAL": "#0D9488",
    "CH_PANEL": "#FFFFFF",
}


def _apply_chart_theme():
    try:
        from deprem_izleme.config import load_settings
        light = (load_settings().get("appearance") or "dark") == "light"
        globals().update(_LIGHT_CHART if light else _DARK_CHART)
    except Exception:
        pass


_apply_chart_theme()


def _mpl():
    """matplotlib'i tembel yükle (ilk grafik istendiğinde ~1 sn, açılışı yavaşlatmaz)."""
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    return Figure


def _style_ax(ax, title, xlabel="", ylabel=""):
    ax.set_facecolor(COLOR_BG)
    ax.set_title(title, fontsize=11, color=CH_TXT, pad=6, fontweight="bold")
    ax.set_xlabel(xlabel, fontsize=8, color=CH_DIM, labelpad=3)
    ax.set_ylabel(ylabel, fontsize=8, color=CH_DIM, labelpad=3)
    ax.tick_params(colors=CH_DIM, labelsize=7)
    for spine in ax.spines.values():
        spine.set_color(CH_BRD)
    ax.grid(True, alpha=0.12, color=CH_GRID, linewidth=0.3)


def _thin_labels(lbls, max_show=12):
    """Kalabalık eksen etiketlerini seyrelt: (konumlar, etiketler, açı)."""
    n = len(lbls)
    if n <= max_show:
        return list(range(n)), list(lbls), 0
    step = math.ceil(n / max_show)
    idx = list(range(0, n, step))
    return idx, [lbls[i] for i in idx], 45


def _daily_max(quakes):
    daily = {}
    for q in quakes:
        ts = q.get("occurred_at", "")
        if ts:
            day = ts[:10]
            mag = q.get("magnitude") or 0
            if day not in daily or mag > daily[day]:
                daily[day] = mag
    return sorted(daily.items())


def build_risk_trend_figure(width=4, height=2.5, days=30):
    """Risk trendi figürü - Tk gerektirmez (arka plan thread'inde güvenli).

    days>14 ise haftalık geçmiş, değilse seçili aralığın günlük verisi.
    """
    _apply_chart_theme()
    Figure = _mpl()
    fig = Figure(figsize=(width, height), dpi=90, facecolor=COLOR_BG)
    ax = fig.add_subplot(111)

    # Önce haftalık dene (uzun aralıklarda)
    weekly = get_weekly_history(limit=12, region="marmara")
    if days > 14 and weekly and len(weekly) >= 2:
        weekly = sorted(weekly, key=lambda w: (w["year"], w["week"]))
        weeks = [f"W{w['week']}" for w in weekly]
        risks = [w["risk_score"] for w in weekly]
        ax.plot(range(len(weeks)), risks, color=CH_TEAL, linewidth=2, marker="o", markersize=5)
        ax.fill_between(range(len(weeks)), risks, alpha=0.12, color=CH_TEAL)
        ax.set_xticks(range(len(weeks)))
        ax.set_xticklabels(weeks, fontsize=7, rotation=0)
        ax.set_ylim(0, 1)
        _style_ax(ax, "Risk Skoru (Haftalık)", "Hafta", "Risk")
    else:
        # Günlük MAX magnitüd (bar) + güncel risk referans çizgisi
        try:
            from deprem_izleme.aggregation import get_comprehensive_risk_report
            current_risk = get_comprehensive_risk_report()["composite_risk_score"]
        except Exception:
            current_risk = 0.0

        quakes = get_earthquakes(
            since=datetime.now() - timedelta(days=max(days, 1)),
            region="marmara", limit=500
        )
        if quakes:
            sorted_d = _daily_max(quakes)
            if len(sorted_d) >= 1:
                lbls = [d[0][5:] for d in sorted_d]
                mags = [d[1] for d in sorted_d]
                colors = ["#F87171" if m >= 4 else "#FBBF24" if m >= 3 else "#34D399" for m in mags]

                # Ana eksen: magnitüd (eski bug: eksen 0-1'e sabitleniyordu - düzeltildi)
                ax.bar(range(len(lbls)), mags, color=colors, alpha=0.7, width=0.5,
                       edgecolor="white", linewidth=0.3)
                ax.set_ylim(0, max(mags) + 0.5 if mags else 2)
                ax.set_ylabel("Magnitüd", fontsize=8, color=CH_DIM)

                # İkinci eksen: risk referans çizgisi
                ax2 = ax.twinx()
                ax2.axhline(y=current_risk, color=CH_INFO, linewidth=2, linestyle="--", alpha=0.7)
                ax2.text(0.5, min(0.97, max(current_risk + 0.04, 0.08)),
                         f"Risk: {current_risk:.3f}", fontsize=8, color=CH_INFO,
                         ha="left", va="top",
                         bbox=dict(boxstyle="round,pad=0.25", facecolor=COLOR_BG, edgecolor=CH_BRD))
                ax2.set_ylim(0, 1)
                ax2.set_ylabel("Risk", fontsize=8, color=CH_INFO, rotation=270, labelpad=12)
                ax2.tick_params(colors=CH_INFO, labelsize=7, pad=3)

                _xi, _xl, _rot = _thin_labels(lbls)
                ax.set_xticks(_xi)
                ax.set_xticklabels(_xl, fontsize=7, rotation=_rot)
                _style_ax(ax, "Günlük Maks. Magnitüd + Risk", "Gün", "Magnitüd")
            else:
                ax.text(0.5, 0.5, "Henüz yeterli veri yok\n(1+ gün gerekli)", ha="center", va="center",
                        fontsize=9, color="#888", transform=ax.transAxes)
                _style_ax(ax, "Risk Skoru")
        else:
            ax.text(0.5, 0.5, "Henüz veri yok\n(Verileri Çek ile başlayın)", ha="center", va="center",
                    fontsize=9, color="#888", transform=ax.transAxes)
            _style_ax(ax, "Risk Skoru")

    fig.tight_layout(pad=1.5)
    return fig


def build_daily_count_figure(days=30, width=4, height=2.5):
    """Günlük deprem sayısı figürü - Tk gerektirmez."""
    _apply_chart_theme()
    Figure = _mpl()
    fig = Figure(figsize=(width, height), dpi=90, facecolor=COLOR_BG)
    ax = fig.add_subplot(111)

    quakes = get_earthquakes(
        since=datetime.now() - timedelta(days=days),
        region="marmara", limit=1000
    )

    if quakes:
        dates = Counter()
        for q in quakes:
            ts = q.get("occurred_at", "")
            if ts:
                dates[ts[:10]] += 1
        if dates:
            sorted_d = sorted(dates.items())
            lbls = [d[0][5:] for d in sorted_d]
            cnts = [d[1] for d in sorted_d]
            ax.bar(range(len(cnts)), cnts, color="#34D399", alpha=0.7, width=0.6)
            _xi, _xl, _rot = _thin_labels(lbls)
            ax.set_xticks(_xi)
            ax.set_xticklabels(_xl, fontsize=7, rotation=_rot)
            for i, v in enumerate(cnts):
                ax.text(i, v + 0.1, str(v), ha="center", fontsize=6, color=CH_DIM)
        else:
            ax.text(0.5, 0.5, "Veri yok", ha="center", va="center", fontsize=9, color=CH_DIM,
                    transform=ax.transAxes)
    else:
        ax.text(0.5, 0.5, "Veri yok", ha="center", va="center", fontsize=9, color=CH_DIM,
                transform=ax.transAxes)

    _style_ax(ax, "Günlük Deprem Sayısı", "Gün", "Deprem")
    fig.tight_layout(pad=1.5)
    return fig


def _attach_canvas(parent_frame, fig):
    """Figürü Tk'ya bağla - SADECE ana thread'den çağır.

    Değişimde eski figürler temizlenir (clf), yoksa her yenilemede
    megabaytlarca figür bellekte kalır.
    """
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    for w in list(parent_frame.winfo_children()):
        try:
            w.destroy()
        except Exception:
            pass
    for _old in (getattr(parent_frame, "_mpl_figs", None) or []):
        try:
            _old.clf()
        except Exception:
            pass
    try:
        parent_frame._mpl_figs = [fig]
    except Exception:
        pass
    canvas = FigureCanvasTkAgg(fig, master=parent_frame)
    try:
        canvas.get_tk_widget().configure(highlightthickness=0, bd=0)
    except Exception:
        pass
    canvas.draw()
    return canvas, fig


def create_risk_trend_chart(parent_frame, width=4, height=2.5):
    """
    Risk trend grafiği - tercihen haftalık, yoksa günlük.
    """
    return _attach_canvas(parent_frame, build_risk_trend_figure(width, height))


def create_daily_count_chart(parent_frame, days=30, width=4, height=2.5):
    """Günlük deprem sayısı grafiği."""
    return _attach_canvas(parent_frame, build_daily_count_figure(days, width, height))


def build_fmd_figure(width=5.5, height=3.2, days=90):
    """Büyüklük-dağılım (FMD) + Gutenberg-Richter uyumu - Tk gerektirmez."""
    _apply_chart_theme()
    from deprem_izleme.aggregation import calculate_b_value
    Figure = _mpl()
    fig = Figure(figsize=(width, height), dpi=90, facecolor=COLOR_BG)
    ax = fig.add_subplot(111)

    quakes = get_earthquakes(since=datetime.now() - timedelta(days=days),
                             region="marmara", limit=2000)
    mags = sorted([q["magnitude"] for q in quakes if q.get("magnitude")])
    if len(mags) >= 10:
        import math
        b, a, mc = calculate_b_value(mags)
        lo = math.floor(min(mags) * 2) / 2
        hi = math.ceil(max(mags) * 2) / 2
        bins, cum = [], []
        m = lo
        while m <= hi:
            bins.append(round(m, 1))
            cum.append(sum(1 for x in mags if x >= m - 1e-9))
            m += 0.5
        CNT = [sum(1 for x in mags if b - 0.25 <= x < b + 0.25) for b in bins]
        ax.bar(bins, CNT, width=0.42, color=CH_TEAL, alpha=0.55, label="Gözlenen (0.5 dilim)")
        ax.set_yscale("log")
        ax2 = ax.twinx()
        ax2.plot(bins, cum, color="#FBBF24", linewidth=2, marker="o", markersize=4,
                 label="Kümülatif N(≥M)")
        fit = [10 ** (a - b * mm) for mm in bins]
        ax2.plot(bins, fit, color=CH_INFO, linewidth=1.5, linestyle="--",
                 label=f"GR uyumu (b={b:.2f})")
        ax2.axvline(x=mc, color="#F87171", linewidth=1, linestyle=":",
                    label=f"Mc={mc:.1f}")
        ax2.set_yscale("log")
        ax2.set_ylabel("Kümülatif sayı (log)", fontsize=8, color=CH_DIM)
        ax2.tick_params(colors=CH_DIM, labelsize=7)
        for spine in ax2.spines.values():
            spine.set_color(CH_BRD)
        ax.legend(fontsize=7, loc="upper right", facecolor=CH_PANEL,
                  edgecolor=CH_BRD, labelcolor=CH_TXT)
        ax2.legend(fontsize=7, loc="lower right", facecolor=CH_PANEL,
                   edgecolor=CH_BRD, labelcolor=CH_TXT)
        _style_ax(ax, f"Büyüklük Dağılımı (n={len(mags)}, Mc={mc:.1f})",
                  "Büyüklük (M)", "Deprem sayısı (log)")
    else:
        ax.text(0.5, 0.5, "Yetersiz veri (10+ deprem gerekli)", ha="center", va="center",
                fontsize=9, color=CH_DIM, transform=ax.transAxes)
        _style_ax(ax, "Büyüklük Dağılımı")
    fig.tight_layout(pad=1.5)
    return fig


def build_hourly_figure(width=5.5, height=3.2, days=90):
    """Saate göre dağılım - Tk gerektirmez."""
    _apply_chart_theme()
    from deprem_izleme.analysis import hourly_distribution
    Figure = _mpl()
    fig = Figure(figsize=(width, height), dpi=90, facecolor=COLOR_BG)
    ax = fig.add_subplot(111)

    quakes = get_earthquakes(since=datetime.now() - timedelta(days=days),
                             region="marmara", limit=2000)
    hours = hourly_distribution(quakes)
    if sum(hours) > 0:
        colors = ["#FBBF24" if ((6 <= h <= 9) or (18 <= h <= 22)) else CH_TEAL
                  for h in range(24)]
        ax.bar(range(24), hours, color=colors, alpha=0.75, width=0.8)
        ax.set_xticks(range(0, 24, 2))
        ax.set_xlim(-0.6, 23.6)
        _style_ax(ax, f"Saate Göre Dağılım (n={sum(hours)}) — depremin saati olmaz",
                  "Saat (yerel)", "Deprem sayısı")
    else:
        ax.text(0.5, 0.5, "Veri yok", ha="center", va="center",
                fontsize=9, color=CH_DIM, transform=ax.transAxes)
        _style_ax(ax, "Saate Göre Dağılım")
    fig.tight_layout(pad=1.5)
    return fig


def build_depth_figure(width=5.5, height=3.2, days=90):
    """Derinlik dağılımı - Tk gerektirmez."""
    _apply_chart_theme()
    from deprem_izleme.analysis import depth_distribution
    Figure = _mpl()
    fig = Figure(figsize=(width, height), dpi=90, facecolor=COLOR_BG)
    ax = fig.add_subplot(111)

    quakes = get_earthquakes(since=datetime.now() - timedelta(days=days),
                             region="marmara", limit=2000)
    dd = depth_distribution(quakes)
    if dd["n"] > 0:
        lbls = [b["range"] for b in dd["bins"]]
        cnts = [b["count"] for b in dd["bins"]]
        ax.bar(range(len(lbls)), cnts, color=CH_INFO, alpha=0.75, width=0.65)
        ax.set_xticks(range(len(lbls)))
        ax.set_xticklabels(lbls, fontsize=7, rotation=0)
        _style_ax(ax, f"Derinlik Dağılımı — sığ (<20 km) %{dd['shallow_pct']:.0f} (n={dd['n']})",
                  "Derinlik (km)", "Deprem sayısı")
    else:
        ax.text(0.5, 0.5, "Veri yok", ha="center", va="center",
                fontsize=9, color=CH_DIM, transform=ax.transAxes)
        _style_ax(ax, "Derinlik Dağılımı")
    fig.tight_layout(pad=1.5)
    return fig


def build_magtime_figure(width=5.5, height=3.2, days=90):
    """Büyüklük-zaman serisi - Tk gerektirmez."""
    _apply_chart_theme()
    from deprem_izleme.analysis import magnitude_time
    Figure = _mpl()
    fig = Figure(figsize=(width, height), dpi=90, facecolor=COLOR_BG)
    ax = fig.add_subplot(111)

    quakes = get_earthquakes(since=datetime.now() - timedelta(days=days),
                             region="marmara", limit=2000)
    pts = magnitude_time(quakes)
    if len(pts) >= 2:
        import datetime as _dt
        t0 = pts[0][0]
        xs = [(t - t0) / 86400 for t, _ in pts]
        ms = [m for _, m in pts]
        colors = ["#F87171" if m >= 4 else "#FBBF24" if m >= 3 else "#34D399" for m in ms]
        ax.scatter(xs, ms, c=colors, s=[4 + m * 4 for m in ms], alpha=0.75,
                   edgecolors="white", linewidths=0.4)
        d0 = _dt.datetime.fromtimestamp(t0).strftime("%d.%m")
        ax.text(0.02, 0.95, f"başlangıç: {d0}", transform=ax.transAxes,
                fontsize=7, color=CH_DIM, va="top")
        _style_ax(ax, f"Büyüklük-Zaman (n={len(pts)})", "Gün", "Büyüklük (M)")
    else:
        ax.text(0.5, 0.5, "Veri yok", ha="center", va="center",
                fontsize=9, color=CH_DIM, transform=ax.transAxes)
        _style_ax(ax, "Büyüklük-Zaman")
    fig.tight_layout(pad=1.5)
    return fig


def _prep_daily(quakes, days):
    """Günlük gruplanmış (etiket, max) listesi."""
    daily = {}
    for q in quakes:
        ts = q.get("occurred_at", "")
        if ts:
            day = ts[:10]
            mag = q.get("magnitude") or 0
            if day not in daily:
                daily[day] = []
            daily[day].append(mag)
    return sorted(daily.items())


def build_overview_figure(days=7, width=12, height=6):
    """Grafikler sayfası 4'lü genel görünüm - Tk gerektirmez."""
    _apply_chart_theme()
    from collections import Counter
    from deprem_izleme.aggregation import daily_risk_light, calculate_b_value, seismic_energy_joules
    Figure = _mpl()
    fig = Figure(figsize=(width, height), dpi=100, facecolor=COLOR_BG)

    quakes = get_earthquakes(since=datetime.now() - timedelta(days=days),
                             region="marmara", limit=1000)

    # 1. Günlük max + risk
    ax1 = fig.add_subplot(2, 2, 1)
    ax1.set_facecolor(COLOR_BG)
    grouped = _prep_daily(quakes, days)
    if grouped:
        labels = [d[0][5:] for d in grouped]
        maxs = [max(d[1]) for d in grouped]
        colors = ["#F87171" if m >= 4 else "#FBBF24" if m >= 3 else "#34D399" for m in maxs]
        ax1.bar(range(len(maxs)), maxs, color=colors, alpha=0.7, width=0.6,
                edgecolor="white", linewidth=0.3)
        _xi, _xl, _rot = _thin_labels(labels)
        ax1.set_xticks(_xi)
        ax1.set_xticklabels(_xl, rotation=_rot, fontsize=7)
        ax1.set_ylim(0, max(maxs) + 0.5 if maxs else 2)
        ax2 = ax1.twinx()
        risks = [daily_risk_light(mags) for _, mags in grouped]
        ax2.plot(range(len(risks)), risks, color=CH_INFO, linewidth=2,
                 marker="o", markersize=4, alpha=0.8)
        ax2.fill_between(range(len(risks)), risks, alpha=0.1, color=CH_INFO)
        ax2.set_ylim(0, 1)
        ax2.set_ylabel("Risk Skoru", fontsize=7, color=CH_INFO, rotation=270, labelpad=12)
        ax2.tick_params(colors=CH_INFO, labelsize=6, pad=3)
    _style_ax(ax1, "Günlük Maksimum Magnitüd + Risk Skoru", "", "Magnitüd")

    # 2. Günlük sayı
    ax3 = fig.add_subplot(2, 2, 2)
    ax3.set_facecolor(COLOR_BG)
    dates = Counter()
    for q in quakes:
        ts = q.get("occurred_at", "")
        if ts:
            dates[ts[:10]] += 1
    if dates:
        sd = sorted(dates.items())
        lbls = [d[0][5:] for d in sd]
        cnts = [d[1] for d in sd]
        ax3.bar(range(len(cnts)), cnts, color="#34D399", alpha=0.7, width=0.6)
        _xi3, _xl3, _rot3 = _thin_labels(lbls)
        ax3.set_xticks(_xi3)
        ax3.set_xticklabels(_xl3, rotation=_rot3, fontsize=8)
    _style_ax(ax3, "Günlük Deprem Sayısı", "Gün", "Deprem")

    # 3. b-değeri trendi
    ax4 = fig.add_subplot(2, 2, 3)
    ax4.set_facecolor(COLOR_BG)
    if grouped and len(grouped) >= 2:
        b_vals, blbls = [], []
        for day, mags in grouped:
            # Günlük b için en az 10 olay gerekir; az veride varsayılan 1.0
            # çizmek yanıltıcı olur, o günler atlanır (dürüst grafik).
            if len(mags) >= 10:
                bv, _, _ = calculate_b_value(mags)
                b_vals.append(bv)
                blbls.append(day[5:])
        if len(b_vals) >= 2:
            ax4.plot(range(len(b_vals)), b_vals, color=CH_TEAL, linewidth=2.5,
                     marker="o", markersize=5)
            ax4.axhline(y=1.0, color=CH_GRID, linewidth=0.5, linestyle="--", alpha=0.5)
            ax4.fill_between(range(len(b_vals)), b_vals, 1.0, alpha=0.1, color=CH_TEAL)
            _xb, _xlb, _rotb = _thin_labels(blbls)
            ax4.set_xticks(_xb)
            ax4.set_xticklabels(_xlb, rotation=_rotb, fontsize=8)
            ax4.set_ylim(0, max(b_vals) + 0.5 if b_vals else 2)
            for i, v in enumerate(b_vals):
                ax4.text(i, v + 0.05, f"{v:.2f}", ha="center", fontsize=7, color=CH_TEAL)
    _style_ax(ax4, "b-değeri Trendi (Günlük, gün≥10 olay)", "", "b")

    # 4. Enerji
    ax5 = fig.add_subplot(2, 2, 4)
    ax5.set_facecolor(COLOR_BG)
    if grouped:
        elbls = [d[0][5:] for d in grouped]
        energies = [sum(seismic_energy_joules(m) for m in mags) / 1e9 for _, mags in grouped]
        ax5.bar(range(len(energies)), energies, color="#FBBF24", alpha=0.7, width=0.6)
        _xe, _xle, _rote = _thin_labels(elbls)
        ax5.set_xticks(_xe)
        ax5.set_xticklabels(_xle, rotation=_rote, fontsize=8)
        ax5.set_ylabel("GJ", fontsize=9, color=CH_DIM)
        for i, v in enumerate(energies):
            if v > 0:
                ax5.text(i, v + 0.01, f"{v:.1f}", ha="center", fontsize=7, color=CH_DIM)
    _style_ax(ax5, "Günlük Sismik Enerji", "", "")

    fig.tight_layout(pad=2.5)
    return fig


def build_fullscreen_figure(days=7, width=16, height=9):
    """Tam ekran büyük grafik - Tk gerektirmez."""
    _apply_chart_theme()
    from deprem_izleme.aggregation import daily_risk_light
    Figure = _mpl()
    fig = Figure(figsize=(width, height), dpi=100, facecolor=COLOR_BG)
    ax = fig.add_subplot(111)

    quakes = get_earthquakes(since=datetime.now() - timedelta(days=days),
                             region="marmara", limit=1000)
    grouped = _prep_daily(quakes, days)
    if grouped:
        labels = [d[0][5:] for d in grouped]
        maxs = [max(d[1]) for d in grouped]
        colors = ["#F87171" if m >= 4 else "#FBBF24" if m >= 3 else "#34D399" for m in maxs]
        ax.bar(range(len(maxs)), maxs, color=colors, alpha=0.7, width=0.6,
               edgecolor="white", linewidth=0.5)
        _xf, _xlf, _rotf = _thin_labels(labels)
        ax.set_xticks(_xf)
        ax.set_xticklabels(_xlf, rotation=_rotf, fontsize=9)
        ax.set_ylim(0, max(maxs) + 0.5 if maxs else 2)
        risks = [daily_risk_light(mags) for _, mags in grouped]
        ax2 = ax.twinx()
        ax2.plot(range(len(risks)), risks, color=CH_INFO, linewidth=2.5,
                 marker="o", markersize=6, alpha=0.8, label="Risk Skoru")
        ax2.fill_between(range(len(risks)), risks, alpha=0.1, color=CH_INFO)
        ax2.set_ylim(0, 1)
        ax2.set_ylabel("Risk Skoru", fontsize=9, color=CH_INFO, rotation=270, labelpad=14)
        ax2.tick_params(colors=CH_INFO, labelsize=8, pad=3)
    ax.set_title(f"Günlük Maksimum Magnitüd ve Risk Skoru (Son {days} Gün)",
                 fontsize=14, color=CH_TXT, fontweight="bold", pad=8)
    ax.set_ylabel("Magnitüd", fontsize=9, color=CH_DIM)
    ax.set_xlabel("Gün", fontsize=9, color=CH_DIM)
    ax.tick_params(colors=CH_DIM, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(CH_BRD)
    ax.grid(True, alpha=0.1, color=CH_GRID, linewidth=0.3)
    fig.tight_layout(pad=2)
    return fig
