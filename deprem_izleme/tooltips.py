"""
Tooltip/Açıklama sistemi - her metrik yanında soru işareti
"""
import customtkinter as ctk

TOOLTIPS = {
    "b-değeri": (
        "Gutenberg-Richter b-değeri\n\n"
        "log₁₀(N) = a - b·M denklemindeki b değeridir.\n\n"
        "• b ≈ 1.0 : Normal stress seviyesi (stabil)\n"
        "• b < 0.7 : YÜKSEK stress (deprem riski artar)\n"
        "• b > 1.2 : Düşük stress (aktivite normal)\n\n"
        "Dünya ortalaması ~1.0'dır. Düşük b-değeri,\n"
        "bölgede büyük bir deprem öncesi stress\n"
        "birikimini işaret edebilir.\n\n"
        "Kaynak: Schorlemmer et al. (2005), Nature"
    ),
    "a-değeri": (
        "Gutenberg-Richter a-değeri\n\n"
        "log₁₀(N) = a - b·M denklemindeki a değeridir.\n\n"
        "Bölgenin sismik aktivite seviyesini gösterir.\n"
        "Yüksek a = daha fazla deprem aktivitesi.\n"
        "Genellikle 3-6 arası değişir."
    ),
    "M≥4.0 7g": (
        "M≥4.0 Deprem Olasılığı (7 Gün)\n\n"
        "Poisson dağılımına göre önümüzdeki 7 gün\n"
        "içinde M≥4.0 büyüklüğünde bir deprem olma\n"
        "olasılığı.\n\n"
        "Hesap: P = 1 - exp(-λ·t)\n"
        "λ = günlük deprem hızı, t = 7 gün\n\n"
        "Not: Bu istatistiksel bir olasılıktır,\n"
        "kesin bir tahmin DEĞİLDİR."
    ),
    "Son 24h": (
        "Son 24 Saatteki Deprem Sayısı\n\n"
        "Marmara Bölgesi'nde son 24 saat içinde\n"
        "kaydedilen toplam deprem sayısı.\n\n"
        "Normal: 0-5 deprem/gün\n"
        "Yüksek: 5-15 deprem/gün\n"
        "Anormal: 15+ deprem/gün"
    ),
    "Enerji": (
        "Toplam Sismik Enerji\n\n"
        "Seçilen zaman aralığında açığa çıkan\n"
        "toplam sismik enerji (Joule cinsinden).\n\n"
        "Hesap: E = 10^(1.5·M + 4.8)\n"
        "Gutenberg-Richter enerji-magnitüd ilişkisi.\n\n"
        "Referans:\n"
        "• M2.0 → 6.3×10⁷ J\n"
        "• M4.0 → 2.0×10¹⁰ J\n"
        "• M6.0 → 6.3×10¹² J"
    ),
    "Risk Skoru": (
        "Birleşik Risk Skoru (0-1)\n\n"
        "6 bileşenin ağırlıklı ortalaması:\n"
        "• b-değeri anomalisi (%25)\n"
        "• Enerji salınım hızı (%20)\n"
        "• Mmax oranı (%15)\n"
        "• Z-Skor anomali (%15)\n"
        "• Derinlik (%10)\n"
        "• Poisson olasılık (%15)\n\n"
        "Ayrıca fay segment riski ile harmanlanır.\n\n"
        "0.0-0.2: Çok Düşük\n"
        "0.2-0.4: Düşük\n"
        "0.4-0.6: Orta\n"
        "0.6-0.8: Yüksek\n"
        "0.8-1.0: Çok Yüksek"
    ),
    "Beklenen Mmax": (
        "Beklenen Maksimum Magnitüd\n\n"
        "Gutenberg-Richter yasasından hesaplanır:\n"
        "Mmax = a / b\n\n"
        "Mevcut b-değeri ve aktivite seviyesine\n"
        "göre bölgede beklenen en büyük deprem.\n\n"
        "Bu istatistiksel bir tahmindir."
    ),
    "b Anomalisi": (
        "b-değeri Anomalisi\n\n"
        "Mevcut b-değeri ile referans değer (1.0)\n"
        "arasındaki fark: Δb = b - 1.0\n\n"
        "Negatif: Normalden yüksek stress\n"
        "Pozitif: Normalden düşük stress\n\n"
        "Büyük depremler öncesi b-değerinde\n"
        "belirgin düşüş gözlenir (0.95→0.70)."
    ),
    "λ (Lambda)": (
        "Günlük Deprem Hızı (λ)\n\n"
        "Belirli bir magnitüd üzerindeki depremlerin\n"
        "günlük ortalama sayısı.\n\n"
        "λ = N / T\n"
        "N: toplam deprem sayısı\n"
        "T: zaman aralığı (gün)\n\n"
        "Poisson modelinde deprem olasılığını\n"
        "hesaplamak için kullanılır."
    ),
    "Z-Skor": (
        "Aktivite Z-Skoru\n\n"
        "Son dönem deprem aktivitesinin normalden\n"
        "ne kadar saptığını ölçer.\n\n"
        "Z = (son aktivite - geçmiş aktivite) / std\n\n"
        "Z > 2 : Anormal aktivite\n"
        "Z > 3 : Güçlü anomali (öncü olabilir)\n"
        "Z < -2 : Normalden düşük aktivite"
    ),
    "Trend": (
        "Deprem Trend Analizi\n\n"
        "b-değeri ve enerji oranına göre belirlenir:\n\n"
        "INCREASING (Artıyor):\n"
        "b düşüyor, enerji artıyor → risk artışı\n\n"
        "STABLE (Stabil):\n"
        "Normal seviyelerde aktivite\n\n"
        "DECREASING (Azalıyor):\n"
        "b yükseliyor, enerji düşüyor → stress azalışı"
    ),
    "Tekrarlama Aralığı": (
        "Deprem Tekrarlama Aralığı\n\n"
        "Gutenberg-Richter yasasına göre belirli bir\n"
        "magnitüdeki depremin ortalama tekrarlanma\n"
        "süresi.\n\n"
        "T(M) = 1 / 10^(a - b·M) gün\n\n"
        "İstatistiksel ortalamadır, kesin periyot\n"
        "değildir."
    ),
    "Fay Segmenti": (
        "Fay Segmenti Risk Skoru\n\n"
        "Her fay segmenti için ayrı hesaplanır:\n"
        "• Son kırılma yılı (ne kadar eski = riskli)\n"
        "• Kayma hızı (mm/yıl)\n"
        "• Segmente yakın deprem sayısı\n"
        "• En büyük yakın deprem\n"
        "• Segmentin maksimum üretebileceği M\n\n"
        "Tekirdağ segmenti en yüksek riske sahiptir\n"
        "(Kutoğlu, 2025)."
    ),
    "Stres Transferi": (
        "Coulomb Stres Transferi (ΔCFF)\n\n"
        "Bir depremin çevre faylarda yarattığı\n"
        "stress değişimi.\n\n"
        "ΔCFF = Δτ + μ'·Δσn\n"
        "Δτ: kayma stressi değişimi\n"
        "μ': efektif sürtünme katsayısı (0.4)\n"
        "Δσn: normal stress değişimi (+ = açma)\n\n"
        "Pozitif ΔCFF → fayı tetikler\n"
        "Eşik: ~0.1 bar (Stein 1999; aralık tartışmalı: 0.1-0.5)\n\n"
        "Kaynak: King, Stein & Lin (1994)"
    ),
    "Bileşik Risk": (
        "Birleşik Risk Skoru (0-1)\n\n"
        "6 bileşenin ağırlıklı ortalaması:\n"
        "• b-değeri anomalisi (%25)\n"
        "• Enerji salınım hızı (%20)\n"
        "• Mmax oranı (%15)\n"
        "• Z-Skor anomali (%15)\n"
        "• Derinlik (%10)\n"
        "• Poisson olasılık (%15)\n\n"
        "Ağırlıklar uzman seçimidir, geçmiş depremlerle\n"
        "kalibre EDİLMEMİŞTİR — eğilim göstergesidir.\n\n"
        "Ayrıca fay segment riski ile harmanlanır.\n"
        "0.0-0.2: Çok Düşük | 0.2-0.4: Düşük | 0.4-0.6: Orta\n"
        "0.6-0.8: Yüksek | 0.8-1.0: Çok Yüksek"
    ),
    "Gutenberg-Richter": (
        "Gutenberg-Richter Yasası\n\n"
        "log₁₀(N) = a - b·M\n\n"
        "N: belirli magnitüd üzerindeki deprem sayısı\n"
        "M: magnitüd\n"
        "b: b-değeri (stress göstergesi)\n"
        "a: a-değeri (aktivite seviyesi)\n\n"
        "b ≈ 1.0 → normal stress\n"
        "b < 0.7 → yüksek stress (risk artar)\n"
        "b > 1.2 → düşük stress"
    ),
    "Poisson": (
        "Poisson Olasılıkları (zemin hızdan)\n\n"
        "Artçı-kümelenmeden arındırılmış (Gardner-Knopoff 1974)\n"
        "zemin kataloğunun günlük hızı (λ) kullanılır:\n\n"
        "P = 1 - exp(-λ·t)\n"
        "λ: zemin deprem hızı (/gün)\n"
        "t: zaman aralığı (gün)\n\n"
        "Varsayım: zemin depremler bağımsızdır.\n"
        "Zincirleme tetiklenme bu modelde YOKTUR.\n\n"
        "Kaynak: Gardner & Knopoff (1974)"
    ),
    "Trend & Anomali": (
        "Trend ve Anomali Analizi\n\n"
        "b-değeri trendi: b-değerinin zaman içindeki değişimi.\n"
        "Negatif trend (düşen b) = artan stress.\n\n"
        "Z-Skor: Son aktivitenin normalden sapması.\n"
        "Z > 2: anormal aktivite\n"
        "Z > 3: güçlü anomali (öncü olabilir)\n\n"
        "Enerji oranı: Son 30g/90g enerji karşılaştırması.\n"
        "> 1.5x: artan aktivite"
    ),
}


_popover = {"win": None, "bind": None}


def _close_popover(_ev=None):
    w = _popover.get("win")
    _popover["win"] = None
    try:
        if w is not None and w.winfo_exists():
            w.destroy()
    except Exception:
        pass


def _popover_colors():
    try:
        import customtkinter as _ctk
        if _ctk.get_appearance_mode() == "Light":
            return {"bg": "#FFFFFF", "frame": "#F1F5F9", "title": "#0D9488",
                    "text": "#334155", "border": "#DDE5EE"}
    except Exception:
        pass
    return {"bg": "#111826", "frame": "#0D1524", "title": "#2DD4BF",
            "text": "#C6CEDB", "border": "#1E2A3F"}


_dismiss_installed = False


def _install_global_dismiss():
    """Uygulamada herhangi bir yere tıklanınca baloncuğu kapat (tek seferlik kurulum)."""
    global _dismiss_installed
    if _dismiss_installed:
        return
    _dismiss_installed = True
    try:
        import tkinter as _tk

        def _on_any_click(ev=None):
            try:
                pop = _popover.get("win")
                if pop is None:
                    return
                w = ev.widget if ev is not None else None
                while w is not None:
                    if w == pop:
                        return  # baloncuk içine tıklandı
                    try:
                        w = w.master
                    except Exception:
                        break
                _close_popover()
            except Exception:
                pass

        root = _tk._default_root
        if root is not None:
            root.bind_all("<ButtonPress-1>", _on_any_click, add="+")
    except Exception:
        pass


def show_tooltip_popover(widget, key):
    """Düğmenin yanında açılan kompakt açıklama baloncuğu (penceresiz)."""
    import customtkinter as ctk
    _close_popover()
    _install_global_dismiss()
    text = TOOLTIPS.get(key, f"Açıklama bulunamadı: {key}")
    first, _, rest = text.partition("\n")

    tip = ctk.CTkToplevel()
    tip.overrideredirect(True)
    tip.attributes("-topmost", True)
    tip.withdraw()
    c = _popover_colors()
    tip.configure(fg_color=c["border"])
    frame = ctk.CTkFrame(tip, fg_color=c["frame"], corner_radius=8)
    frame.pack(fill="both", expand=True, padx=1, pady=1)
    ctk.CTkLabel(frame, text=first.strip() or key,
                 font=ctk.CTkFont(size=12, weight="bold"),
                 text_color=c["title"]).pack(anchor="w", padx=12, pady=(10, 2))
    body = rest.strip() or text.strip()
    ctk.CTkLabel(frame, text=body, font=ctk.CTkFont(size=10),
                 text_color=c["text"], justify="left", wraplength=270,
                 anchor="w").pack(anchor="w", padx=12, pady=(0, 10))

    tip.update_idletasks()
    bw, bh = 300, min(tip.winfo_reqheight(), 420)
    try:
        sw, sh = tip.winfo_screenwidth(), tip.winfo_screenheight()
    except Exception:
        sw, sh = 1600, 900
    try:
        x = widget.winfo_rootx() - bw + widget.winfo_width()
        y = widget.winfo_rooty() + widget.winfo_height() + 6
    except Exception:
        x, y = sw // 2 - 150, sh // 2 - 100
    x = max(4, min(x, sw - bw - 8))
    y = max(4, min(y, sh - bh - 8))
    tip.geometry(f"{bw}x{bh}+{x}+{y}")
    tip.deiconify()
    _popover["win"] = tip

    def _away(_e=None):
        _close_popover()
    try:
        tip.bind("<FocusOut>", _away)
        tip.bind("<Escape>", _away)
        tip.bind("<Button-1>", _away)
        tip.after(12000, _close_popover)
    except Exception:
        pass


class TooltipButton(ctk.CTkButton):
    """Yanında ? işareti olan, tıklayınca açıklama baloncuğu açan buton."""
    def __init__(self, master, tooltip_key, **kwargs):
        self._key = tooltip_key
        try:
            import customtkinter as _ctk
            light = _ctk.get_appearance_mode() == "Light"
        except Exception:
            light = False
        super().__init__(
            master,
            text="?", width=22, height=20,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#E2E8F0" if light else "#2A3A55",
            hover_color="#CBD5E1" if light else "#3A4F75",
            text_color="#0F766E" if light else "#2DD4BF",
            corner_radius=11,
            command=self._open,
            **kwargs
        )

    def _open(self):
        show_tooltip_popover(self, self._key)


def add_tooltip(parent, key, side="right", padx=(4, 0)):
    """Tooltip butonu ekle."""
    btn = TooltipButton(parent, key)
    btn.pack(side=side, padx=padx)
    return btn
