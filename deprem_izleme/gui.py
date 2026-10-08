"""
Deprem Analiz - Marmara - Modern GUI (CustomTkinter)
Ana Sayfa | Risk Analizi | Tekrarlama | Harita | Geçmiş | Ayarlar
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import queue
import json
import math
import tkinter as _tk
from datetime import datetime, timedelta
from collections import deque

import customtkinter as ctk
from tkinter import messagebox, filedialog

from deprem_izleme.fetcher import fetch_and_store
from deprem_izleme.fetcher_koeri import fetch_koeri
from deprem_izleme.aggregation import (
    get_comprehensive_risk_report, compute_weekly_stats, compute_monthly_stats,
    calculate_b_value, seismic_energy_joules,
)
from deprem_izleme.db import get_earthquakes, get_stats, get_weekly_history, get_monthly_history, insert_earthquake
from deprem_izleme.predictor import EarthquakePredictor
from deprem_izleme.notifier import (
    check_and_alert, send_telegram_message, telegram_available, _load_telegram_config
)
from deprem_izleme.analysis import (get_recurrence_report, build_analysis_prompt,
                                      catalog_span_days, interpret_now, baseline_status)
from deprem_izleme.tooltips import add_tooltip, TOOLTIPS
from deprem_izleme.marmara_canvas import MarmaraMap
from deprem_izleme.config import DAILY_LIMIT
# NOT: charts (matplotlib) bilerek üstte import EDİLMİYOR - açılışı ~1.3 sn
# yavaşlatıyordu. İlk grafik istendiğinde fonksiyon içinde yüklenir.

# --- Theme ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLOR_LOW = "#34D399"
COLOR_MODERATE = "#FBBF24"
COLOR_HIGH = "#FB9236"
COLOR_VERY_HIGH = "#F87171"
COLOR_CRITICAL = "#C084FC"
COLOR_CARD_BG = "#111826"
COLOR_CARD_BORDER = "#1E2A3F"
COLOR_INSET = "#0D1524"
COLOR_SIDEBAR_BG = "#0C111B"
COLOR_MAIN_BG = "#0A0E15"
COLOR_TEXT = "#E6EBF4"
COLOR_TEXT2 = "#93A0B4"
COLOR_ACCENT = "#2DD4BF"
COLOR_ACCENT_DEEP = "#0F766E"
COLOR_SUCCESS = "#34D399"
COLOR_WARNING = "#FBBF24"
COLOR_DANGER = "#F87171"
COLOR_INFO = "#60A5FA"
COLOR_CHART_BG = "#0B1220"
# Arayüz metin/buton renkleri (açık temada üzerine yazılır)
COLOR_BODY = "#C6CEDB"
COLOR_BODY2 = "#B9C2D2"
COLOR_DIM = "#7E8BA0"
COLOR_BTN_SEC_BG = "#182236"
COLOR_BTN_SEC_HOVER = "#1F2C44"
COLOR_ENTRY_BORDER = "#3a3a55"
COLOR_TRACK = "#1B2740"
COLOR_NAV_ACTIVE = "#141C2E"
COLOR_NAV_HOVER = "#1A2438"


def _apply_startup_theme():
    """Açılışta kayıtlı görünümü uygula (koyu/açık). True=dönüş yapıldı."""
    try:
        from deprem_izleme.config import load_settings
        if (load_settings().get("appearance") or "dark") != "light":
            return False
        ctk.set_appearance_mode("light")
        g = globals()
        g.update({
            "COLOR_CARD_BG": "#FFFFFF",
            "COLOR_CARD_BORDER": "#DDE5EE",
            "COLOR_INSET": "#F1F5F9",
            "COLOR_SIDEBAR_BG": "#F8FAFC",
            "COLOR_MAIN_BG": "#EDF1F6",
            "COLOR_TEXT": "#0F172A",
            "COLOR_TEXT2": "#475569",
            "COLOR_ACCENT": "#0D9488",
            "COLOR_ACCENT_DEEP": "#0F766E",
            "COLOR_LOW": "#059669",
            "COLOR_MODERATE": "#CA8A04",
            "COLOR_HIGH": "#C2410C",
            "COLOR_VERY_HIGH": "#DC2626",
            "COLOR_CRITICAL": "#7C3AED",
            "COLOR_SUCCESS": "#059669",
            "COLOR_WARNING": "#B45309",
            "COLOR_DANGER": "#DC2626",
            "COLOR_INFO": "#0284C7",
            "COLOR_BODY": "#334155",
            "COLOR_BODY2": "#475569",
            "COLOR_DIM": "#64748B",
            "COLOR_BTN_SEC_BG": "#FFFFFF",
            "COLOR_BTN_SEC_HOVER": "#F1F5F9",
            "COLOR_ENTRY_BORDER": "#CBD5E1",
            "COLOR_TRACK": "#E2E8F0",
            "COLOR_NAV_ACTIVE": "#E2E8F0",
            "COLOR_NAV_HOVER": "#CBD5E1",
        })
        return True
    except Exception:
        return False


_IS_LIGHT = _apply_startup_theme()

TIME_FILTERS = [
    ("24 Saat", 1),
    ("48 Saat", 2),
    ("1 Hafta", 7),
    ("1 Ay", 30),
    ("3 Ay", 90),
]

REFRESH_INTERVALS = [15, 30, 60, 120, 180, 360]


def friendly_error(ex):
    """Teknik hataları sade dile çevir (detay günlüğe gider)."""
    import traceback as _tb
    try:
        _tb.print_exc()
    except Exception:
        pass
    s = str(ex) if str(ex) else repr(ex)
    first = s.split("\n")[0][:160]
    if "_MEI" in s or "WinError 3" in s:
        return ("Uygulama dosyaları okunamadı. "
                "Uygulamayı kapatıp yeniden açın; sürerse yeniden kurun.")
    low = s.lower()
    if "timeout" in low or "timed out" in low or "max retries" in low \
            or "connection" in low:
        return "Ağ bağlantısı kurulamadı. İnterneti kontrol edip tekrar deneyin."
    if "Günlük API limiti" in s:
        return first
    return f"İşlem başarısız: {first}"


class DepremGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Deprem Analiz - Marmara")
        self.geometry("1360x820")
        self.minsize(1100, 700)
        self._alive = True
        self._refresh_lock = threading.Lock()
        self._ui_queue = queue.Queue()
        self._history_backfilled = False
        self._refreshed_once = False
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.configure(fg_color=COLOR_MAIN_BG)
        self.bind("<Map>", self._on_map_window)
        try:
            import os as _os
            import sys as _sys
            if getattr(_sys, "frozen", False):
                # PyInstaller datas -> sys._MEIPASS (onefile dahil)
                _base = getattr(_sys, "_MEIPASS", _os.path.dirname(_sys.executable))
                _ico = _os.path.join(_base, "icon.ico")
            else:
                _ico = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     "..", "assets", "icon.ico")
            _ico = _os.path.normpath(_ico)
            if _os.path.exists(_ico):
                self.iconbitmap(_ico)
        except Exception:
            pass

        # --- State ---
        self.risk_report = None
        self.prediction = None
        self.earthquakes = []
        self.stats_data = {}
        self.weekly_history = []
        self.monthly_history = []
        self.recurrence_data = []
        self.rec_meta = {}
        self.current_time_filter = 7  # gün

        # Background worker
        self.bg_running = False
        self.bg_thread = None
        self.bg_interval = 60  # dakika
        self._load_api_counter()

        # --- Layout ---
        self.grid_columnconfigure(0, weight=0, minsize=200)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_area()

        self.pages = {}
        self._page_builders = {}
        self._building_pages = set()
        self._build_dashboard()  # Sadece ana sayfayı hemen yap
        self._page_builders = {
            "risk-analiz": self._build_risk_analysis,
            "tekrarlama": self._build_recurrence,
            "harita": self._build_map_page,
            "gecmis": self._build_history,
            "tahmin": self._build_prediction,
            "grafikler": self._build_grafikler,
            "metodoloji": self._build_metodoloji,
            "haberler": self._build_haberler,
            "ayarlar": self._build_settings,
        }
        self.switch_page("ana-sayfa")
        # Test/gelistirme: DEPREM_START_PAGE=harita ile dogrudan sayfada ac
        _start = os.environ.get("DEPREM_START_PAGE", "").strip()
        if _start and _start in self._page_builders:
            self.switch_page(_start)
        # Hızlı açılış: önce kayıtlı veriyi ekrana bas (ağ beklemeden),
        # sayfalar ilk ziyarette kurulur; hafif olanlar boşta önden hazırlanır.
        self._safe_after(300, self.refresh_all)
        self._safe_after(1500, self._startup_fetch_once)
        self._safe_after(2500, self._prebuild_pages)
        self._safe_after(15000, self._refresh_if_stale)
        self._safe_after(250, self._drain_ui_queue)
        self._safe_after(1200, self._maybe_show_welcome)
        self._safe_after(25000, self._update_auto_check)
        try:
            threading.Thread(target=self._early_backfill, daemon=True).start()
        except Exception:
            pass
        try:
            from deprem_izleme.errors import diag
            diag("init tamam")
        except Exception:
            pass

    def _prebuild_pages(self):
        """Hafif sayfaları boşta önden hazırla (ağır grafik/haber hariç)."""
        for name in ("risk-analiz", "tekrarlama", "gecmis", "tahmin",
                     "metodoloji", "ayarlar", "harita"):
            if name in self.pages:
                continue
            try:
                self._page_builders[name]()
            except Exception as ex:
                try:
                    from deprem_izleme.errors import log_error
                    log_error(ex, f"sayfa on-hazirlik: {name}")
                except Exception:
                    pass
        try:
            self.refresh_all()
        except Exception:
            pass

    def _on_page_shown(self, name):
        """Sayfa ilk kez görüntülendiğinde gerekli veriyi çek."""
        try:
            if name == "harita":
                if "harita" in self.pages:
                    self._sync_map_db_layer()
                    if not getattr(self, "_map_live_loaded", False):
                        self._refresh_map_live()
            elif name == "haberler":
                if not getattr(self, "_news_loaded", False):
                    self._refresh_news()
        except Exception:
            pass

    def _load_api_counter(self):
        """Günlük API sayacını kalıcı ayarlardan yükle."""
        try:
            from deprem_izleme.config import load_settings
            import datetime as _dt
            s = load_settings()
            today = _dt.date.today()
            if s.get("api_date") == today.isoformat():
                self.daily_request_count = int(s.get("api_used", 0) or 0)
            else:
                self.daily_request_count = 0
            self.daily_request_date = today
        except Exception:
            self.daily_request_count = 0
            self.daily_request_date = datetime.now().date()

    def _bump_api_use(self, n=1):
        """API sayacını artır, gün döndüyse sıfırla, kalıcı kaydet."""
        import datetime as _dt
        today = _dt.date.today()
        if today != getattr(self, "daily_request_date", today):
            self.daily_request_date = today
            self.daily_request_count = 0
        self.daily_request_count += n
        try:
            from deprem_izleme.config import save_settings
            save_settings({"api_used": self.daily_request_count,
                           "api_date": today.isoformat()})
        except Exception:
            pass
        return self.daily_request_count

    def _startup_fetch_once(self):
        """Açılışta tek seferlik hafif çekiş: SADECE Sismik Harita.

        KOERI bu ağdan yanıt vermiyor (15 sn+ asılıyor); açılışı
        kilitlememesi için startup'ta çağrılmıyor (butonla istenirse çekilir).
        """
        if getattr(self, "_startup_fetched", False):
            return
        self._startup_fetched = True
        self.dash_status.configure(text="📡 Güncel veriler çekiliyor...",
                                   text_color=COLOR_WARNING)
        threading.Thread(target=self._startup_fetch_worker, daemon=True).start()

    def _startup_fetch_worker(self):
        try:
            try:
                from deprem_izleme.errors import diag
                diag("fetch worker basladi")
            except Exception:
                pass
            c = fetch_and_store(days_back=3, min_magnitude=0.0)
            self._bump_api_use()
            self._post_ui( self.refresh_all)
            self._post_ui(lambda: self.dash_status.configure(
                text=f"✅ Güncel: {c} yeni deprem" if c else "✅ Veriler güncel",
                text_color=COLOR_SUCCESS))
        except Exception as e:
            _emsg = friendly_error(e)
            self._post_ui(lambda e=_emsg: self.dash_status.configure(
                text=f"Çekme hatası (kayıtlı veri gösteriliyor): {e}",
                text_color=COLOR_DANGER))

    # ================================================================
    # SIDEBAR
    # ================================================================

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=COLOR_SIDEBAR_BG, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_rowconfigure(8, weight=1)

        tf = ctk.CTkFrame(sb, fg_color="transparent")
        tf.pack(fill="x", padx=18, pady=(25, 5))
        self._logo_img = None
        try:
            from PIL import Image as _PILImage
            _lp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "assets", "icon.png")
            if getattr(sys, "frozen", False):
                _base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
                _lp = os.path.join(_base, "icon.png")
            if os.path.exists(os.path.normpath(_lp)):
                self._logo_img = ctk.CTkImage(
                    light_image=_PILImage.open(os.path.normpath(_lp)), size=(36, 36))
        except Exception:
            self._logo_img = None
        if self._logo_img is not None:
            ctk.CTkLabel(tf, text="", image=self._logo_img).pack(side="left", padx=(0, 10))
        tt = ctk.CTkFrame(tf, fg_color="transparent")
        tt.pack(side="left")
        ctk.CTkLabel(tt, text="Deprem Analiz", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=COLOR_TEXT).pack(anchor="w")
        ctk.CTkLabel(tt, text="Marmara Bölgesi · Risk Analizi", font=ctk.CTkFont(size=11),
                     text_color=COLOR_ACCENT).pack(anchor="w", pady=(2, 14))

        self.nav_btns = {}
        groups = [
            ("İzleme", [("ana-sayfa", "⌂  Ana Sayfa"),
                        ("harita", "◉  Harita"),
                        ("haberler", "☰  Haberler")]),
            ("Analiz", [("risk-analiz", "◈  Risk Analizi"),
                        ("tekrarlama", "↻  Tekrarlama"),
                        ("gecmis", "◷  Geçmiş"),
                        ("tahmin", "◐  Tahmin"),
                        ("grafikler", "▦  Grafikler")]),
            ("Bilgi", [("metodoloji", "∑  Metodoloji")]),
            ("Sistem", [("ayarlar", "⚙  Ayarlar")]),
        ]
        for gi, (gname, items) in enumerate(groups):
            ctk.CTkLabel(sb, text=gname.upper(), font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=COLOR_TEXT2).pack(anchor="w", padx=18,
                                                      pady=(14 if gi else 4, 2))
            for key, label in items:
                btn = ctk.CTkButton(
                    sb, text=label,
                    font=ctk.CTkFont(size=12),
                    fg_color="transparent", hover_color=COLOR_NAV_HOVER,
                    text_color=COLOR_TEXT, anchor="w",
                    height=32, corner_radius=8, border_width=0,
                    command=lambda k=key: self.switch_page(k)
                )
                btn.pack(fill="x", padx=8, pady=1)
                self.nav_btns[key] = btn

        # Sidebar footer
        div2 = ctk.CTkFrame(sb, fg_color=COLOR_CARD_BORDER, height=1, corner_radius=0)
        div2.pack(fill="x", padx=18, pady=(10, 8))
        sf = ctk.CTkFrame(sb, fg_color="transparent")
        sf.pack(fill="x", padx=18, pady=(0, 15))
        sf.grid_columnconfigure(0, weight=1)

        self.sidebar_status = ctk.CTkLabel(
            sf, text="Son güncelleme: —",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT
        )
        self.sidebar_status.pack(anchor="w", pady=(0, 5))

        self.sidebar_bar = ctk.CTkProgressBar(
            sf, height=3, corner_radius=2,
            fg_color=COLOR_TRACK, progress_color=COLOR_LOW
        )
        self.sidebar_bar.pack(fill="x", pady=(0, 3))
        self.sidebar_bar.set(0)

        self.sidebar_risk_label = ctk.CTkLabel(
            sf, text="Risk: —", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLOR_TEXT
        )
        self.sidebar_risk_label.pack(anchor="w", pady=(0, 2))

        self.sidebar_bg_label = ctk.CTkLabel(
            sf, text="", font=ctk.CTkFont(size=10),
            text_color=COLOR_TEXT2
        )
        self.sidebar_bg_label.pack(anchor="w")

    # ================================================================
    # MAIN AREA
    # ================================================================

    def _build_main_area(self):
        self.main = ctk.CTkFrame(self, fg_color=COLOR_MAIN_BG, corner_radius=0)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(0, weight=1)

    def _page_frame(self):
        f = ctk.CTkFrame(self.main, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)
        return f

    def _show_only(self, name):
        # Tek görünür sayfa kuralı: hedef öne alınır, diğerleri grid'den
        # çıkarılır. (Hepsini mapped bırakmak sayfa yığınlaşmasına ve
        # "tıklıyorum açılmıyor" hissine yol açıyordu.)
        for pname, frame in self.pages.items():
            if pname == name:
                try:
                    frame.grid(row=0, column=0, sticky="nsew")
                except Exception:
                    pass
                try:
                    frame.tkraise()
                except Exception:
                    pass
            else:
                try:
                    frame.grid_remove()
                except Exception:
                    pass

    def _safe_after(self, ms, func):
        """Kapanışa dayanıklı after: ölü gövdeye zamanlama yapmaz."""
        if not getattr(self, "_alive", True):
            return None
        try:
            return _tk.Misc.after(self, ms, func)
        except Exception:
            return None

    def _post_ui(self, func):
        """Worker thread'dan ana thread'e güvenli iş gönder (Tk thread-güvenli
        değildir; doğrudan after/configure çağrısı yarışta kaybolabilir)."""
        try:
            self._ui_queue.put(func)
        except Exception:
            pass

    def _drain_ui_queue(self):
        """Ana thread yoklayıcısı: kuyruktaki UI işlerini sırayla çalıştır."""
        try:
            while True:
                try:
                    func = self._ui_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    func()
                except AttributeError:
                    # Henüz kurulmamış sayfanın widget'ı (lazy) — sessiz geç;
                    # sayfa açılınca kendi yenilemesini yapar.
                    pass
                except Exception as ex:
                    try:
                        from deprem_izleme.errors import log_error
                        log_error(ex, "ui_queue")
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            try:
                if getattr(self, "_alive", False):
                    self._safe_after(250, self._drain_ui_queue)
            except Exception:
                pass

    def _maybe_backfill(self):
        """Geçmiş tablolarını doldur; deprem sayısı artmışsa tekrar dene.
        (Taze kurulumda ilk yenileme boş DB'ye denk gelebilir; bayrak + sayı
        takibiyle veri gelince tamamlanır.)"""
        with self._refresh_lock:
            try:
                from deprem_izleme.db import get_stats
                from deprem_izleme.aggregation import backfill_history
                nq = 0
                try:
                    nq = int(get_stats(region="marmara").get("total", 0) or 0)
                except Exception:
                    pass
                if self._history_backfilled and nq == getattr(self, "_history_bf_count", -1):
                    return
                w, m = backfill_history(weeks=26, months=12, region="marmara")
                self._history_backfilled = True
                self._history_bf_count = nq
                try:
                    from deprem_izleme.errors import diag
                    diag(f"backfill tamam: {nq} deprem -> {w} hafta, {m} ay")
                except Exception:
                    pass
            except Exception as ex:
                try:
                    from deprem_izleme.errors import log_error
                    log_error(ex, "backfill")
                except Exception:
                    pass

    def _early_backfill(self):
        """Açılışta ağ beklemeden geçmişi doldur (yenileme çalışanını beklemez)."""
        self._maybe_backfill()

    def _refresh_if_stale(self):
        """Zamanlayıcı tetiklemeli yenileme: ağ takılsa bile ekran tazelenir."""
        try:
            if not self._refreshed_once:
                self.refresh_all()
        except Exception:
            pass

    def _on_map_window(self, _e=None):
        """Pencere geri açıldığında boyamayı tazele (siyah flaşları azaltır)."""
        try:
            self.update_idletasks()
        except Exception:
            pass

    def _on_close(self):
        """Temiz kapanış: arka plan işlerini durdur, sonra kapat."""
        self._alive = False
        self.bg_running = False
        try:
            self.destroy()
        except Exception:
            pass

    def _fast_scroll(self, root, mult=12):
        """Fare tekerleği hızlandırma (CTkScrollableFrame varsayılanı yavaştır).

        İçerik oranına göre kayar (notch başına ~%3.5) ve varsayılan
        işleyiciyi durdurur (çift-kayma/sarsıntı olmaz).
        """
        try:
            import customtkinter as _ctk
        except Exception:
            return

        def _bind_tree(w, canvas):
            try:
                def _on_wheel(e, c=canvas):
                    try:
                        first, _ = c.yview()
                        c.yview_moveto(max(0.0, min(1.0, first - (e.delta / 120) * 0.035)))
                    except Exception:
                        pass
                    return "break"
                w.bind("<MouseWheel>", _on_wheel)
            except Exception:
                pass
            try:
                for ch in w.winfo_children():
                    _bind_tree(ch, canvas)
            except Exception:
                pass

        def _walk(w):
            try:
                if isinstance(w, _ctk.CTkScrollableFrame):
                    try:
                        _bind_tree(w, w._parent_canvas)
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                for ch in w.winfo_children():
                    _walk(ch)
            except Exception:
                pass
        _walk(root)

    def _darken_hex(self, hexcolor, f=0.82):
        """Düz renk butonlar için koyu hover tonu üret."""
        try:
            h = str(hexcolor).lstrip("#")
            if len(h) != 6:
                return hexcolor
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            return f"#{int(r * f):02X}{int(g * f):02X}{int(b * f):02X}"
        except Exception:
            return hexcolor

    def _polish_button_hovers(self, root):
        """Hover rengi atanmamış butonlara tema uyumlu hover ver (tek seferlik)."""
        try:
            import customtkinter as ctk
            for w in root.winfo_children():
                try:
                    self._polish_button_hovers(w)
                except Exception:
                    pass
                try:
                    if isinstance(w, ctk.CTkButton) and not getattr(w, "_hover_polished", False):
                        fg = w.cget("fg_color")
                        if isinstance(fg, (tuple, list)):
                            w._hover_polished = True
                            continue  # temalı renk: varsayılan hover kalsın
                        if fg == "transparent":
                            w.configure(hover_color=COLOR_NAV_HOVER)
                        elif isinstance(fg, str) and fg.startswith("#"):
                            w.configure(hover_color=self._darken_hex(fg))
                        w._hover_polished = True
                except Exception:
                    pass
        except Exception:
            pass

    def switch_page(self, name):
        # Anında geri bildirim: seçili menüyü önce işaretle (kurulum sürse bile
        # tıklamanın alındığı belli olur).
        try:
            for key, btn in self.nav_btns.items():
                if key == name:
                    btn.configure(fg_color=COLOR_ACCENT_DEEP, text_color="#FFFFFF")
                else:
                    btn.configure(fg_color="transparent", text_color=COLOR_TEXT)
        except Exception:
            pass
        if name not in self.pages and name in getattr(self, "_page_builders", {}):
            if name in getattr(self, "_building_pages", set()):
                return
            self._building_pages.add(name)
            had = name in self.pages
            try:
                import time as _t
                _t0 = _t.perf_counter()
                self._page_builders[name]()
                _dur = _t.perf_counter() - _t0
                if _dur > 1.5:
                    try:
                        from deprem_izleme.errors import log_error
                        log_error(RuntimeError(f"yavas sayfa kurulumu: {name} {_dur:.1f}sn"),
                                  "switch_page")
                    except Exception:
                        pass
            except Exception as ex:
                try:
                    from deprem_izleme.errors import log_error
                    log_error(ex, f"sayfa kurulumu: {name}")
                except Exception:
                    pass
                if not had:
                    self.pages.pop(name, None)
                return
            finally:
                try:
                    self._building_pages.discard(name)
                except Exception:
                    pass
        if name not in self.pages:
            return  # sayfa henüz kurulmadıysa sessizce yoksay
        self._show_only(name)
        try:
            self._fast_scroll(self.pages[name])
        except Exception:
            pass
        try:
            self._polish_button_hovers(self)
        except Exception:
            pass
        try:
            self._on_page_shown(name)
        except Exception as ex:
            try:
                from deprem_izleme.errors import log_error
                log_error(ex, f"sayfa gosterimi: {name}")
            except Exception:
                pass

    # ================================================================
    # BUILD ALL PAGES
    # ================================================================

    def _build_all_pages(self):
        self._build_dashboard()
        self._build_risk_analysis()
        self._build_recurrence()
        self._build_map_page()
        self._build_history()
        self._build_prediction()
        self._build_metodoloji()
        self._build_grafikler()
        self._build_haberler()
        self._build_settings()

    # ---------------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------------

    def _risk_color(self, s):
        if s >= 0.8: return COLOR_CRITICAL
        if s >= 0.6: return COLOR_HIGH
        if s >= 0.4: return COLOR_MODERATE
        return COLOR_LOW

    def _warn_color(self, lv):
        return {"red": COLOR_DANGER, "orange": COLOR_WARNING,
                "yellow": COLOR_MODERATE, "green": COLOR_LOW}.get(lv, COLOR_TEXT)

    def _warn_tr(self, lv):
        return {"red": "KIRMIZI", "orange": "TURUNCU",
                "yellow": "SARI", "green": "YEŞİL"}.get(lv, str(lv).upper())

    def _trend_tr(self, t):
        return {"increasing": "ARTIYOR", "stable": "STABİL",
                "decreasing": "AZALIYOR"}.get(t, str(t).upper())

    def _make_card(self, parent, title, **grid_kw):
        c = ctk.CTkFrame(parent, fg_color=COLOR_CARD_BG, corner_radius=10,
                         border_width=1, border_color=COLOR_CARD_BORDER)
        ctk.CTkLabel(c, text=title, font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLOR_TEXT).pack(anchor="w", padx=14, pady=(12, 6))
        return c

    def _card_field(self, parent, label, row, col=0, sticky="ew", pady=2):
        """Return (container, value_label) for a labelled field."""
        f = ctk.CTkFrame(parent, fg_color=COLOR_INSET, corner_radius=6,
                         border_width=1, border_color=COLOR_CARD_BORDER)
        f.grid(row=row, column=col, sticky=sticky, padx=5, pady=pady)
        ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=9),
                     text_color=COLOR_TEXT2).pack(anchor="w", padx=10, pady=(6, 0))
        vl = ctk.CTkLabel(f, text="—", font=ctk.CTkFont(size=13, weight="bold"),
                          text_color=COLOR_TEXT)
        vl.pack(anchor="w", padx=10, pady=(0, 6))
        return f, vl

    def _header(self, page, title, sub=""):
        ctk.CTkLabel(page, text=title, font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=COLOR_TEXT).pack(anchor="w", padx=28, pady=(22, 2))
        if sub:
            ctk.CTkLabel(page, text=sub, font=ctk.CTkFont(size=11),
                         text_color=COLOR_TEXT2).pack(anchor="w", padx=28, pady=(0, 8))
        div = ctk.CTkFrame(page, fg_color=COLOR_CARD_BORDER, height=1, corner_radius=0)
        div.pack(fill="x", padx=28, pady=(0, 10))

    # ================================================================
    # 1. DASHBOARD
    # ================================================================

    def _build_dashboard(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color="transparent")
        p.grid_columnconfigure(0, weight=1)
        self.pages["ana-sayfa"] = p

        self._header(p, "Ana Sayfa", "Marmara Bölgesi Güncel Deprem Durumu")

        # Zaman filtresi
        tf = ctk.CTkFrame(p, fg_color="transparent")
        tf.pack(fill="x", padx=28, pady=(0, 10))
        ctk.CTkLabel(tf, text="Zaman Aralığı:", font=ctk.CTkFont(size=11),
                     text_color=COLOR_TEXT2).pack(side="left", padx=(0, 8))
        self.time_segment = ctk.CTkSegmentedButton(
            tf, values=[t[0] for t in TIME_FILTERS],
            font=ctk.CTkFont(size=11), selected_color=COLOR_ACCENT_DEEP,
            command=self._on_time_filter
        )
        self.time_segment.pack(side="left")
        self.time_segment.set("1 Hafta")

        self.theme_segment_dash = ctk.CTkSegmentedButton(
            tf, values=["Koyu", "Açık"], font=ctk.CTkFont(size=11),
            selected_color=COLOR_ACCENT_DEEP, command=self._on_theme_dashboard, height=28)
        self.theme_segment_dash.pack(side="right")
        try:
            from deprem_izleme.config import load_settings as _lth
            self.theme_segment_dash.set("Açık" if _lth().get("appearance") == "light" else "Koyu")
        except Exception:
            self.theme_segment_dash.set("Koyu")

        # Risk gauge kartı
        rg = self._make_card(p, "Risk Göstergesi")
        rg.pack(fill="x", padx=28, pady=4)

        gauge_frame = ctk.CTkFrame(rg, fg_color="transparent")
        gauge_frame.pack(fill="x", padx=14, pady=(0, 14))

        self.risk_gauge = ctk.CTkProgressBar(
            gauge_frame, height=18, corner_radius=8,
            fg_color=COLOR_TRACK, progress_color=COLOR_LOW
        )
        self.risk_gauge.pack(fill="x", pady=(5, 2))

        gfs = ctk.CTkFrame(gauge_frame, fg_color="transparent")
        gfs.pack(fill="x", pady=(8, 0))
        self.risk_gauge_label = ctk.CTkLabel(
            gfs, text="Risk: 0.00 (HESAPLANIYOR)",
            font=ctk.CTkFont(size=15, weight="bold"), text_color=COLOR_TEXT
        )
        self.risk_gauge_label.pack(side="left")
        self.risk_chip = ctk.CTkFrame(gfs, fg_color=COLOR_LOW, corner_radius=10)
        self.risk_chip.pack(side="right", padx=(8, 0))
        self.risk_gauge_level = ctk.CTkLabel(
            self.risk_chip, text="—", font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#FFFFFF"
        )
        self.risk_gauge_level.pack(padx=10, pady=2)

        # "Şu an ne diyor?" - sade dil özeti
        self.now_label = ctk.CTkLabel(p, text="Veriler yükleniyor...",
                                      font=ctk.CTkFont(size=11), text_color=COLOR_TEXT2,
                                      justify="left", wraplength=1000)
        self.now_label.pack(anchor="w", padx=28, pady=(0, 6))

        # 4 metrik kartı
        mf = ctk.CTkFrame(p, fg_color="transparent")
        mf.pack(fill="x", padx=28, pady=4)
        mf.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.metric_widgets = {}
        for i, (title, unit) in enumerate([
            ("b-değeri", ""), ("M≥4.0 7g", "olasılık"),
            ("Son 24h", "deprem"), ("Enerji", "")
        ]):
            card = ctk.CTkFrame(mf, fg_color=COLOR_INSET, corner_radius=8,
                                border_width=1, border_color=COLOR_CARD_BORDER)
            card.grid(row=0, column=i, sticky="ew", padx=4, pady=2)
            th = ctk.CTkFrame(card, fg_color="transparent")
            th.pack(fill="x", padx=10, pady=(8, 0))
            ctk.CTkLabel(th, text=title, font=ctk.CTkFont(size=9),
                         text_color=COLOR_TEXT2).pack(side="left")
            add_tooltip(th, title, side="right", padx=(4, 0))
            val = ctk.CTkLabel(card, text="—", font=ctk.CTkFont(size=20, weight="bold"),
                               text_color=COLOR_TEXT)
            val.pack(anchor="w", padx=10, pady=(0, 0))
            ctk.CTkLabel(card, text=unit, font=ctk.CTkFont(size=8),
                         text_color=COLOR_TEXT2).pack(anchor="w", padx=10, pady=(0, 6))
            self.metric_widgets[title] = val

        # Orta: durum + butonlar
        mid = ctk.CTkFrame(p, fg_color="transparent")
        mid.pack(fill="x", padx=28, pady=4)

        # Status labels
        self.status_widgets = {}
        for label in ["Trend", "Uyarı", "Deprem Sayısı", "Son Deprem"]:
            f = ctk.CTkFrame(mid, fg_color=COLOR_INSET, corner_radius=6,
                             border_width=1, border_color=COLOR_CARD_BORDER)
            f.pack(side="left", fill="x", expand=True, padx=3)
            ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=8),
                         text_color=COLOR_TEXT2).pack(anchor="w", padx=8, pady=(5, 0))
            vl = ctk.CTkLabel(f, text="—", font=ctk.CTkFont(size=11),
                              text_color=COLOR_TEXT)
            vl.pack(anchor="w", padx=8, pady=(0, 5))
            self.status_widgets[label] = vl

        # Buttons row
        bf = ctk.CTkFrame(p, fg_color="transparent")
        bf.pack(fill="x", padx=28, pady=(6, 0))
        ctk.CTkButton(bf, text="Verileri Çek ve Güncelle", font=ctk.CTkFont(size=11),
                      fg_color=COLOR_ACCENT_DEEP, hover_color="#0D9488",
                      command=self.do_fetch_and_refresh, height=30, width=150).pack(side="left", padx=(0, 6))
        ctk.CTkButton(bf, text="Haritada Göster", font=ctk.CTkFont(size=11),
                      fg_color=COLOR_BTN_SEC_BG, hover_color=COLOR_BTN_SEC_HOVER, text_color=COLOR_TEXT, border_width=1,
                      border_color=COLOR_CARD_BORDER,
                      command=lambda: self.switch_page("harita"), height=30, width=130).pack(side="left", padx=6)
        ctk.CTkButton(bf, text="AI Analizi", font=ctk.CTkFont(size=11),
                      fg_color=COLOR_BTN_SEC_BG, hover_color=COLOR_BTN_SEC_HOVER, text_color=COLOR_TEXT, border_width=1,
                      border_color=COLOR_CARD_BORDER,
                      command=self.copy_ai_analysis, height=30, width=120).pack(side="left", padx=6)

        self.dash_status = ctk.CTkLabel(p, text="", font=ctk.CTkFont(size=10),
                                         text_color=COLOR_TEXT2)
        self.dash_status.pack(anchor="w", padx=28, pady=2)

        # Grafikler
        chart_frame = ctk.CTkFrame(p, fg_color="transparent")
        chart_frame.pack(fill="x", padx=28, pady=4)
        chart_frame.grid_columnconfigure(0, weight=1)
        chart_frame.grid_columnconfigure(1, weight=1)

        self.risk_chart_frame = ctk.CTkFrame(chart_frame, fg_color=COLOR_CARD_BG, corner_radius=8,
                                                 border_width=1, border_color=COLOR_CARD_BORDER)
        self.risk_chart_frame.grid(row=0, column=0, sticky="nsew", padx=3)
        self.risk_chart_frame.grid_columnconfigure(0, weight=1)
        self.risk_chart_frame.grid_rowconfigure(0, weight=1)
        self._chart_placeholder(self.risk_chart_frame)

        self.count_chart_frame = ctk.CTkFrame(chart_frame, fg_color=COLOR_CARD_BG, corner_radius=8,
                                                  border_width=1, border_color=COLOR_CARD_BORDER)
        self.count_chart_frame.grid(row=0, column=1, sticky="nsew", padx=3)
        self.count_chart_frame.grid_columnconfigure(0, weight=1)
        self.count_chart_frame.grid_rowconfigure(0, weight=1)
        self._chart_placeholder(self.count_chart_frame)

        self.risk_canvas = None
        self.count_canvas = None

        # Deprem listesi
        dl = self._make_card(p, "Deprem Listesi")
        dl.pack(fill="both", expand=True, padx=28, pady=(4, 20))

        self.quake_scroll = ctk.CTkScrollableFrame(dl, fg_color="transparent", corner_radius=0)
        self.quake_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _on_time_filter(self, choice):
        mapping = {t[0]: t[1] for t in TIME_FILTERS}
        self.current_time_filter = mapping.get(choice, 7)
        self.refresh_all()

    # ================================================================
    # 2. RISK ANALYSIS
    # ================================================================

    def _build_risk_analysis(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color="transparent")
        p.grid_columnconfigure(0, weight=1)
        self.pages["risk-analiz"] = p
        self._header(p, "Risk Analizi", "Bilimsel metriklerle deprem risk değerlendirmesi")

        sections = [
            ("Bileşik Risk", ["Risk Skoru", "Risk Seviyesi", "Uyarı Seviyesi", "b Anomalisi"], 4),
            ("Gutenberg-Richter", ["b-değeri", "b-σ", "Mc", "a-değeri", "Beklenen Mmax", "Gözlenen Mmax"], 3),
            ("Poisson", ["λ M≥3.0 (/gün)", "λ M≥4.0 (/gün)", "λ M≥4.0 zemin", "P(M≥4.0) 7gün", "P(M≥4.0) 30gün"], 3),
            ("Enerji", ["Toplam Enerji", "TNT Eşdeğeri"], 2),
            ("Trend & Anomali", ["b-trendi", "Z-Skor", "Trend Yönü", "Enerji Oranı"], 4),
        ]

        self.risk_sections = {}
        for stitle, fields, cols in sections:
            card = self._make_card(p, stitle)
            card.pack(fill="x", padx=28, pady=5)
            # Section tooltip
            add_tooltip(card, stitle, side="right", padx=(4, 14))
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=10, pady=(0, 12))
            for i in range(cols):
                inner.grid_columnconfigure(i, weight=1)
            labels = {}
            for i, f in enumerate(fields):
                _, vl = self._card_field(inner, f, i // cols, i % cols)
                labels[f] = vl
            self.risk_sections[stitle] = labels

        # Fay Segmentleri karti
        fault_card = self._make_card(p, "Fay Segmentleri - Marmara Denizi")
        fault_card.pack(fill="x", padx=28, pady=5)
        self.fault_header_frame = ctk.CTkFrame(fault_card, fg_color="transparent")
        self.fault_header_frame.pack(fill="x", padx=14, pady=(0, 6))
        self.fault_legend = ctk.CTkLabel(self.fault_header_frame,
            text="Her segmentin risk skoru, kırılma yılı, kayma hızı ve yakın deprem aktivitesine göre hesaplanır.",
            font=ctk.CTkFont(size=9), text_color=COLOR_TEXT2, justify="left")
        self.fault_legend.pack(anchor="w")
        self.fault_scores_frame = ctk.CTkFrame(fault_card, fg_color="transparent")
        self.fault_scores_frame.pack(fill="x", padx=14, pady=(0, 14))
        self.fault_labels = {}

    # ================================================================
    # 3. RECURRENCE
    # ================================================================

    def _build_recurrence(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color="transparent")
        p.grid_columnconfigure(0, weight=1)
        self.pages["tekrarlama"] = p
        self._header(p, "Tekrarlama Aralıkları",
                     "Gutenberg-Richter bazlı farklı magnitüdlerin beklenen tekrarlama periyotları")

        self.rec_meta_label = ctk.CTkLabel(p, text="", font=ctk.CTkFont(size=10),
                                          text_color=COLOR_TEXT2)
        self.rec_meta_label.pack(anchor="w", padx=28, pady=(0, 4))

        self.rec_card = self._make_card(p, "Tekrarlama Periyotları")
        self.rec_card.pack(fill="x", padx=28, pady=5)

        self.rec_inner = ctk.CTkFrame(self.rec_card, fg_color="transparent")
        self.rec_inner.pack(fill="x", padx=10, pady=(0, 12))

        self.rec_labels = {}
        self._rebuild_rec_table()

        # Açıklama
        info = ctk.CTkFrame(p, fg_color=COLOR_CARD_BG, corner_radius=10)
        info.pack(fill="x", padx=28, pady=8)
        ctk.CTkLabel(info, text="Nasıl Hesaplanır?",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLOR_ACCENT).pack(anchor="w", padx=14, pady=(12, 4))
        ctk.CTkLabel(info, text=
            "Gutenberg-Richter Yasası: log₁₀(N) = a - b·M\n"
            "Tekrarlama Aralığı: T(M) = T_obs / 10^(a - b·M)\n"
            "(T_obs: kataloğun zaman genişliği, gün)\n"
            "b-değeri ≈1.0 görece stabil, <0.7 yüksek stress göstergesidir.\n"
            "Değerler yukarıdaki tabloya güncel katalogdan hesaplanır.\n"
            "UYARI: Kısa katalogdan (30 gün) M≥6-7 dışdeğerlemesi mertebe\n"
            "tahminidir; belirsizlik ±1 mertebeyi bulur.",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT, justify="left"
        ).pack(anchor="w", padx=14, pady=(0, 12))

    def _rebuild_rec_table(self):
        for w in self.rec_inner.winfo_children():
            w.destroy()

        headers = ["Magnitüd", "Tekrarlama", "Yılda Beklenen"]
        for i, h in enumerate(headers):
            ctk.CTkLabel(self.rec_inner, text=h, font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=COLOR_ACCENT).grid(row=0, column=i, padx=10, pady=(0, 4), sticky="w")

        for row_idx in range(11):
            for col in range(3):
                vl = ctk.CTkLabel(self.rec_inner, text="—", font=ctk.CTkFont(size=11),
                                  text_color=COLOR_TEXT)
                vl.grid(row=row_idx + 1, column=col, padx=10, pady=1, sticky="w")
            self.rec_labels[row_idx] = [None] * 3

    # ================================================================
    # 4. MAP PAGE
    # ================================================================

    def _build_map_page(self):
        p = ctk.CTkFrame(self.main, fg_color="transparent")
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(2, weight=1)
        self.pages["harita"] = p

        hf = ctk.CTkFrame(p, fg_color="transparent")
        hf.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 4))
        hf.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hf, text="Deprem Haritası", font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=COLOR_TEXT).pack(anchor="w")
        ctk.CTkLabel(hf, text="Gerçek kıyı çizgileri ve fay segmentleri — çevrimdışı harita, canlı katmanlar",
                     font=ctk.CTkFont(size=10), text_color=COLOR_TEXT2).pack(anchor="w")

        # Araç çubuğu
        tb = ctk.CTkFrame(p, fg_color=COLOR_CARD_BG, corner_radius=10,
                          border_width=1, border_color=COLOR_CARD_BORDER)
        tb.grid(row=1, column=0, sticky="ew", padx=28, pady=(8, 0))
        tb.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(tb, text="Aralık:", font=ctk.CTkFont(size=11),
                     text_color=COLOR_TEXT2).grid(row=0, column=0, padx=(14, 6), pady=10, sticky="w")
        self.map_time_segment = ctk.CTkSegmentedButton(
            tb, values=["24 Saat", "7 Gün", "14 Gün", "30 Gün"], font=ctk.CTkFont(size=11),
            selected_color=COLOR_ACCENT_DEEP, command=self._on_map_time)
        self.map_time_segment.grid(row=0, column=1, padx=6, pady=10, sticky="w")
        self.map_time_segment.set("7 Gün")
        self.map_days = 7

        self.map_switches = {}
        for i, (key, label) in enumerate([("uygulama", "Uygulama"),
                                          ("sismik", "Sismik"),
                                          ("koeri", "KOERI"),
                                          ("fay", "Faylar")]):
            sw = ctk.CTkSwitch(tb, text=label, font=ctk.CTkFont(size=11),
                               command=lambda k=key: self._on_map_layer(k))
            sw.grid(row=0, column=2 + i, padx=6, pady=10, sticky="w")
            sw.select(True)
            self.map_switches[key] = sw
        self.map_layers = {"uygulama": True, "sismik": True, "koeri": True, "fay": True}

        ctk.CTkButton(tb, text="Canlı Veri Çek", font=ctk.CTkFont(size=11),
                      fg_color=COLOR_ACCENT_DEEP, command=self._refresh_map_live,
                      height=28, width=110).grid(row=0, column=6, padx=6, pady=10)
        ctk.CTkButton(tb, text="Sığdır", font=ctk.CTkFont(size=11),
                      fg_color=COLOR_BTN_SEC_BG, hover_color=COLOR_BTN_SEC_HOVER, text_color=COLOR_TEXT,
                      border_width=1, border_color=COLOR_CARD_BORDER,
                      command=lambda: self.embedded_map.fit(),
                      height=28, width=70).grid(row=0, column=7, padx=(6, 14), pady=10)

        # Gövde: harita + detay paneli
        body = ctk.CTkFrame(p, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", padx=28, pady=(8, 0))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        map_card = ctk.CTkFrame(body, fg_color=COLOR_CARD_BG, corner_radius=12,
                                border_width=1, border_color=COLOR_CARD_BORDER)
        map_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        map_card.grid_columnconfigure(0, weight=1)
        map_card.grid_rowconfigure(0, weight=1)

        self.embedded_map = MarmaraMap(map_card, on_quake=self._on_map_quake,
                                       on_fault=self._on_map_fault,
                                       width=800, height=460)
        self.embedded_map.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        detail = ctk.CTkFrame(body, fg_color=COLOR_CARD_BG, corner_radius=12,
                              border_width=1, border_color=COLOR_CARD_BORDER, width=290)
        detail.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        detail.grid_propagate(False)
        detail.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(detail, text="Seçim Detayı", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLOR_ACCENT).grid(row=0, column=0, padx=14, pady=(14, 4), sticky="w")
        self.map_detail_title = ctk.CTkLabel(detail, text="Nokta veya fay seçin",
                                             font=ctk.CTkFont(size=15, weight="bold"),
                                             text_color=COLOR_TEXT, wraplength=260)
        self.map_detail_title.grid(row=1, column=0, padx=14, pady=(0, 2), sticky="w")
        self.map_detail_body = ctk.CTkLabel(detail, text="Haritada bir deprem noktasına\nveya fay hattına tıklayın.",
                                            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT2,
                                            justify="left", wraplength=260)
        self.map_detail_body.grid(row=2, column=0, padx=14, pady=(0, 8), sticky="w")

        ctk.CTkLabel(detail, text="Lejant", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=COLOR_TEXT).grid(row=3, column=0, padx=14, pady=(8, 2), sticky="w")
        legend = ctk.CTkFrame(detail, fg_color="transparent")
        legend.grid(row=4, column=0, padx=14, pady=(0, 6), sticky="ew")
        for (label, color) in [("M≥5.0", "#C084FC"), ("M≥4.0", "#F87171"), ("M≥3.0", "#FBBF24"),
                               ("M≥2.0", "#FB9236"), ("M<2.0", "#34D399")]:
            row = ctk.CTkFrame(legend, fg_color="transparent")
            row.pack(fill="x", pady=1)
            dot = ctk.CTkFrame(row, fg_color=color, corner_radius=6, width=12, height=12)
            dot.pack(side="left", padx=(0, 8))
            dot.pack_propagate(False)
            ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=10),
                         text_color=COLOR_TEXT2).pack(side="left")
        for (label, color) in [("Uygulama", "#2DD4BF"), ("Sismik", "#FBBF24"), ("KOERI", "#60A5FA")]:
            row = ctk.CTkFrame(legend, fg_color="transparent")
            row.pack(fill="x", pady=1)
            dot = ctk.CTkFrame(row, fg_color="transparent", corner_radius=0, width=12, height=12,
                               border_width=2, border_color=color)
            dot.pack(side="left", padx=(0, 8))
            dot.pack_propagate(False)
            ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=10),
                         text_color=COLOR_TEXT2).pack(side="left")

        self.map_status = ctk.CTkLabel(p, text="", font=ctk.CTkFont(size=10, weight="bold"),
                                       text_color=COLOR_TEXT)
        self.map_status.grid(row=3, column=0, sticky="w", padx=28, pady=(6, 8))

        self.map_cache = {"uygulama": [], "sismik": [], "koeri": []}
        self._map_live_loaded = False

    # ---------- harita veri ----------
    def _map_cutoff_ts(self):
        from datetime import datetime as _dt
        return _dt.now().timestamp() - self.map_days * 86400

    def _filter_time(self, quakes):
        from deprem_izleme.db import _parse_occurred_ts
        cutoff = self._map_cutoff_ts()
        out = []
        for q in quakes or []:
            ts = q.get("timestamp") or _parse_occurred_ts(q.get("occurred_at", ""))
            if ts and ts >= cutoff:
                out.append(q)
        return out

    def _sync_map_db_layer(self):
        """Uygulama katmanını kayıtlı veriden güncelle (hızlı, eşzamanlı)."""
        from datetime import datetime as _dt, timedelta as _td
        if not hasattr(self, "embedded_map"):
            return
        dbq = get_earthquakes(since=_dt.now() - _td(days=self.map_days),
                              region="marmara", limit=2000)
        self.map_cache["uygulama"] = dbq
        self.embedded_map.set_data({k: (self._filter_time(v) if k != "uygulama" else v)
                                    for k, v in self.map_cache.items()})
        for src in ("uygulama", "sismik", "koeri"):
            self.embedded_map.set_layer_visible(src, self.map_layers.get(src, True))
        self.embedded_map.set_faults_visible(self.map_layers.get("fay", True))
        self._update_map_counts()

    def _update_map_counts(self):
        counts = {k: len(self._filter_time(v)) for k, v in self.map_cache.items()}
        for key, label in [("uygulama", "Uygulama"), ("sismik", "Sismik"),
                           ("koeri", "KOERI"), ("fay", "Faylar")]:
            sw = self.map_switches.get(key)
            if not sw:
                continue
            n = counts.get(key, "")
            if key == "fay":
                from deprem_izleme.fault_segments import FAULT_SEGMENTS as _FS
                sw.configure(text=f"{label} ({len(_FS)})")
            else:
                sw.configure(text=f"{label} ({n})")

    def _on_map_time(self, choice):
        self.map_days = {"24 Saat": 1, "7 Gün": 7, "14 Gün": 14, "30 Gün": 30}.get(choice, 7)
        self._sync_map_db_layer()

    def _on_map_layer(self, key):
        sw = self.map_switches.get(key)
        on = bool(sw.get()) if sw else True
        self.map_layers[key] = on
        if key == "fay":
            self.embedded_map.set_faults_visible(on)
        else:
            self.embedded_map.set_layer_visible(key, on)

    def _refresh_map_live(self):
        """Sismik + KOERI canlı çekiş (arka plan)."""
        self.map_status.configure(text="Canlı veri çekiliyor...", text_color=COLOR_WARNING)
        threading.Thread(target=self._map_live_worker, daemon=True).start()

    def _map_live_worker(self):
        ok, errs = [], []
        try:
            from deprem_izleme.fetcher import fetch_earthquakes
            sq = fetch_earthquakes(days_back=self.map_days, min_magnitude=0.0)
            self.map_cache["sismik"] = sq
            ok.append(f"Sismik: {len(sq)}")
        except Exception as e:
            errs.append(f"Sismik: {e}")
        try:
            from deprem_izleme.fetcher_koeri import fetch_koeri
            kq = fetch_koeri()
            self.map_cache["koeri"] = kq
            ok.append(f"KOERI: {len(kq)}")
        except Exception as e:
            errs.append(f"KOERI: {e}")
        self._post_ui( lambda: self._apply_map_live(ok, errs))

    def _apply_map_live(self, ok, errs):
        self._sync_map_db_layer()
        self._map_live_loaded = True
        msg = " · ".join(ok) if ok else ""
        if errs:
            msg += (" | " if msg else "") + " ".join(errs)
        self.map_status.configure(
            text=msg or "Canlı kaynaklara erişilemedi",
            text_color=COLOR_SUCCESS if ok else COLOR_DANGER)

    def _on_map_quake(self, quake, info):
        mag = quake.get("magnitude")
        mag_s = f"M{mag:.1f}" if mag else "M?.."
        loc = (quake.get("location") or "?")[:44]
        ts = quake.get("occurred_at", "?")
        depth = quake.get("depth_km")
        depth_s = f"{depth:.1f} km" if depth is not None else "?"
        src = (quake.get("source") or "?").upper()
        fault = info.get("fault", "?")
        fdist = info.get("fault_dist_km")
        fdist_s = f"{fdist:.1f} km" if fdist is not None else "?"
        self.map_detail_title.configure(text=f"{mag_s} — {loc}")
        self.map_detail_body.configure(
            text=(f"Zaman: {ts}\nDerinlik: {depth_s}\n"
                  f"Konum: {(quake.get('latitude') or 0):.4f}, {(quake.get('longitude') or 0):.4f}\n"
                  f"Kaynak: {src}\nEn yakın fay: {fault} ({fdist_s})"))

    def _on_map_fault(self, seg):
        locked = seg.get("locked_status", "?").replace("_", " ").title()
        self.map_detail_title.configure(text=seg.get("name_tr", "?"))
        self.map_detail_body.configure(
            text=(f"Durum: {locked}\nMaks: M{seg.get('max_magnitude', '?')}\n"
                  f"Uzunluk: {seg.get('length_km', '?')} km\n"
                  f"Kayma hızı: {seg.get('slip_rate', '?')} mm/yıl\n"
                  f"Tekrarlama: ~{seg.get('recurrence_years', '?')} yıl\n"
                  f"Son kırılma: {seg.get('last_rupture', '?')}\n"
                  f"İz kaynağı: {seg.get('trace_source', '?')}"))

    def _open_url(self, url):
        import webbrowser
        # Dış kaynaktan gelen bağlantılar (haber RSS) dahil: yalnızca http/https
        try:
            u = (url or "").strip()
            if u.lower().startswith(("http://", "https://")):
                webbrowser.open(u)
                self.map_status.configure(text=f"✅ {u} açıldı", text_color=COLOR_SUCCESS)
            else:
                self.map_status.configure(text="⛔ Güvenli olmayan bağlantı engellendi",
                                           text_color=COLOR_DANGER)
        except Exception:
            pass

    # ================================================================
    # 5. HISTORY
    # ================================================================

    def _build_history(self):
        p = self._page_frame()
        self.pages["gecmis"] = p
        self._header(p, "Geçmiş İstatistikler", "Haftalık ve aylık deprem verileri")

        hist_sum = self._make_card(p, "Dönem Özeti")
        hist_sum.pack(fill="x", padx=28, pady=5)
        self.hist_labels = {}
        hs_inner = ctk.CTkFrame(hist_sum, fg_color="transparent")
        hs_inner.pack(fill="x", padx=10, pady=(0, 4))
        hs_inner.grid_columnconfigure((0, 1, 2, 3), weight=1)
        for i, (key, label) in enumerate([
            ("total", "Kayıtlı Hafta"),
            ("quakes", "Toplam Deprem"),
            ("max", "En Büyük"),
            ("b", "Ortalama b"),
        ]):
            _, vl = self._card_field(hs_inner, label, 0, i)
            self.hist_labels[key] = vl
        self.hist_state = ctk.CTkLabel(hist_sum, text="", font=ctk.CTkFont(size=11),
                                       text_color=COLOR_TEXT2)
        self.hist_state.pack(anchor="w", padx=14, pady=(0, 12))

        tv = ctk.CTkTabview(p, fg_color=COLOR_CARD_BG, corner_radius=10)
        tv.pack(fill="both", expand=True, padx=28, pady=(0, 20))
        tv.grid_columnconfigure(0, weight=1)
        tv.grid_rowconfigure(0, weight=1)

        tw = tv.add("Haftalık")
        tw.grid_columnconfigure(0, weight=1)
        tw.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(tw, text="Haftalık Deprem İstatistikleri",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=COLOR_TEXT).grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")
        self.weekly_frame = ctk.CTkScrollableFrame(tw, fg_color="transparent")
        self.weekly_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        tm = tv.add("Aylık")
        tm.grid_columnconfigure(0, weight=1)
        tm.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(tm, text="Aylık Deprem İstatistikleri",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=COLOR_TEXT).grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")
        self.monthly_frame = ctk.CTkScrollableFrame(tm, fg_color="transparent")
        self.monthly_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

    # ================================================================
    # 6. PREDICTION
    # ================================================================

    def _build_prediction(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color="transparent")
        p.grid_columnconfigure(0, weight=1)
        self.pages["tahmin"] = p
        self._header(p, "Deprem Tahmini", "Kısa vadeli olasılık ve trend analizi (7 gün)")

        # Tahmin kartı
        pred_card = self._make_card(p, "7 Günlük Tahmin")
        pred_card.pack(fill="x", padx=28, pady=5)

        self.pred_labels = {}
        pred_fields = [
            ("warning", "Uyarı Seviyesi"),
            ("probability", "M≥4.0 Olasılık"),
            ("poisson_prob", "Poisson Olasılık"),
            ("expected_count", "Beklenen Deprem"),
            ("max_mag", "Beklenen Mmax"),
            ("trend", "Trend"),
        ]
        inner = ctk.CTkFrame(pred_card, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=(0, 12))
        inner.grid_columnconfigure((0, 1, 2), weight=1)
        for i, (key, label) in enumerate(pred_fields):
            _, vl = self._card_field(inner, label, i // 3, i % 3)
            self.pred_labels[key] = vl

        # Bileşenler
        comp_card = self._make_card(p, "Tahmin Bileşenleri")
        comp_card.pack(fill="x", padx=28, pady=5)
        self.comp_inner = ctk.CTkFrame(comp_card, fg_color="transparent")
        self.comp_inner.pack(fill="x", padx=10, pady=(0, 12))

        # Artçı öngörüsü (Omori-Utsu + Reasenberg-Jones jenerik)
        om_card = self._make_card(p, "Artçı Öngörüsü (Omori)")
        om_card.pack(fill="x", padx=28, pady=(5, 20))
        self.omori_labels = {}
        om_inner = ctk.CTkFrame(om_card, fg_color="transparent")
        om_inner.pack(fill="x", padx=10, pady=(0, 12))
        om_inner.grid_columnconfigure((0, 1, 2), weight=1)
        for i, (key, label) in enumerate([
            ("main", "Ana Şok"),
            ("expected", "Beklenen (M≥3, 7g)"),
            ("prob", "En Az 1 Artçı Olasılığı"),
        ]):
            _, vl = self._card_field(om_inner, label, 0, i)
            self.omori_labels[key] = vl

    # ================================================================
    # 7. METODOLOJI
    # ================================================================

    def _build_metodoloji(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color="transparent")
        p.grid_columnconfigure(0, weight=1)
        self.pages["metodoloji"] = p
        self._header(p, "Metodoloji", "Kullanılan bilimsel yöntemler, kaynaklar ve hesaplama mantığı")

        sections = [
            ("Yeni mi Başladınız?",
             "Bu ne demek? Bu uygulama depremleri sayar; büyüklüklerin dağılımından\n"
             "bölgedeki gerilimi (b-değeri), geçmiş hızdan gelecek olasılığı (Poisson)\n"
             "hesaplar. Hiçbir sayı 'deprem olacak' demek değildir; hepsi istatistiksel\n"
             "eğilimdir. Merak ettiğiniz her başlığın altında kaynağı ve sade açıklaması var.\n"
             "Derinlemesine okuma için her karttaki bağlantıya tıklayın.",
             ""),
            ("Gutenberg-Richter Yasası", 
             "Deprem büyüklük-dağılım ilişkisi: log₁₀(N) = a - b·M\n\n"
             "N: belirli magnitüd üzerindeki deprem sayısı\n"
             "M: magnitüd, b: b-değeri, a: aktivite seviyesi\n\n"
             "b-değeri MLE (Aki 1965) + Utsu (1966) düzeltmesiyle hesaplanır:\n"
             "b = log₁₀(e) / (ortalama(M) - (Mc - ΔM/2))\n\n"
             "Mc (tamlık): MAXC yöntemi + 0.2 düzeltme (Wiemer & Wyss 2000).\n"
             "σ(b) ≈ b/√n.\n\n"
             "Kaynak: Gutenberg & Richter (1944) BSSA; Aki (1965); Utsu (1966)",
             "https://pubs.geoscienceworld.org/ssa/bssa/article/55/4/777/116361"),
            
            ("Tamlık Sınırı (Mc)",
             "Bu ne demek? Sismik ağ küçük depremlerin bir kısmını kaçırır.\n"
             "Mc, 'bundan büyüklerin tamamı yakalanır' sınırıdır; hesabın altı\n"
             "eksik, üstü sağlamdır. Mc altı veriyi analize katmak b-değerini bozar.\n\n"
             "MAXC yöntemi: en kalabalık büyüklük dilimi + 0.2 güvenlik payı\n"
             "(Wiemer & Wyss 2000). Bu uygulama Mc'yi veriden otomatik bulur.\n\n"
             "Kaynak: Wiemer & Wyss (2000) BSSA; Woessner & Wiemer (2005)",
             "https://pubs.geoscienceworld.org/ssa/bssa/article/90/4/859/120467"),
            
            ("Poisson Zaman Modeli", 
             "Depremlerin rastgele (Poisson) süreç olduğu varsayımı:\n\n"
             "P(M≥m, t) = 1 - exp(-λ·t)\n\n"
             "λ: artçı-ayıklanmış zemin hızı (/gün), t: zaman (gün)\n\n"
             "Bu uygulama λ'yı Gardner-Knopoff (1974) pencereleriyle\n"
             "artçıklardan arındırılmış katalogdan hesaplar.\n"
             "Temel varsayım: Zemin depremler bağımsızdır.\n"
             "Büyük depremler için zaman-bağımlı modeller (BPT) daha uygundur.\n\n"
             "Kaynak: Gardner & Knopoff (1974) BSSA; Parsons (2004) JGR",
             "https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2003JB002667"),
            
            ("Artçı Ayıklama",
             "Bu ne demek? Artçılar ana şoku izleyen 'yankı'lardır. Gelecek\n"
             "olasılığını hesaplarken yankıyı değil zemin sesi duymak isteriz.\n\n"
             "Gardner-Knopoff (1974) pencereleri: her depremin büyüklüğüne göre\n"
             "zaman-mesafe penceresi içindeki küçükler artçı sayılır, zemin\n"
             "katalogda kalanlardır. Poisson olasılığı bu temiz hızdan hesaplanır.\n\n"
             "Kaynak: Gardner & Knopoff (1974) BSSA",
             "http://www.corssa.org/export/sites/corssa/.galleries/articles-pdf/vanStiphout_et_al.pdf_2063069299.pdf"),
            
            ("Artçı Azalımı (Omori-Utsu)", 
             "Ana şok sonrası artçı hızı zamanla azalır:\n\n"
             "R(t) = K / (t + c)^p\n\n"
             "K: üretkenlik, c: erken dönem ölçeği, p: azalım üssü\n\n"
             "Reasenberg-Jones (1989) üretkenlik modeli:\n"
             "K = 10^[a + b·(Mm - Mkes)]\n\n"
             "Bu uygulama Türkiye kalibrasyonunu kullanır:\n"
             "a=-1.90, b=1.11, p=1.20, c=0.05 gün\n"
             "(Müderrisoğlu & Yazgan 2020; Mw≥5.9 Türkiye dizileri).\n\n"
             "Kaynak: Reasenberg & Jones (1989) Science; USGS OAF;\n"
             "Muderrisoglu & Yazgan (2020) Earthq. Eng. Eng. Vib. 19:149-160",
             "https://doi.org/10.1007/s11803-020-0553-2"),
            
            ("Kısa Vadeli Bileşik Gösterge (7 Gün)",
             "5 bileşenin ağırlıklı ortalaması (0-1 skor):\n\n"
             "• Poisson olasılığı (%30)\n"
             "• b-değeri trendi (%20): max(0, -Δb·5)\n"
             "• Enerji oranı (%15): (oran-0.5)/2\n"
             "• Z-skor (%20): z/4\n"
             "• Öncü sismisite oranı (%15): oran·3\n\n"
             "Uyarı eşikleri: ≥0.65 kırmızı, ≥0.45 turuncu,\n"
             "≥0.25 sarı (uzman seçimi eşikler).\n\n"
             "ÖNEMLİ: Ağırlık ve eşikler geçmiş veriyle kalibre\n"
             "EDİLMEMİŞTİR; bileşik sayı kalibre bir olasılık değil\n"
             "eğilim göstergesidir. Operasyonel tahmin standartları\n"
             "(ICEF) kalibre ve test edilebilir olasılık ister;\n"
             "bu ekrandaki kalibre olasılık SADECE Poisson\n"
             "bileşenidir (zemin hızdan).\n\n"
             "Kaynak: Jordan vd. (2011) Ann. Geophys. 54:315-326 (ICEF)",
             "https://doi.org/10.4401/ag-5350"),
           
            ("Coulomb Stres Transferi", 
             "Coulomb Kırılma Kriteri: ΔCFF = Δτ + μ'·Δσn\n\n"
             "Δτ: kayma stressi değişimi\n"
             "Δσn: normal stress değişimi (pozitif = fayı açar)\n"
             "μ': efektif sürtünme katsayısı (0.4 varsayılan)\n\n"
             "Eşik değer: ΔCFF ≥ 0.1 bar = deprem tetikleme potansiyeli\n\n"
             "Kaynak: King, Stein & Lin (1994) BSSA; Toda & Stein (2005) Nature",
             "https://pubs.geoscienceworld.org/ssa/bssa/article/84/3/935/119895"),
            
            ("BVAL Metodu (b-değeri Analizi)", 
             "b-değerinin zamansal değişimi büyük depremlerin öncülüdür.\n\n"
             "Büyük deprem öncesi b-değerinde düşüş gözlenir:\n"
             "• Normal: b ≈ 1.0\n"
             "• Öncü dönem: b düşüşü (aylar-yıllar öncesi)\n"
             "• Sonrası: b tekrar yükselir\n\n"
             "Laboratuvar: kırılma öncesi b düşüşü (Scholz 1968).\n"
             "Saha: düşük b = yüksek gerilim (Schorlemmer & Wiemer 2005).\n"
             "Gerçek zamanlı öncü/artçı ayrımı: b düşmeye devam ederse\n"
             "öncü olasılığı artar (Gulia & Wiemer 2019).\n\n"
             "Marmara'ya özgü sayısal b-eşiği yayınlanmamıştır;\n"
             "bu ekrandaki eğilim göstergesidir, alarm eşiği değildir.\n\n"
             "Kaynak: Schorlemmer & Wiemer (2005) Nature; Gulia & Wiemer (2019) Nat. Commun.",
             "https://www.science.org/doi/10.1126/science.adz0072"),
            
            ("Kitli Fay & Sismik Boşluk Teorisi", 
             "Marmara'da ~160 km'lik bölüm 1766'dan beri büyük ölçüde kırılmamıştır\n"
             "(2025'te Kumburgaz batısında M6.2 kısmi kırılma oldu).\n\n"
             "Fedotov (1965) sismik boşluk teorisi: Uzun süre kırılmamış\n"
             "fay segmentleri büyük deprem üretme potansiyeli taşır.\n\n"
             "Parsons (2004): İstanbul için 30 yıllık M≥7 olasılığı:\n"
             "Poisson %21; zaman-bağımlı + stres transferli %41±14.\n"
             "Murru vd. (2016): M>7.3 için %35 Poisson, %47 zaman-bağımlı.\n"
             "Martínez-Garzón vd. (2025): Kırılma doğuya, İstanbul'a\n"
             "ilerliyor; 2025 M6.2 Kumburgaz batısında kısmi kırılma.\n\n"
             "Segment bazında risk:\n"
             f"• Tekirdağ: 1766'dan beri kırılmadı ({datetime.now().year - 1766} yıl boşluk)\n"
             "• Kumburgaz: 2025'te kısmi kırılma, ana segment kitli\n"
             f"• Avcılar: 1509'dan beri kırılmamış ({datetime.now().year - 1509} yıl boşluk)\n"
             "• Adalar: 1766'dan beri locked",
             "https://temblor.net/earthquake-insights/a-magnitude-6-2-quake-strikes-the-marmara-fault-at-site-of-large-historic-earthquakes-near-istanbul-16755/"),
            
            ("Veri Kaynakları", 
             "1. Sismik Harita API (sismikharita.com) — Ana kaynak\n"
             "   Ücretsiz: 100 istek/gün, anahtar gerekmez\n"
             "   Kandilli Rasathanesi + AFAD verilerini birleştirir\n\n"
             "2. KOERI (Kandilli) — Ek kaynak\n"
             "   http://www.koeri.boun.edu.tr/scripts/lst0.asp\n"
             "   Son 500 deprem, otomatik çözümler\n\n"
             "3. Akademik Referanslar:\n"
             "   • Armijo et al. (2005): Marmara fay geometrisi\n"
             "   • Le Pichon et al. (2016): Marmara fay segmentleri\n"
             "   • MARSITE Project D7.2: GIS fay veritabanı\n"
             "   • Science (Martínez-Garzón 2025): Doğuya ilerleyen kırılma\n"
             "   • USGS/EMSC: Uluslararası deprem katalogları",
             ""),
        ]

        for title, desc, source in sections:
            card = self._make_card(p, title)
            card.pack(fill="x", padx=28, pady=5)

            for line in desc.split("\n"):
                if line.strip().startswith("•"):
                    ctk.CTkLabel(card, text=line.strip(), font=ctk.CTkFont(size=10),
                                 text_color=COLOR_BODY2, justify="left",
                                 anchor="w").pack(anchor="w", padx=18, pady=1)
                elif line.strip().startswith(("1.", "2.", "3.")):
                    ctk.CTkLabel(card, text=line.strip(), font=ctk.CTkFont(size=10, weight="bold"),
                                 text_color=COLOR_BODY, justify="left",
                                 anchor="w").pack(anchor="w", padx=18, pady=2)
                elif line.strip() == "":
                    pass
                else:
                    ctk.CTkLabel(card, text=line.strip(), font=ctk.CTkFont(size=10),
                                 text_color=COLOR_BODY, justify="left",
                                 anchor="w").pack(anchor="w", padx=18, pady=2)

            if source:
                link_lbl = ctk.CTkLabel(card, text=f"🔗 {source}", font=ctk.CTkFont(size=8, slant="italic"),
                                        text_color=COLOR_INFO, justify="left",
                                        anchor="w")
                link_lbl.pack(anchor="w", padx=18, pady=(4, 10))
                import webbrowser
                link_lbl.bind("<Button-1>", lambda e, url=source: webbrowser.open(url))

    # ================================================================
    # 7b. GRAFIKLER
    # ================================================================

    def _build_grafikler(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color="transparent")
        p.grid_columnconfigure(0, weight=1)
        self.pages["grafikler"] = p

        hf = ctk.CTkFrame(p, fg_color="transparent")
        hf.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 8))
        hf.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hf, text="Grafikler", font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=COLOR_TEXT).pack(anchor="w")
        ctk.CTkLabel(hf, text="Detaylı deprem metrikleri ve trend analizi",
                     font=ctk.CTkFont(size=10), text_color=COLOR_TEXT2).pack(anchor="w")

        # Kontrol çubuğu
        cbar = ctk.CTkFrame(p, fg_color="transparent")
        cbar.grid(row=1, column=0, sticky="ew", padx=28, pady=4)

        ctk.CTkLabel(cbar, text="Zaman Aralığı:", font=ctk.CTkFont(size=10),
                     text_color=COLOR_TEXT2).pack(side="left", padx=(0, 6))
        self.chart_time_segment = ctk.CTkSegmentedButton(
            cbar, values=["7 Gün", "14 Gün", "30 Gün", "60 Gün", "90 Gün"],
            font=ctk.CTkFont(size=10), selected_color=COLOR_ACCENT_DEEP,
            command=self._on_chart_filter, height=28
        )
        self.chart_time_segment.pack(side="left", padx=(0, 10))
        self.chart_time_segment.set("7 Gün")

        ctk.CTkButton(cbar, text="Yenile", font=ctk.CTkFont(size=10),
                      fg_color=COLOR_ACCENT_DEEP, command=self._refresh_charts,
                      height=28, width=80).pack(side="left", padx=4)

        ctk.CTkButton(cbar, text="Tam Ekran", font=ctk.CTkFont(size=10),
                      fg_color=COLOR_BTN_SEC_BG, hover_color=COLOR_BTN_SEC_HOVER, text_color=COLOR_TEXT, border_width=1,
                      border_color=COLOR_CARD_BORDER, command=self._chart_fullscreen,
                      height=28, width=90).pack(side="right", padx=4)

        self.chart_status = ctk.CTkLabel(p, text="", font=ctk.CTkFont(size=9),
                                          text_color=COLOR_TEXT2)
        self.chart_status.grid(row=2, column=0, sticky="w", padx=28, pady=(4, 0))

        # Grafik container
        self.chart_canvas_frame = ctk.CTkFrame(p, fg_color=COLOR_CARD_BG, corner_radius=8,
                                               border_width=1, border_color=COLOR_CARD_BORDER)
        self.chart_canvas_frame.grid(row=3, column=0, sticky="nsew", padx=28, pady=(8, 4))
        self.chart_canvas_frame.grid_columnconfigure(0, weight=1)
        self.chart_canvas_frame.grid_rowconfigure(0, weight=1)
        p.grid_rowconfigure(3, weight=1)
        self._chart_placeholder(self.chart_canvas_frame)

        self.chart_caption1 = ctk.CTkLabel(
            p, text="Üst grafikler: günlük en büyük deprem (renk = büyüklük) ve mavi risk eğilimi. "
                    "Yükselen çubuklar + yükselen çizgi = artan hareketlilik.",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT2, justify="left",
            wraplength=900)
        self.chart_caption1.grid(row=4, column=0, sticky="w", padx=28, pady=(0, 8))

        # Dağılımlar (FMD, saatlik, derinlik, büyüklük-zaman)
        self.chart_dist_frame = ctk.CTkFrame(p, fg_color="transparent")
        self.chart_dist_frame.grid(row=5, column=0, sticky="nsew", padx=28, pady=(0, 4))
        self.chart_dist_frame.grid_columnconfigure((0, 1), weight=1)
        self.dist_frames = []
        for _r in range(2):
            for _c in range(2):
                _f = ctk.CTkFrame(self.chart_dist_frame, fg_color=COLOR_CARD_BG, corner_radius=8,
                                  border_width=1, border_color=COLOR_CARD_BORDER)
                _f.grid(row=_r, column=_c, sticky="nsew", padx=3, pady=3)
                _f.grid_columnconfigure(0, weight=1)
                _f.grid_rowconfigure(0, weight=1)
                self._chart_placeholder(_f)
                self.dist_frames.append(_f)

        self.chart_caption2 = ctk.CTkLabel(
            p, text="Dağılımlar: Büyüklük Dağılımı (sarı = kümülatif sayı, kesikli mavi = yasa eğrisi, "
                    "kırmızı çizgi = tamlık sınırı Mc) • Saatlik (depremin saati olmaz; gece-gündüz farkı algıdır) • "
                    "Derinlik (sığ depremler daha çok hissedilir) • Büyüklük-Zaman (artçı dizileri dikey kümelenir).",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT2, justify="left",
            wraplength=900)
        self.chart_caption2.grid(row=6, column=0, sticky="w", padx=28, pady=(0, 20))

        self.chart_canvas = None
        self.chart_fig = None
        self.chart_days = 7

        # NOT: Deprem listesi burada TEKRARLANMIYOR - Ana Sayfa'da var.

        # İlk yükleme
        self._safe_after(200, self._refresh_charts)

    def _on_chart_filter(self, choice):
        mapping = {"7 Gün": 7, "14 Gün": 14, "30 Gün": 30, "60 Gün": 60, "90 Gün": 90}
        self.chart_days = mapping.get(choice, 7)
        self._refresh_charts()

    def _refresh_charts(self):
        self.chart_status.configure(text="📊 Grafik oluşturuluyor...", text_color=COLOR_WARNING)
        threading.Thread(target=self._chart_worker, daemon=True).start()

    def _chart_worker(self):
        try:
            days = self.chart_days
            from deprem_izleme.charts import (
                build_overview_figure, build_fmd_figure, build_hourly_figure,
                build_depth_figure, build_magtime_figure)
            from deprem_izleme.db import get_earthquakes as _gq
            from datetime import datetime as _dt, timedelta as _td
            nq = len(_gq(since=_dt.now() - _td(days=days), region="marmara", limit=1000))
            fig = build_overview_figure(days=days)
            figs2 = [build_fmd_figure(width=5.5, height=2.8, days=days),
                     build_hourly_figure(width=5.5, height=2.8, days=days),
                     build_depth_figure(width=5.5, height=2.8, days=days),
                     build_magtime_figure(width=5.5, height=2.8, days=days)]

            # Canvas bağlama ANA THREAD'de olmalı (Tk thread-güvenli değil)
            dd = days
            self._post_ui( lambda: self._attach_grafikler_chart(fig, figs2, nq, dd))
        except Exception as e:
            _emsg = str(e)
            self._post_ui(lambda e=_emsg: self.chart_status.configure(
                text=f"Hata: {e}", text_color=COLOR_DANGER))
            import traceback
            traceback.print_exc()

    def _attach_grafikler_chart(self, fig, figs2, n_quakes, days):
        """4 panelli + 4 dağılım figürünü Tk'ya bağla - SADECE ana thread'den."""
        for w in self.chart_canvas_frame.winfo_children():
            w.destroy()
        from deprem_izleme.charts import _attach_canvas as _ac1
        canvas, fig = _ac1(self.chart_canvas_frame, fig)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self.chart_canvas = canvas
        self.chart_fig = fig
        for frame, fig2 in zip(getattr(self, "dist_frames", []), figs2 or []):
            try:
                from deprem_izleme.charts import _attach_canvas as _ac2
                c2, _f2 = _ac2(frame, fig2)
                c2.get_tk_widget().pack(fill="both", expand=True)
            except Exception:
                pass
        self.chart_status.configure(
            text=f"✅ {n_quakes} deprem verisiyle grafikler oluşturuldu ({days} gün)",
            text_color=COLOR_SUCCESS)

    def _chart_fullscreen(self):
        """Grafikleri tam ekran yap."""
        if hasattr(self, '_chart_fs') and self._chart_fs and self._chart_fs.winfo_exists():
            self._chart_fs.destroy()
            self._chart_fs = None
            return

        fs = ctk.CTkToplevel(self)
        fs.title("Grafikler - Tam Ekran")
        try:
            # Geçerli monitörü doldur (çok ekranlı kurulumda doğru ekran)
            fs.attributes("-fullscreen", True)
        except Exception:
            fs.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")
        fs.configure(fg_color=COLOR_MAIN_BG)
        fs.grid_columnconfigure(0, weight=1)
        fs.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(fs, fg_color=COLOR_CARD_BG, corner_radius=0, height=36)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_propagate(False)
        ctk.CTkLabel(top, text="Grafikler - Tam Ekran", font=ctk.CTkFont(size=12),
                     text_color=COLOR_TEXT).pack(side="left", padx=12)
        ctk.CTkButton(top, text="✕ Kapat", font=ctk.CTkFont(size=10),
                      fg_color="#ef4444", command=lambda: (fs.destroy(), setattr(self, '_chart_fs', None)),
                      height=24, width=60).pack(side="right", padx=8)

        # Zaman seçici (tam ekrandaki seçim ana grafiği de günceller)
        seg = ctk.CTkSegmentedButton(top,
            values=["7 Gün", "14 Gün", "30 Gün", "60 Gün", "90 Gün"],
            font=ctk.CTkFont(size=9), selected_color=COLOR_ACCENT_DEEP, height=24,
            command=self._on_fullscreen_filter)
        seg.pack(side="right", padx=8)
        seg.set(self.chart_time_segment.get())

        # Büyük grafik alanı
        cf = ctk.CTkFrame(fs, fg_color=COLOR_CARD_BG, corner_radius=8,
                          border_width=1, border_color=COLOR_CARD_BORDER)
        cf.grid(row=1, column=0, sticky="nsew")
        cf.grid_columnconfigure(0, weight=1)
        cf.grid_rowconfigure(0, weight=1)
        self._fs_frame = cf

        # Ana grafiği büyük boyutta çiz
        self._draw_fullscreen_chart(cf)

        self._chart_fs = fs
        try:
            fs.bind("<Escape>", lambda e: (fs.destroy(), setattr(self, '_chart_fs', None)))
        except Exception:
            pass

    def _on_fullscreen_filter(self, choice):
        """Tam ekrandaki zaman seçimi: ana grafiği de eşitler, yeniden çizer."""
        mapping = {"7 Gün": 7, "14 Gün": 14, "30 Gün": 30, "60 Gün": 60, "90 Gün": 90}
        self.chart_days = mapping.get(choice, 7)
        try:
            self.chart_time_segment.set(choice)
        except Exception:
            pass
        self._refresh_charts()
        fs = getattr(self, "_chart_fs", None)
        if fs is not None and fs.winfo_exists() and hasattr(self, "_fs_frame"):
            for w in self._fs_frame.winfo_children():
                w.destroy()
            self._draw_fullscreen_chart(self._fs_frame)

    def _draw_fullscreen_chart(self, parent_frame):
        """Tam ekran için büyük grafik."""
        from deprem_izleme.charts import build_fullscreen_figure
        fig = build_fullscreen_figure(days=self.chart_days)
        from deprem_izleme.charts import _attach_canvas as _ac3
        canvas, _ff = _ac3(parent_frame, fig)
        canvas.get_tk_widget().pack(fill="both", expand=True)

    # ================================================================
    # 8. HABERLER
    # ================================================================

    def _build_haberler(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color="transparent")
        p.grid_columnconfigure(0, weight=1)
        self.pages["haberler"] = p
        self._header(p, "Deprem Haberleri", "Güncel deprem haberleri (Google News)")

        # Kontrol çubuğu
        cbar = ctk.CTkFrame(p, fg_color="transparent")
        cbar.pack(fill="x", padx=28, pady=(0, 10))
        self.news_status = ctk.CTkLabel(cbar, text="", font=ctk.CTkFont(size=10),
                                         text_color=COLOR_TEXT2)
        self.news_status.pack(side="left", padx=(0, 10))
        ctk.CTkButton(cbar, text="Haberleri Güncelle", font=ctk.CTkFont(size=11),
                      fg_color=COLOR_ACCENT_DEEP, hover_color="#0D9488",
                      command=self._refresh_news, height=30, width=140).pack(side="left")

        self.news_frame = ctk.CTkFrame(p, fg_color="transparent")
        self.news_frame.pack(fill="both", expand=True, padx=28, pady=(0, 20))

    def _refresh_news(self):
        """Haberleri çek ve göster."""
        self._news_loaded = True
        self.news_status.configure(text="Haberler çekiliyor...", text_color=COLOR_WARNING)
        threading.Thread(target=self._news_worker, daemon=True).start()

    def _news_worker(self):
        try:
            from deprem_izleme.news_fetcher import fetch_news
            news = fetch_news(max_items=30)
            self._post_ui( lambda: self._display_news(news))
        except Exception as e:
            _emsg = str(e)
            self._post_ui(lambda e=_emsg: self.news_status.configure(
                text=f"Hata: {e}", text_color=COLOR_DANGER))

    def _display_news(self, news):
        if not hasattr(self, "news_frame"):
            return
        for w in self.news_frame.winfo_children():
            w.destroy()

        if not news:
            ctk.CTkLabel(self.news_frame, text="Henüz haber bulunamadı.",
                         font=ctk.CTkFont(size=12), text_color=COLOR_TEXT2).pack(pady=30)
            self.news_status.configure(text="Haber bulunamadı", text_color=COLOR_WARNING)
            return

        # Haberler (bozuk kayıtları ele, bağlantıları kapıdan geçir)
        def _ok(n):
            return (isinstance(n, dict) and n.get("tip", "haber") == "haber"
                    and str(n.get("baslik") or "").strip())
        haberler = [n for n in (news or []) if _ok(n)] or \
                   [n for n in (news or [])
                    if isinstance(n, dict) and str(n.get("baslik") or "").strip()]
        if haberler:
            hab_frame = ctk.CTkFrame(self.news_frame, fg_color=COLOR_CARD_BG, corner_radius=10)
            hab_frame.pack(fill="x", pady=6)
            ctk.CTkLabel(hab_frame, text="Deprem Haberleri",
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=COLOR_ACCENT).pack(anchor="w", padx=16, pady=(12, 6))

            for n in haberler[:15]:
                title = str(n.get("baslik", "?"))[:140]
                source = str(n.get("kaynak", "?"))
                date = str(n.get("tarih", ""))[:17]
                link = str(n.get("link", ""))
                item = ctk.CTkFrame(hab_frame, fg_color=COLOR_INSET, corner_radius=6)
                item.pack(fill="x", padx=16, pady=3)
                item.grid_columnconfigure(0, weight=1)

                # Başlık (tıklanabilir - el imleci + hover)
                lbl = ctk.CTkLabel(item, text=f"{title}  →",
                                   font=ctk.CTkFont(size=10),
                                   text_color=COLOR_TEXT, justify="left",
                                   anchor="w", wraplength=650, cursor="hand2")
                lbl.grid(row=0, column=0, padx=10, pady=(6, 2), sticky="w")

                # Kaynak + tarih
                ctk.CTkLabel(item, text=f"{source} | {date}",
                             font=ctk.CTkFont(size=8), text_color=COLOR_TEXT2,
                             anchor="w").grid(row=1, column=0, padx=10, pady=(0, 6), sticky="w")

                def _open_news(_ev=None, url=link):
                    if (url or "").strip().lower().startswith(("http://", "https://")):
                        try:
                            import webbrowser as _wb
                            _wb.open(url)
                            self.news_status.configure(text="Haber tarayıcıda açıldı",
                                                       text_color=COLOR_SUCCESS)
                        except Exception as ex:
                            self.news_status.configure(text=f"Açılamadı: {ex}",
                                                       text_color=COLOR_DANGER)
                    else:
                        self.news_status.configure(text="⛔ Güvenli olmayan bağlantı engellendi",
                                                   text_color=COLOR_DANGER)

                lbl.bind("<Button-1>", _open_news)
                lbl.bind("<Enter>", lambda e, l=lbl: l.configure(text_color=COLOR_INFO))
                lbl.bind("<Leave>", lambda e, l=lbl: l.configure(text_color=COLOR_TEXT))
                item.bind("<Button-1>", _open_news)

        self.news_status.configure(
            text=f"✅ {len(news)} haber — son güncelleme: {datetime.now().strftime('%H:%M')}",
            text_color=COLOR_SUCCESS)

    # ================================================================
    # 9. AYARLAR
    # ================================================================

    def _build_settings(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color="transparent")
        p.grid_columnconfigure(0, weight=1)
        self.pages["ayarlar"] = p
        self._header(p, "Ayarlar", "Sistem yapılandırması ve yönetim")

        # --- Görünüm ---
        theme_card = self._make_card(p, "Görünüm")
        theme_card.pack(fill="x", padx=28, pady=5)
        theme_inner = ctk.CTkFrame(theme_card, fg_color="transparent")
        theme_inner.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkLabel(theme_inner, text="Tema:", font=ctk.CTkFont(size=11),
                     text_color=COLOR_TEXT).pack(side="left", padx=(0, 8))
        self.theme_segment = ctk.CTkSegmentedButton(
            theme_inner, values=["Koyu", "Açık"], font=ctk.CTkFont(size=11),
            selected_color=COLOR_ACCENT_DEEP, command=self._on_theme)
        self.theme_segment.pack(side="left")
        try:
            from deprem_izleme.config import load_settings as _lss
            self.theme_segment.set("Açık" if _lss().get("appearance") == "light" else "Koyu")
        except Exception:
            self.theme_segment.set("Koyu")
        ctk.CTkLabel(theme_inner, text="Değişiklik yeniden başlatınca uygulanır.",
                     font=ctk.CTkFont(size=9), text_color=COLOR_TEXT2).pack(side="left", padx=(10, 0))
        self.theme_status = ctk.CTkLabel(theme_inner, text="", font=ctk.CTkFont(size=10),
                                        text_color=COLOR_SUCCESS)
        self.theme_status.pack(side="left", padx=(10, 0))

        # --- Background worker ---
        bg_card = self._make_card(p, "Arkaplan Otomatik Güncelleme")
        bg_card.pack(fill="x", padx=28, pady=5)

        bg_inner = ctk.CTkFrame(bg_card, fg_color="transparent")
        bg_inner.pack(fill="x", padx=14, pady=(0, 14))
        bg_inner.grid_columnconfigure(1, weight=1)

        self.bg_switch = ctk.CTkSwitch(bg_inner, text="Aktif", font=ctk.CTkFont(size=12),
                                        command=self._toggle_bg, onvalue=True, offvalue=False)
        self.bg_switch.grid(row=0, column=0, padx=(0, 10), pady=5, sticky="w")
        self.bg_switch.select(False)

        ctk.CTkLabel(bg_inner, text="Güncelleme Aralığı:",
                     font=ctk.CTkFont(size=11), text_color=COLOR_TEXT).grid(row=1, column=0, pady=5, sticky="w")
        self.bg_interval_combo = ctk.CTkComboBox(
            bg_inner, values=[f"{i} dakika" for i in REFRESH_INTERVALS],
            font=ctk.CTkFont(size=11), state="readonly", width=120,
            command=self._on_bg_interval
        )
        self.bg_interval_combo.grid(row=1, column=0, padx=(120, 0), pady=5, sticky="w")
        self.bg_interval_combo.set("60 dakika")

        self.bg_status = ctk.CTkLabel(bg_inner, text="⏸️ Durduruldu",
                                       font=ctk.CTkFont(size=10), text_color=COLOR_TEXT2)
        self.bg_status.grid(row=2, column=0, columnspan=2, pady=(2, 0), sticky="w")

        ctk.CTkLabel(bg_inner, text=f"Günlük API limiti: {DAILY_LIMIT} istek",
                     font=ctk.CTkFont(size=9), text_color=COLOR_TEXT2).grid(row=3, column=0, columnspan=2, pady=2, sticky="w")
        self.bg_count_label = ctk.CTkLabel(bg_inner, text="Bugün kullanılan: 0",
                                            font=ctk.CTkFont(size=9), text_color=COLOR_WARNING)
        self.bg_count_label.grid(row=4, column=0, columnspan=2, sticky="w")

        # --- Veri Kaynağı (Sismik Harita API) ---
        api_card = self._make_card(p, "Veri Kaynağı (Sismik Harita API)")
        api_card.pack(fill="x", padx=28, pady=5)

        api_inner = ctk.CTkFrame(api_card, fg_color="transparent")
        api_inner.pack(fill="x", padx=14, pady=(0, 14))
        api_inner.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(api_inner, text="API Adresi:", font=ctk.CTkFont(size=11),
                     text_color=COLOR_TEXT).grid(row=0, column=0, padx=(0, 8), pady=4, sticky="w")
        self.api_base = ctk.CTkEntry(api_inner, fg_color=COLOR_INSET, border_color=COLOR_ENTRY_BORDER)
        self.api_base.grid(row=0, column=1, pady=4, sticky="ew")

        ctk.CTkLabel(api_inner, text="API Anahtarı:", font=ctk.CTkFont(size=11),
                     text_color=COLOR_TEXT).grid(row=1, column=0, padx=(0, 8), pady=4, sticky="w")
        self.api_key = ctk.CTkEntry(api_inner, placeholder_text="Yoksa boş bırakın (100 istek/gün)",
                                    fg_color=COLOR_INSET, border_color=COLOR_ENTRY_BORDER, show="•")
        self.api_key.grid(row=1, column=1, pady=4, sticky="ew")

        try:
            from deprem_izleme.config import load_settings as _lsapi
            _sa = _lsapi()
            self.api_base.insert(0, _sa.get("api_base", "https://sismikharita.com"))
            if _sa.get("api_key"):
                self.api_key.insert(0, _sa["api_key"])
        except Exception:
            pass

        abf = ctk.CTkFrame(api_inner, fg_color="transparent")
        abf.grid(row=2, column=0, columnspan=2, pady=6, sticky="w")
        ctk.CTkButton(abf, text="Bağlantıyı Test Et", font=ctk.CTkFont(size=10),
                      fg_color=COLOR_BTN_SEC_BG, hover_color=COLOR_BTN_SEC_HOVER, text_color=COLOR_TEXT, border_width=1,
                      border_color=COLOR_CARD_BORDER,
                      command=self.test_api, width=110, height=28).pack(side="left", padx=(0, 6))
        ctk.CTkButton(abf, text="Kaydet", font=ctk.CTkFont(size=10),
                      fg_color=COLOR_ACCENT_DEEP, hover_color="#0D9488",
                      command=self.save_api, width=70, height=28).pack(side="left")
        ctk.CTkLabel(api_inner,
                     text="Anahtar zorunlu değil (günde 100 istek). Anahtar için sismikharita.com/api "
                          "sayfasından giriş yapın/kayıt olun; anahtar otomatik oluşur.",
                     font=ctk.CTkFont(size=9), text_color=COLOR_TEXT2,
                     wraplength=420, justify="left").grid(row=3, column=0, columnspan=2, sticky="w")

        self.api_status = ctk.CTkLabel(api_inner, text="", font=ctk.CTkFont(size=10),
                                      text_color=COLOR_SUCCESS)
        self.api_status.grid(row=4, column=0, columnspan=2, sticky="w")

        # --- Telegram ---
        tel_card = self._make_card(p, "Telegram Bildirimleri")
        tel_card.pack(fill="x", padx=28, pady=5)

        tel_inner = ctk.CTkFrame(tel_card, fg_color="transparent")
        tel_inner.pack(fill="x", padx=14, pady=(0, 14))
        tel_inner.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(tel_inner, text="Bot Token:", font=ctk.CTkFont(size=11),
                     text_color=COLOR_TEXT).grid(row=0, column=0, padx=(0, 8), pady=4, sticky="w")
        self.tel_token = ctk.CTkEntry(tel_inner, placeholder_text="...",
                                      fg_color=COLOR_INSET, border_color=COLOR_ENTRY_BORDER,
                                      show="•")
        self.tel_token.grid(row=0, column=1, pady=4, sticky="ew")

        ctk.CTkLabel(tel_inner, text="Chat ID:", font=ctk.CTkFont(size=11),
                     text_color=COLOR_TEXT).grid(row=1, column=0, padx=(0, 8), pady=4, sticky="w")
        self.tel_chat = ctk.CTkEntry(tel_inner, placeholder_text="...",
                                      fg_color=COLOR_INSET, border_color=COLOR_ENTRY_BORDER)
        self.tel_chat.grid(row=1, column=1, pady=4, sticky="ew")

        try:
            from deprem_izleme.config import load_settings as _lst
            _ts = _lst()
            if _ts.get("telegram_token"):
                self.tel_token.insert(0, _ts["telegram_token"])
            if _ts.get("telegram_chat_id"):
                self.tel_chat.insert(0, _ts["telegram_chat_id"])
        except Exception:
            pass

        tbf = ctk.CTkFrame(tel_inner, fg_color="transparent")
        tbf.grid(row=2, column=0, columnspan=2, pady=6, sticky="w")
        ctk.CTkButton(tbf, text="Test", font=ctk.CTkFont(size=10),
                      fg_color=COLOR_BTN_SEC_BG, hover_color=COLOR_BTN_SEC_HOVER, text_color=COLOR_TEXT, border_width=1,
                      border_color=COLOR_CARD_BORDER,
                      command=self.test_tel, width=70, height=28).pack(side="left", padx=(0, 6))
        ctk.CTkButton(tbf, text="Kaydet", font=ctk.CTkFont(size=10),
                      fg_color=COLOR_ACCENT_DEEP, hover_color="#0D9488",
                      command=self.save_tel, width=70, height=28).pack(side="left")

        self.tel_status = ctk.CTkLabel(tel_inner, text="", font=ctk.CTkFont(size=10),
                                        text_color=COLOR_SUCCESS)
        self.tel_status.grid(row=3, column=0, columnspan=2, sticky="w")

        ctk.CTkLabel(tel_inner, text="Bildirim Filtreleri:", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=COLOR_TEXT).grid(row=4, column=0, columnspan=2, pady=(10, 2), sticky="w")

        self.tel_enable = ctk.CTkSwitch(tel_inner, text="Otomatik uyarılar aktif",
                                        font=ctk.CTkFont(size=11))
        self.tel_enable.grid(row=5, column=0, columnspan=2, pady=2, sticky="w")

        ctk.CTkLabel(tel_inner, text="Risk eşiği (0-1):", font=ctk.CTkFont(size=11),
                     text_color=COLOR_TEXT).grid(row=6, column=0, padx=(0, 8), pady=4, sticky="w")
        self.tel_threshold = ctk.CTkEntry(tel_inner, width=80,
                                          fg_color=COLOR_INSET, border_color=COLOR_ENTRY_BORDER)
        self.tel_threshold.grid(row=6, column=1, pady=4, sticky="w")

        ctk.CTkLabel(tel_inner, text="Tekrar bekleme (saat):", font=ctk.CTkFont(size=11),
                     text_color=COLOR_TEXT).grid(row=7, column=0, padx=(0, 8), pady=4, sticky="w")
        self.tel_cooldown = ctk.CTkEntry(tel_inner, width=80,
                                         fg_color=COLOR_INSET, border_color=COLOR_ENTRY_BORDER)
        self.tel_cooldown.grid(row=7, column=1, pady=4, sticky="w")

        lvf = ctk.CTkFrame(tel_inner, fg_color="transparent")
        lvf.grid(row=8, column=0, columnspan=2, pady=4, sticky="w")
        ctk.CTkLabel(lvf, text="Uyarı düzeyi:", font=ctk.CTkFont(size=11),
                     text_color=COLOR_TEXT).pack(side="left", padx=(0, 8))
        self.tel_lv = {}
        for key, label in [("red", "Kırmızı"), ("orange", "Turuncu"), ("yellow", "Sarı")]:
            cb = ctk.CTkCheckBox(lvf, text=label, font=ctk.CTkFont(size=11))
            cb.pack(side="left", padx=6)
            self.tel_lv[key] = cb

        tbf2 = ctk.CTkFrame(tel_inner, fg_color="transparent")
        tbf2.grid(row=9, column=0, columnspan=2, pady=6, sticky="w")
        ctk.CTkButton(tbf2, text="Filtreleri Kaydet", font=ctk.CTkFont(size=10),
                      fg_color=COLOR_ACCENT_DEEP, hover_color="#0D9488",
                      command=self.save_tel_filters, width=110, height=28).pack(side="left", padx=(0, 6))
        ctk.CTkButton(tbf2, text="Geçmişi Yenile", font=ctk.CTkFont(size=10),
                      fg_color=COLOR_BTN_SEC_BG, hover_color=COLOR_BTN_SEC_HOVER, text_color=COLOR_TEXT, border_width=1,
                      border_color=COLOR_CARD_BORDER,
                      command=self.refresh_notif_log, width=110, height=28).pack(side="left")
        self.tel_filter_status = ctk.CTkLabel(tel_inner, text="", font=ctk.CTkFont(size=10),
                                              text_color=COLOR_SUCCESS)
        self.tel_filter_status.grid(row=10, column=0, columnspan=2, sticky="w")

        self.notif_scroll = ctk.CTkScrollableFrame(tel_inner, fg_color=COLOR_INSET,
                                                   corner_radius=6, height=110)
        self.notif_scroll.grid(row=11, column=0, columnspan=2, pady=(4, 0), sticky="ew")

        try:
            from deprem_izleme.config import load_settings as _lsn
            _sn = _lsn()
            if _sn.get("telegram_enabled", True):
                self.tel_enable.select()
            else:
                self.tel_enable.deselect()
            self.tel_threshold.insert(0, str(_sn.get("telegram_threshold", 0.6)))
            self.tel_cooldown.insert(0, str(_sn.get("telegram_cooldown_h", 6)))
            _lvs = _sn.get("telegram_levels", ["red", "orange"]) or []
            for _k, _cb in self.tel_lv.items():
                if _k in _lvs:
                    _cb.select()
                else:
                    _cb.deselect()
        except Exception:
            pass

        # --- Manual Actions ---
        act_card = self._make_card(p, "İşlemler")
        act_card.pack(fill="x", padx=28, pady=5)

        act_inner = ctk.CTkFrame(act_card, fg_color="transparent")
        act_inner.pack(fill="x", padx=14, pady=(0, 14))

        ctk.CTkButton(act_inner, text="Sismik Harita API", font=ctk.CTkFont(size=11),
                      fg_color=COLOR_ACCENT_DEEP, hover_color="#0D9488", command=self.do_fetch_sismik,
                      height=32, width=150).pack(side="left", padx=(0, 6))
        ctk.CTkButton(act_inner, text="KOERI (Kandilli)", font=ctk.CTkFont(size=11),
                      fg_color=COLOR_BTN_SEC_BG, hover_color=COLOR_BTN_SEC_HOVER, text_color=COLOR_TEXT, border_width=1,
                      border_color=COLOR_CARD_BORDER, command=self.do_fetch_koeri,
                      height=32, width=150).pack(side="left", padx=6)
        ctk.CTkButton(act_inner, text="Rapor Güncelle", font=ctk.CTkFont(size=11),
                      fg_color=COLOR_BTN_SEC_BG, hover_color=COLOR_BTN_SEC_HOVER, text_color=COLOR_TEXT, border_width=1,
                      border_color=COLOR_CARD_BORDER, command=self.refresh_all,
                      height=32, width=130).pack(side="left", padx=6)
        ctk.CTkButton(act_inner, text="Alarm Kontrol", font=ctk.CTkFont(size=11),
                      fg_color=COLOR_BTN_SEC_BG, hover_color=COLOR_BTN_SEC_HOVER, text_color=COLOR_TEXT, border_width=1,
                      border_color=COLOR_CARD_BORDER, command=self.do_alert,
                      height=32, width=130).pack(side="left", padx=6)

        self.act_status = ctk.CTkLabel(act_inner, text="", font=ctk.CTkFont(size=10),
                                        text_color=COLOR_TEXT2)
        self.act_status.pack(anchor="w", pady=(6, 0))

        # Info
        info_card = self._make_card(p, "Bilgi")
        info_card.pack(fill="x", padx=28, pady=5)
        ctk.CTkLabel(info_card, text=
            "Bölge: Marmara Denizi + İstanbul (40.5°K–41.5°K, 27.0°D–30.0°D)\n"
            "Ana Kaynak: Sismik Harita API (ücretsiz, 100 istek/gün)\n"
            "Ek Kaynak: KOERI Kandilli Rasathanesi\n"
            "API: Anahtar gerekmez, CORS açık, 1000 deprem/istek limiti\n"
            "Veritabanı: data/ klasöründe SQLite (depremler.db)\n"
            "Veri kaynağı: Sismik Harita (sismikharita.com)",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT, justify="left"
        ).pack(anchor="w", padx=14, pady=(0, 12))

        # --- Uygulama (sürüm + GitHub + lisans) ---
        try:
            from deprem_izleme.config import APP_VERSION, APP_NAME, GITHUB_URL, GITHUB_OWNER
        except Exception:
            APP_VERSION, APP_NAME, GITHUB_URL, GITHUB_OWNER = "?", "Deprem Analiz - Marmara", "", ""
        app_card = self._make_card(p, "Uygulama")
        app_card.pack(fill="x", padx=28, pady=5)
        app_inner = ctk.CTkFrame(app_card, fg_color="transparent")
        app_inner.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkLabel(app_inner,
                     text=f"{APP_NAME}  •  Sürüm v{APP_VERSION}  •  Lisans: MIT  •  GitHub: {GITHUB_OWNER}",
                     font=ctk.CTkFont(size=11),
                     text_color=COLOR_TEXT).pack(anchor="w", pady=(0, 6))
        abtn = ctk.CTkFrame(app_inner, fg_color="transparent")
        abtn.pack(anchor="w")
        ctk.CTkButton(abtn, text="GitHub'da Aç", font=ctk.CTkFont(size=10),
                      fg_color=COLOR_BTN_SEC_BG, hover_color=COLOR_BTN_SEC_HOVER,
                      text_color=COLOR_TEXT, border_width=1, border_color=COLOR_CARD_BORDER,
                      command=lambda: self._open_external(GITHUB_URL),
                      height=28, width=110).pack(side="left", padx=(0, 6))
        ctk.CTkButton(abtn, text="Tanıtımı Göster", font=ctk.CTkFont(size=10),
                      fg_color=COLOR_BTN_SEC_BG, hover_color=COLOR_BTN_SEC_HOVER,
                      text_color=COLOR_TEXT, border_width=1, border_color=COLOR_CARD_BORDER,
                      command=lambda: self._show_welcome(preview=True),
                      height=28, width=120).pack(side="left")

        # --- Güncellemeler ---
        upd_card = self._make_card(p, "Güncellemeler")
        upd_card.pack(fill="x", padx=28, pady=(5, 20))
        upd_inner = ctk.CTkFrame(upd_card, fg_color="transparent")
        upd_inner.pack(fill="x", padx=14, pady=(0, 14))
        self.upd_auto = ctk.CTkSwitch(upd_inner, text="Açılışta otomatik denetle",
                                      font=ctk.CTkFont(size=11),
                                      command=self._save_upd_pref)
        self.upd_auto.pack(anchor="w", pady=(0, 6))
        try:
            from deprem_izleme.config import load_settings as _lsu
            if _lsu().get("auto_update_check", True):
                self.upd_auto.select()
            else:
                self.upd_auto.deselect()
        except Exception:
            pass
        urow = ctk.CTkFrame(upd_inner, fg_color="transparent")
        urow.pack(anchor="w")
        ctk.CTkButton(urow, text="Güncellemeleri Denetle", font=ctk.CTkFont(size=10),
                      fg_color=COLOR_ACCENT_DEEP,
                      command=self.check_update_manual,
                      height=28, width=160).pack(side="left", padx=(0, 10))
        self.upd_status = ctk.CTkLabel(urow, text=f"Yüklü sürüm: v{APP_VERSION}",
                                       font=ctk.CTkFont(size=10),
                                       text_color=COLOR_TEXT2)
        self.upd_status.pack(side="left")

    # ================================================================
    # BACKGROUND WORKER
    # ================================================================

    def _restart_app(self):
        """Uygulamayı yeniden başlat (tema değişikliği için)."""
        import sys as _s
        import os as _o
        try:
            if getattr(_s, "frozen", False):
                _o.startfile(_s.executable)
            else:
                import subprocess as _sp
                # argv[0] göreli olabilir (örn. "main.py"); mutlaklaştır
                _script = _o.path.abspath(_s.argv[0])
                _sp.Popen([_s.executable] + [_script] + _s.argv[1:],
                          cwd=_o.path.dirname(_o.path.abspath(__file__)))
        except Exception as e:
            try:
                from tkinter import messagebox as _mb
                _mb.showerror("Yeniden başlatılamadı",
                              f"Uygulamayı el ile kapatıp açın.\n\nHata: {e}")
            except Exception:
                pass
            return False
        self._alive = False
        try:
            self.destroy()
        except Exception:
            pass
        _o._exit(0)

    def _ask_restart_for_theme(self):
        from tkinter import messagebox as _mb
        if _mb.askyesno("Tema Değişti",
                        "Yeni tema için uygulama yeniden başlatılsın mı?"):
            self._restart_app()

    # ---------------------------------------------------------------
    # Karşılama (ilk çalıştırma) + güncelleme
    # ---------------------------------------------------------------
    def _maybe_show_welcome(self):
        """İlk açılışta API kurulum kutusu (güncellemelerde tekrar çıkmaz)."""
        try:
            from deprem_izleme.config import load_settings, save_settings
            if load_settings().get("welcome_shown"):
                return
        except Exception:
            pass
        try:
            self._show_welcome()
        except Exception as ex:
            try:
                from deprem_izleme.errors import log_error
                log_error(ex, "welcome")
            except Exception:
                pass

    def _center_on_app(self, win, w, h):
        """Pencereyi uygulama üzerinde ortala (ekrana kelepçeli)."""
        try:
            win.update_idletasks()
            x = self.winfo_x() + (self.winfo_width() - w) // 2
            y = self.winfo_y() + (self.winfo_height() - h) // 2
            sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
            x = max(0, min(x, sw - w - 10))
            y = max(0, min(y, sh - h - 40))
            win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _show_welcome(self, preview=False):
        """Sismik Harita API kurulum rehberi. preview=True: ayarlardan tekrar gösterim."""
        import customtkinter as ctk
        try:
            from deprem_izleme.config import save_settings
        except Exception:
            save_settings = None
        win = ctk.CTkToplevel(self)
        win.title("Deprem Analiz - Marmara'ya Hoş Geldiniz")
        win.resizable(False, False)
        self._center_on_app(win, 560, 480)
        try:
            win.transient(self)
        except Exception:
            pass
        try:
            win.grab_set()
        except Exception:
            pass
        closed = {"done": False}

        def _finish():
            if closed["done"]:
                return
            closed["done"] = True
            if not preview and save_settings:
                try:
                    save_settings({"welcome_shown": True})
                except Exception:
                    pass
            try:
                win.grab_release()
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass

        try:
            win.protocol("WM_DELETE_WINDOW", _finish)
        except Exception:
            pass
        ctk.CTkLabel(win, text="Deprem Analiz - Marmara'ya Hoş Geldiniz",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=COLOR_TEXT).pack(anchor="w", padx=24, pady=(22, 4))
        ctk.CTkLabel(win, text="Veri kaynağını 2 dakikada bağlayın",
                     font=ctk.CTkFont(size=12),
                     text_color=COLOR_TEXT2).pack(anchor="w", padx=24, pady=(0, 12))
        steps = ctk.CTkFrame(win, fg_color=COLOR_CARD_BG, corner_radius=10,
                             border_width=1, border_color=COLOR_CARD_BORDER)
        steps.pack(fill="x", padx=24, pady=(0, 12))
        body = (
            "1. API anahtarı ZORUNLU DEĞİL — anahtarsız günde 100 istek kullanırsınız.\n\n"
            "2. Anahtarınız varsa: sol menüden Ayarlar → Sismik Harita API bölümüne\n"
            "    yapıştırın → Kaydet → Bağlantıyı Test Et düğmesine basın.\n\n"
            "3. Anahtar için: sismikharita.com/api sayfasından giriş yapın ya da\n"
            "    kayıt olun; anahtarınız otomatik oluşur (ücretsiz planda da çalışır)."
        )
        ctk.CTkLabel(steps, text=body, font=ctk.CTkFont(size=12),
                     text_color=COLOR_TEXT, justify="left",
                     anchor="w").pack(anchor="w", padx=16, pady=14)
        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=24, pady=(0, 20))
        ctk.CTkButton(btns, text="API Sayfasını Aç", font=ctk.CTkFont(size=11),
                      fg_color=COLOR_BTN_SEC_BG, hover_color=COLOR_BTN_SEC_HOVER,
                      text_color=COLOR_TEXT, border_width=1, border_color=COLOR_CARD_BORDER,
                      command=lambda: self._open_url("https://sismikharita.com/api"),
                      height=32, width=120).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Ayarlar'a Git", font=ctk.CTkFont(size=11),
                      fg_color=COLOR_BTN_SEC_BG, hover_color=COLOR_BTN_SEC_HOVER,
                      text_color=COLOR_TEXT, border_width=1, border_color=COLOR_CARD_BORDER,
                      command=lambda: (self.switch_page("ayarlar"), _finish()),
                      height=32, width=110).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="Başla", font=ctk.CTkFont(size=11),
                      fg_color=COLOR_ACCENT_DEEP,
                      command=_finish, height=32, width=110).pack(side="right")

    def _open_external(self, url):
        """Ayarlar/GitHub bağlantıları için bağımsız URL açıcı."""
        try:
            import webbrowser
            u = (url or "").strip()
            if u.lower().startswith(("http://", "https://")):
                webbrowser.open(u)
        except Exception:
            pass

    def _save_upd_pref(self):
        try:
            from deprem_izleme.config import save_settings
            save_settings({"auto_update_check": bool(self.upd_auto.get())})
        except Exception:
            pass

    def check_update_manual(self):
        """Ayarlar düğmesi: güncellemeyi denetle (arka plan)."""
        try:
            self.upd_status.configure(text="Denetleniyor...", text_color=COLOR_WARNING)
        except Exception:
            pass
        threading.Thread(target=self._update_check_worker, args=(True,), daemon=True).start()

    def _update_auto_check(self):
        """Açılışta sessiz denetim (ayar açıksa)."""
        try:
            from deprem_izleme.config import load_settings
            if not load_settings().get("auto_update_check", True):
                return
        except Exception:
            pass
        threading.Thread(target=self._update_check_worker, args=(False,), daemon=True).start()

    def _update_check_worker(self, manual):
        try:
            from deprem_izleme import updater as _upd
            info = _upd.check_for_updates()
        except Exception as ex:
            info = None
            try:
                from deprem_izleme.errors import log_error
                log_error(ex, "update-check")
            except Exception:
                pass
        self._post_ui(lambda: self._update_check_done(info, manual))

    def _update_check_done(self, info, manual):
        try:
            from deprem_izleme.config import APP_VERSION
        except Exception:
            APP_VERSION = "?"
        if not info:
            try:
                self.upd_status.configure(text=f"Güncel (v{APP_VERSION})",
                                          text_color=COLOR_SUCCESS)
            except Exception:
                pass
            if manual:
                try:
                    from tkinter import messagebox as _mb
                    _mb.showinfo("Güncelleme", f"Uygulama güncel (v{APP_VERSION}).")
                except Exception:
                    pass
            return
        try:
            self.upd_status.configure(text=f"Yeni sürüm: v{info['version']}",
                                      text_color=COLOR_WARNING)
        except Exception:
            pass
        try:
            from tkinter import messagebox as _mb
            notes = (info.get("notes") or "")[:600]
            msg = (f"Yeni sürüm bulundu: v{info['version']} "
                   f"(yüklü: v{APP_VERSION}).\n\n{notes}\n\nŞimdi güncellensin mi?\n"
                   f"(Verileriniz korunur.)")
            if _mb.askyesno("Güncelleme Var", msg):
                self._start_update_apply(info)
        except Exception:
            pass

    def _start_update_apply(self, info):
        try:
            self.upd_status.configure(text="İndiriliyor...", text_color=COLOR_WARNING)
        except Exception:
            pass
        threading.Thread(target=self._update_apply_worker, args=(info,), daemon=True).start()

    def _update_apply_worker(self, info):
        try:
            from deprem_izleme import updater as _upd
            ok, msg = _upd.download_and_apply(info, on_quit=self._quit_for_update)
        except Exception as ex:
            ok, msg = False, f"Hata: {ex}"
        self._post_ui(lambda: self._update_apply_done(ok, msg, info))

    def _update_apply_done(self, ok, msg, info):
        try:
            self.upd_status.configure(text=msg,
                                      text_color=COLOR_SUCCESS if ok else COLOR_DANGER)
        except Exception:
            pass
        if not ok:
            try:
                from tkinter import messagebox as _mb
                page = (info or {}).get("page", "")
                _mb.showwarning("Güncelleme", f"{msg}\n{page}")
            except Exception:
                pass

    def _quit_for_update(self):
        """Güncelleyici .bat devralır; uygulamayı sessizce kapat."""
        try:
            self._alive = False
            self.bg_running = False
            self.destroy()
        except Exception:
            pass
        try:
            import os as _o
            _o._exit(0)
        except Exception:
            pass

    def _on_theme_dashboard(self, choice):
        from deprem_izleme.config import save_settings
        save_settings({"appearance": "light" if choice == "Açık" else "dark"})
        self._ask_restart_for_theme()

    def _on_theme(self, choice):
        from deprem_izleme.config import save_settings
        save_settings({"appearance": "light" if choice == "Açık" else "dark"})
        self.theme_status.configure(text="Kaydedildi")
        self._ask_restart_for_theme()

    def _toggle_bg(self):
        if self.bg_switch.get():
            self.bg_running = True
            self.bg_status.configure(text="Çalışıyor...", text_color=COLOR_SUCCESS)
            self.bg_thread = threading.Thread(target=self._bg_loop, daemon=True)
            self.bg_thread.start()
        else:
            self.bg_running = False
            self.bg_status.configure(text="⏸️ Durduruldu", text_color=COLOR_TEXT2)

    def _on_bg_interval(self, choice):
        """Aralık değişimi ana thread'de önbelleğe alınır (worker okur)."""
        try:
            self.bg_interval = int(str(choice).split()[0])
        except Exception:
            pass

    def _bg_loop(self):
        import time as _lt
        while self.bg_running:
            now = datetime.now()
            # Günlük sayacı sıfırla
            if now.date() != self.daily_request_date:
                self.daily_request_date = now.date()
                self.daily_request_count = 0

            if self.daily_request_count < DAILY_LIMIT:
                try:
                    # Fetch (atla hata olursa, sıraya alma)
                    try:
                        c = fetch_and_store(days_back=3, min_magnitude=0.0)
                        self._bump_api_use()

                        # KOERI'yi de dene
                        try:
                            kquakes = fetch_koeri()
                            for kq in kquakes:
                                try:
                                    insert_earthquake(kq, region_tag=kq.get("region_tag", "marmara"))
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        self._post_ui( self._update_bg_ui)
                    except Exception as e:
                        _emsg = str(e)
                        self._post_ui(lambda e=_emsg: self.sidebar_bg_label.configure(
                            text=f"Hata: {e}", text_color=COLOR_DANGER))
                except Exception:
                    pass
            else:
                self._post_ui( lambda: self.bg_status.configure(
                    text=f"⏸️ Limit doldu ({DAILY_LIMIT}/{DAILY_LIMIT})", text_color=COLOR_WARNING))

            # Bekle (10'ar sn dilimlerle; aralık değişimi anında geçerli olur)
            try:
                end = _lt.monotonic() + int(self.bg_interval) * 60
            except Exception:
                end = _lt.monotonic() + 3600
            while self.bg_running and _lt.monotonic() < end:
                _lt.sleep(10)

    def _update_bg_ui(self):
        self.refresh_all()
        self.bg_count_label.configure(
            text=f"Bugün kullanılan: {self.daily_request_count}/{DAILY_LIMIT}")
        self.bg_status.configure(text=f"🔄 Son çalıştı: {datetime.now().strftime('%H:%M')}",
                                  text_color=COLOR_SUCCESS)

    # ================================================================
    # REFRESH
    # ================================================================

    def do_fetch_and_refresh(self):
        """API'den veri çek + ekranı güncelle (tek tuş)."""
        self.dash_status.configure(text="📡 Veri çekiliyor...", text_color=COLOR_WARNING)
        threading.Thread(target=self._fetch_and_refresh_worker, daemon=True).start()

    def _fetch_and_refresh_worker(self):
        try:
            from deprem_izleme.fetcher import fetch_and_store
            c = fetch_and_store(days_back=3, min_magnitude=0.0)
            self._bump_api_use()
            # KOERI'den de dene
            kc, kerr = 0, ""
            try:
                from deprem_izleme.fetcher_koeri import fetch_koeri
                from deprem_izleme.db import insert_earthquake
                klist = fetch_koeri()
                for kq in klist:
                    insert_earthquake(kq, region_tag=kq.get("region_tag", "marmara"))
                kc = len(klist)
            except Exception as ke:
                kerr = f" (KOERI: {friendly_error(ke)})"
            # Veriyi ekrana yansıt
            self._post_ui( self.refresh_all)
            self._post_ui(lambda: self.dash_status.configure(
                text=f"✅ Sismik: {c} yeni + KOERI: {kc} kayıt{kerr}", text_color=COLOR_SUCCESS))
        except Exception as e:
            _emsg = friendly_error(e)
            self._post_ui(lambda e=_emsg: self.dash_status.configure(
                text=e, text_color=COLOR_DANGER))

    def refresh_all(self):
        def worker():
            try:
                # Geçmiş tablolarını doldur (veri geldikçe tamamlanır)
                self._maybe_backfill()
                self._refreshed_once = True

                days = self.current_time_filter
                r = get_comprehensive_risk_report(region="marmara")
                p = EarthquakePredictor(region="marmara").predict_short_term()
                eqs = get_earthquakes(
                    since=datetime.now() - timedelta(days=days),
                    region="marmara", limit=200
                )
                st = get_stats(region="marmara")
                wh = get_weekly_history(limit=24, region="marmara")
                mh = get_monthly_history(limit=24, region="marmara")

                mags = [e["magnitude"] for e in eqs if e.get("magnitude")]
                bv, av, bmc = calculate_b_value(mags) if mags else (1.0, 3.0, 0.0)
                t_obs = catalog_span_days(eqs)
                rec = get_recurrence_report(mags, bv, av, t_obs_days=t_obs)
                rec_meta = {"t_obs": round(t_obs, 1), "n": len(mags), "mc": round(bmc, 2)}

                self._post_ui( lambda r=r, p=p, eqs=eqs, st=st, wh=wh, mh=mh, rec=rec, bv=bv, av=av, rec_meta=rec_meta:
                           self._apply_data(r, p, eqs, st, wh, mh, rec, bv, av, rec_meta))
            except Exception as ex:
                err = friendly_error(ex)
                self._post_ui( lambda e=err: self.dash_status.configure(
                    text=f"Güncelleme hatası: {e}", text_color=COLOR_DANGER))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_data(self, r, p, eqs, st, wh, mh, rec, bv, av, rec_meta=None):
        self.risk_report = r
        self.prediction = p
        self.earthquakes = eqs
        self.stats_data = st
        self.weekly_history = wh
        self.monthly_history = mh
        self.recurrence_data = rec
        self.rec_meta = rec_meta or {}

        self._update_dashboard()
        # İkincil sayfalar henüz kurulmadıysa (açılış yarışı) atla;
        # her sayfa kendi guard'ında güncellenir, biri patlarsa diğerleri etkilenmez.
        for _pg, _fn in (("risk-analiz", self._update_risk_analysis),
                         ("tekrarlama", self._update_recurrence),
                         ("gecmis", self._update_history),
                         ("tahmin", self._update_prediction)):
            if _pg not in self.pages:
                continue
            try:
                _fn()
            except Exception as ex:
                try:
                    from deprem_izleme.errors import log_error
                    log_error(ex, f"sayfa guncelleme: {_pg}")
                except Exception:
                    pass
        try:
            if hasattr(self, "embedded_map") and "harita" in self.pages:
                try:
                    self._sync_map_db_layer()
                except Exception:
                    pass
        except Exception:
            pass
        self._update_charts()
        self._update_sidebar()

        self.dash_status.configure(text=f"✅ Güncellendi: {datetime.now().strftime('%H:%M:%S')}",
                                    text_color=COLOR_SUCCESS)
        try:
            self.now_label.configure(text="  •  ".join(interpret_now(r, p)))
        except Exception:
            pass
        if r.get("no_data"):
            self.dash_status.configure(
                text=(f"⚠️ Son 30 günde yeterli veri yok ({r.get('quake_count', 0)} deprem) — "
                      "sayılar varsayılan; 'Verileri Çek & Güncelle'ye basın"),
                text_color=COLOR_WARNING)

    def _chart_placeholder(self, frame, text="Grafik hazırlanıyor..."):
        for w in frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(frame, text=text, font=ctk.CTkFont(size=10),
                     text_color=COLOR_TEXT2).pack(expand=True, pady=20)

    def _update_charts(self):
        """Grafikleri güncelle - figür arka planda kurulur, canvas ana thread'de."""
        threading.Thread(target=self._charts_worker, daemon=True).start()

    def _charts_worker(self):
        try:
            from deprem_izleme.charts import build_risk_trend_figure, build_daily_count_figure
            scope = max(self.current_time_filter, 1)
            fig1 = build_risk_trend_figure(width=4.5, height=2.2, days=scope)
            fig2 = build_daily_count_figure(days=scope, width=4.5, height=2.2)
            self._post_ui( lambda: self._attach_dashboard_charts(fig1, fig2))
        except Exception as ex:
            err = str(ex)
            self._post_ui( lambda e=err: self._charts_error(e))

    def _attach_dashboard_charts(self, fig1, fig2):
        from deprem_izleme.charts import _attach_canvas
        for w in self.risk_chart_frame.winfo_children():
            w.destroy()
        for w in self.count_chart_frame.winfo_children():
            w.destroy()
        try:
            c, f = _attach_canvas(self.risk_chart_frame, fig1)
            c.get_tk_widget().pack(fill="both", expand=True)
            self.risk_canvas = c
        except Exception as e:
            ctk.CTkLabel(self.risk_chart_frame, text=f"Grafik: {e}",
                         font=ctk.CTkFont(size=9), text_color="#ef4444").pack()
        try:
            c2, f2 = _attach_canvas(self.count_chart_frame, fig2)
            c2.get_tk_widget().pack(fill="both", expand=True)
            self.count_canvas = c2
        except Exception as e:
            ctk.CTkLabel(self.count_chart_frame, text=f"Grafik: {e}",
                         font=ctk.CTkFont(size=9), text_color="#ef4444").pack()

    def _charts_error(self, err):
        for frame in (self.risk_chart_frame, self.count_chart_frame):
            for w in frame.winfo_children():
                w.destroy()
            ctk.CTkLabel(frame, text=f"Grafik: {err}",
                         font=ctk.CTkFont(size=9), text_color="#ef4444").pack()

    # ================================================================
    # UPDATE VIEWS
    # ================================================================

    def _update_dashboard(self):
        r, p = self.risk_report, self.prediction
        if not r or not p: return

        score = r["composite_risk_score"]
        color = self._risk_color(score)

        self.risk_gauge.set(min(score, 1.0))
        self.risk_gauge.configure(progress_color=color)
        self.risk_gauge_label.configure(text=f"Risk: {score:.4f}", text_color=color)
        self.risk_chip.configure(fg_color=color)
        self.risk_gauge_level.configure(text=r['risk_level'])

        self.metric_widgets["b-değeri"].configure(
            text=(f"{r['gutenberg_richter']['b_value']:.3f}"
                  if r.get("quake_count", 0) >= 10 else
                  f"{r['gutenberg_richter']['b_value']:.3f}*"))
        self.metric_widgets["M≥4.0 7g"].configure(text=f"%{r['poisson']['p_m4_7days_pct']:.1f}")
        st = self.stats_data
        self.metric_widgets["Son 24h"].configure(text=f"{st.get('son_24h', 0)}")
        e = r['energy']['total_energy_joules']
        if e >= 1e9:
            es = f"{e/1e9:.1f} GJ"
        elif e >= 1e6:
            es = f"{e/1e6:.1f} MJ"
        else:
            es = f"{e:.1e} J"
        self.metric_widgets["Enerji"].configure(text=es)

        self.status_widgets["Trend"].configure(text=self._trend_tr(p.get('trend', '?')),
                                                text_color=self._warn_color(p.get('warning_level', 'green')))
        self.status_widgets["Uyarı"].configure(text=self._warn_tr(p.get('warning_level', 'green')),
                                                text_color=self._warn_color(p.get('warning_level', 'green')))
        self.status_widgets["Deprem Sayısı"].configure(text=str(len(self.earthquakes)))
        if self.earthquakes:
            last = self.earthquakes[0]
            loc = (last.get("location") or "?")[:35]
            _lm = last.get("magnitude")
            self.status_widgets["Son Deprem"].configure(
                text=f"M{_lm:.1f} {loc}" if _lm else f"M?.. {loc}")

        # Quake list — DÜZGÜN TABLO TASARIMI
        for w in self.quake_scroll.winfo_children():
            w.destroy()

        if self.earthquakes:
            # Header
            hdr = ctk.CTkFrame(self.quake_scroll, fg_color=COLOR_INSET, corner_radius=6, height=30)
            hdr.pack(fill="x", pady=(0, 3))
            hdr.pack_propagate(False)
            for i, (h, w) in enumerate([("Magnitüd", 80), ("Tarih", 95), ("Derinlik", 70), ("Konum", 250), ("Bölge", 60)]):
                ctk.CTkLabel(hdr, text=h, font=ctk.CTkFont(size=9, weight="bold"),
                             text_color=COLOR_INFO, width=w).pack(side="left", padx=4)

            for idx, eq in enumerate(self.earthquakes[:25]):
                mag = eq.get("magnitude")
                depth = eq.get("depth_km")
                loc = (eq.get("location") or "?")[:42]
                ts_raw = (eq.get("occurred_at") or "?")
                ts = ts_raw[5:16] if len(ts_raw) > 15 else ts_raw
                tag = eq.get("region_tag", "?").upper()

                if mag is None:
                    mc = COLOR_TEXT2
                elif mag >= 4.0: mc = COLOR_VERY_HIGH
                elif mag >= 3.0: mc = COLOR_MODERATE
                elif mag >= 2.0: mc = COLOR_HIGH
                else: mc = COLOR_LOW
                bg = COLOR_INSET

                row = ctk.CTkFrame(self.quake_scroll, fg_color=bg, corner_radius=4, height=26)
                row.pack(fill="x", pady=1)
                row.pack_propagate(False)

                ctk.CTkLabel(row, text=f"M{mag:.1f}" if mag is not None else "M?..", font=ctk.CTkFont(size=10, weight="bold"),
                             text_color=mc, width=80).pack(side="left", padx=4)
                ctk.CTkLabel(row, text=ts, font=ctk.CTkFont(size=9),
                             text_color=COLOR_BODY, width=95).pack(side="left")
                ctk.CTkLabel(row, text=f"{depth:.0f} km" if depth is not None else "? km", font=ctk.CTkFont(size=9),
                             text_color=COLOR_DIM, width=70).pack(side="left")
                ctk.CTkLabel(row, text=loc, font=ctk.CTkFont(size=9),
                             text_color=COLOR_BODY, width=250, anchor="w").pack(side="left")
                ctk.CTkLabel(row, text=tag, font=ctk.CTkFont(size=8, weight="bold"),
                             text_color=COLOR_INFO, width=60).pack(side="left")
        else:
            ctk.CTkLabel(self.quake_scroll, text="Henüz deprem verisi yok.",
                         font=ctk.CTkFont(size=11), text_color=COLOR_TEXT2).pack(pady=20)

    def _update_risk_analysis(self):
        r, p = self.risk_report, self.prediction
        if not r or not p: return

        mapping = {
            "Bileşik Risk": {
                "Risk Skoru": f"{r['composite_risk_score']:.4f}",
                "Risk Seviyesi": r['risk_level'],
                "Uyarı Seviyesi": self._warn_tr(p.get('warning_level', 'green')),
                "b Anomalisi": f"{r['gutenberg_richter']['b_anomaly']:+.4f}",
            },
            "Gutenberg-Richter": {
                "b-değeri": f"{r['gutenberg_richter']['b_value']:.3f}",
                "b-σ": f"±{r['gutenberg_richter'].get('b_std', 0):.3f}",
                "Mc": f"M{r['gutenberg_richter']['magnitude_completeness']:.1f}",
                "a-değeri": f"{r['gutenberg_richter']['a_value']:.3f}",
                "Beklenen Mmax": f"M{r['gutenberg_richter']['expected_max_magnitude']:.1f}",
                "Gözlenen Mmax": f"M{r['gutenberg_richter']['observed_max_magnitude']:.1f}",
            },
            "Poisson": {
                "λ M≥3.0 (/gün)": f"{r['poisson']['lambda_m3_per_day']:.4f}",
                "λ M≥4.0 (/gün)": f"{r['poisson']['lambda_m4_per_day']:.4f}",
                "λ M≥4.0 zemin": f"{r['poisson'].get('lambda_m4_bg_per_day', 0):.4f}",
                "P(M≥4.0) 7gün": f"%{r['poisson']['p_m4_7days_pct']:.1f}",
                "P(M≥4.0) 30gün": f"%{r['poisson']['p_m4_30days_pct']:.1f}",
            },
            "Enerji": {
                "Toplam Enerji": f"{r['energy']['total_energy_joules']:.2e} J",
                "TNT Eşdeğeri": f"{r['energy']['total_energy_tnt_tons']:.1f} ton",
            },
            "Trend & Anomali": {
                "b-trendi": f"{p.get('b_trend', 0):+.4f}",
                "Z-Skor": f"{p.get('anomaly_z_score', 0):.2f}",
                "Trend Yönü": self._trend_tr(p.get('trend', 'stable')),
                "Enerji Oranı": f"{p.get('energy_ratio', 1.0):.2f}x",
            },
        }
        for section, fields in mapping.items():
            if section in self.risk_sections:
                for field, val in fields.items():
                    if field in self.risk_sections[section]:
                        lbl = self.risk_sections[section][field]
                        lbl.configure(text=val)
                        c = self._risk_color(r['composite_risk_score'])
                        if field in ("Risk Skoru", "Risk Seviyesi"):
                            lbl.configure(text_color=c)
                        elif field == "Uyarı Seviyesi":
                            lbl.configure(text_color=self._warn_color(p.get('warning_level', 'green')))

        # Fay segmentleri
        fault_segments = r.get("fault_risk", {}).get("segments", [])
        for w in self.fault_scores_frame.winfo_children():
            w.destroy()
        if fault_segments:
            # Header row
            hd = ctk.CTkFrame(self.fault_scores_frame, fg_color=COLOR_INSET, corner_radius=4, height=24)
            hd.pack(fill="x", pady=(0, 2))
            widths = [150, 60, 60, 95, 95]
            for i, h in enumerate(["Segment", "Risk", "Mmax", "Son Kırılma", "Yakın Deprem"]):
                ctk.CTkLabel(hd, text=h, font=ctk.CTkFont(size=8, weight="bold"),
                             text_color=COLOR_ACCENT, width=widths[i]).pack(side="left", padx=(6 if i == 0 else 1, 1))
            # Data rows
            for seg in fault_segments:
                row = ctk.CTkFrame(self.fault_scores_frame, fg_color=COLOR_INSET, corner_radius=2)
                row.pack(fill="x", pady=1)
                sc = seg.get("score", 0)
                color = self._risk_color(sc)
                last = seg.get("time_since_last")
                last_str = str(last) if last else "Hiç"
                vals = [
                    seg.get("name_tr", seg.get("name_en", "?")),
                    f"{sc:.3f}",
                    f"M{seg.get('max_magnitude'):.1f}" if seg.get("max_magnitude") is not None else "M?..",
                    last_str,
                    f"{seg.get('nearby_quakes', 0)} deprem",
                ]
                for i, v in enumerate(vals):
                    ctk.CTkLabel(row, text=v, font=ctk.CTkFont(size=8),
                                 text_color=color if i == 1 else COLOR_TEXT,
                                 width=widths[i], anchor="w").pack(side="left", padx=(6 if i == 0 else 1, 1))

    def _update_recurrence(self):
        rec = self.recurrence_data
        meta = getattr(self, "rec_meta", {}) or {}
        if hasattr(self, "rec_meta_label"):
            if meta:
                self.rec_meta_label.configure(
                    text=(f"Katalog: {meta.get('n', 0)} deprem, "
                          f"{meta.get('t_obs', 0)} gün pencere, "
                          f"Mc M{meta.get('mc', 0):.1f} (MAXC)"))
            else:
                self.rec_meta_label.configure(text="")
        for w in self.rec_inner.winfo_children():
            w.destroy()

        headers = ["Magnitüd", "Tekrarlama Süresi", "Yıllık Frekans"]
        for i, h in enumerate(headers):
            ctk.CTkLabel(self.rec_inner, text=h, font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=COLOR_ACCENT).grid(row=0, column=i, padx=12, pady=(0, 4), sticky="w")

        if rec and "error" not in rec:
            for idx, item in enumerate(rec):
                m = item['magnitude']
                text = item.get('text', '∞')
                if item.get('years') and item['years'] < 100:
                    freq = f"{1/item['years']:.2f}/yıl" if item['years'] > 0 else "—"
                elif item.get('days'):
                    freq = f"{365.25/item['days']:.1f}/yıl" if item['days'] > 0 else "—"
                else:
                    freq = "—"

                ctk.CTkLabel(self.rec_inner, text=f"M≥{m:g}", font=ctk.CTkFont(size=12, weight="bold"),
                             text_color=COLOR_TEXT).grid(row=idx + 1, column=0, padx=12, pady=2, sticky="w")
                ctk.CTkLabel(self.rec_inner, text=text, font=ctk.CTkFont(size=11),
                             text_color=COLOR_TEXT).grid(row=idx + 1, column=1, padx=12, pady=2, sticky="w")
                ctk.CTkLabel(self.rec_inner, text=freq, font=ctk.CTkFont(size=11),
                             text_color=COLOR_TEXT2).grid(row=idx + 1, column=2, padx=12, pady=2, sticky="w")
        else:
            ctk.CTkLabel(self.rec_inner, text="Seçili aralıkta yeterli veri yok.",
                         font=ctk.CTkFont(size=11), text_color=COLOR_WARNING).grid(row=1, column=0, columnspan=3, pady=10)

    def _update_history(self):
        try:
            wh = self.weekly_history or []
            tot = sum(s.get("quake_count", 0) for s in wh)
            mx = max([s.get("max_mag", 0) for s in wh] + [0])
            bs = [s.get("b_value", 0) for s in wh if s.get("b_value")]
            avg_b = sum(bs) / len(bs) if bs else 0
            if hasattr(self, "hist_labels"):
                self.hist_labels["total"].configure(text=f"{len(wh)} hafta")
                self.hist_labels["quakes"].configure(text=f"{tot}")
                self.hist_labels["max"].configure(text=f"M{mx:.1f}")
                self.hist_labels["b"].configure(text=f"{avg_b:.2f}")
            if hasattr(self, "hist_state"):
                st = baseline_status(wh)
                s = st["state"]
                if s == "veri-yok":
                    txt = "Karşılaştırma için yeterli hafta yok."
                elif s == "yuksek":
                    txt = (f"Bu hafta: {st['last']} deprem — olağan aralık "
                           f"({st['low']:.0f}–{st['high']:.0f}) üzerinde.")
                elif s == "dusuk":
                    txt = (f"Bu hafta: {st['last']} deprem — olağan aralık "
                           f"({st['low']:.0f}–{st['high']:.0f}) altında, sakin.")
                else:
                    txt = (f"Bu hafta: {st['last']} deprem — olağan aralıkta "
                           f"({st['low']:.0f}–{st['high']:.0f}).")
                self.hist_state.configure(text=txt)
        except Exception:
            pass
        self._fill_tree(self.weekly_frame, self.weekly_history,
                        ["Hafta", "Deprem", "Min", "Max", "Ort", "b-değer", "Risk"])
        self._fill_tree(self.monthly_frame, self.monthly_history,
                        ["Ay", "Deprem", "Min", "Max", "Ort", "b-değer", "Risk"])

    def _fill_tree(self, parent, data, headers):
        for w in parent.winfo_children():
            w.destroy()

        if not data:
            ctk.CTkLabel(parent, text="Henüz veri yok.",
                         font=ctk.CTkFont(size=11), text_color=COLOR_TEXT2).pack(pady=20)
            return

        hdr = ctk.CTkFrame(parent, fg_color=COLOR_INSET, corner_radius=4)
        hdr.pack(fill="x", pady=(0, 2))
        for i, h in enumerate(headers):
            ctk.CTkLabel(hdr, text=h, font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=COLOR_ACCENT, width=75).pack(side="left", padx=(8 if i == 0 else 1, 1))

        for s in data:
            row = ctk.CTkFrame(parent, fg_color=COLOR_INSET, corner_radius=2)
            row.pack(fill="x", pady=1)
            if "week" in s:
                vals = [f"{s['year']}-W{s['week']}", str(s['quake_count']),
                        f"{s['min_mag']:.1f}", f"{s['max_mag']:.1f}",
                        f"{s['avg_mag']:.2f}", f"{s['b_value']:.3f}", f"{s['risk_score']:.3f}"]
            else:
                vals = [f"{s['year']}-{s['month']:02d}", str(s['quake_count']),
                        f"{s['min_mag']:.1f}", f"{s['max_mag']:.1f}",
                        f"{s['avg_mag']:.2f}", f"{s['b_value']:.3f}", f"{s['risk_score']:.3f}"]
            for i, v in enumerate(vals):
                ctk.CTkLabel(row, text=v, font=ctk.CTkFont(size=9),
                             text_color=COLOR_TEXT, width=75).pack(side="left", padx=(8 if i == 0 else 1, 1))

    def _update_prediction(self):
        p = self.prediction
        if not p: return

        color_map = {
            "warning": self._warn_color(p.get('warning_level', 'green')),
            "trend": self._warn_color(p.get('warning_level', 'green')),
            "b_trend": COLOR_DANGER if p.get('b_trend', 0) < -0.1 else
                       COLOR_SUCCESS if p.get('b_trend', 0) > 0.1 else COLOR_TEXT,
        }

        values = {
            "warning": f"{self._warn_tr(p.get('warning_level', 'green'))} ({p.get('probability',0)*100:.1f}%)",
            "probability": f"%{p.get('probability',0)*100:.1f}",
            "poisson_prob": f"%{p.get('poisson_probability',0)*100:.1f}",
            "expected_count": f"{p.get('expected_quake_count',0):.2f}",
            "max_mag": f"M{p.get('max_likely_magnitude',0):.1f}",
            "trend": self._trend_tr(p.get('trend', '?')),
        }

        for key, val in values.items():
            if key in self.pred_labels:
                self.pred_labels[key].configure(text=val,
                    text_color=color_map.get(key, COLOR_TEXT))

        # Components
        comps = p.get('components', {})
        for w in self.comp_inner.winfo_children():
            w.destroy()
        for name, val in comps.items():
            cf = ctk.CTkFrame(self.comp_inner, fg_color=COLOR_INSET, corner_radius=6)
            cf.pack(fill="x", pady=2)
            cf.grid_columnconfigure(1, weight=1)
            dn = {"poisson": "Poisson", "b_trend_score": "b-Trendi",
                  "energy_score": "Enerji", "z_score": "Z-Skor",
                  "foreshock_score": "Öncü Sismisite"}.get(name, name.replace("_", " ").title())
            ctk.CTkLabel(cf, text=dn, font=ctk.CTkFont(size=9),
                         text_color=COLOR_TEXT2).grid(row=0, column=0, padx=(10, 4), pady=6, sticky="w")
            bar = ctk.CTkProgressBar(cf, height=8, corner_radius=3,
                                      fg_color=COLOR_TRACK, progress_color=COLOR_ACCENT)
            bar.grid(row=0, column=1, padx=(0, 8), pady=6, sticky="ew")
            bar.set(min(val, 1.0))
            ctk.CTkLabel(cf, text=f"%{val*100:.0f}", font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=COLOR_TEXT, width=35).grid(row=0, column=2, padx=(0, 10))

        # Artçı öngörüsü
        if hasattr(self, "omori_labels"):
            aft = (self.risk_report or {}).get("aftershock") if self.risk_report else None
            if aft:
                self.omori_labels["main"].configure(
                    text=f"M{aft['mainshock_mag']:.1f} ({aft['days_since']:.0f}g önce)")
                self.omori_labels["expected"].configure(
                    text=f"{aft['expected_count']:.2f} deprem")
                self.omori_labels["prob"].configure(
                    text=f"%{aft['probability']*100:.1f}",
                    text_color=self._warn_color(
                        "red" if aft["probability"] >= 0.5 else
                        "orange" if aft["probability"] >= 0.2 else "green"))
            else:
                for _k, _lbl in self.omori_labels.items():
                    _lbl.configure(text="— (M≥4 ana şok yok)", text_color=COLOR_TEXT2)

    def _update_sidebar(self):
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        self.sidebar_status.configure(text=f"Son güncelleme: {now_str}")
        if self.risk_report:
            s = self.risk_report["composite_risk_score"]
            self.sidebar_bar.set(min(s, 1.0))
            self.sidebar_bar.configure(progress_color=self._risk_color(s))
            self.sidebar_risk_label.configure(
                text=f"Risk: {s:.3f} ({self.risk_report['risk_level']})",
                text_color=self._risk_color(s))
        try:
            if hasattr(self, 'bg_switch') and self.bg_switch.get():
                self.sidebar_bg_label.configure(
                    text=f"{self.bg_interval} dk aralıkla | {self.daily_request_count}/{DAILY_LIMIT}",
                    text_color=COLOR_SUCCESS)
        except:
            pass

    # ================================================================
    # ACTIONS
    # ================================================================

    def do_fetch_sismik(self):
        self.act_status.configure(text="Sismik Harita API'den çekiliyor...", text_color=COLOR_WARNING)
        threading.Thread(target=self._fetch_sismik_worker, daemon=True).start()

    def _fetch_sismik_worker(self):
        try:
            c = fetch_and_store(days_back=3, min_magnitude=0.0)
            self._bump_api_use()
            count = self.daily_request_count
            self._post_ui( lambda: self.bg_count_label.configure(
                text=f"Bugün kullanılan: {count}/{DAILY_LIMIT}"))
            self._post_ui( lambda: self.act_status.configure(
                text=f"{c} yeni deprem kaydedildi.", text_color=COLOR_SUCCESS))
            self._post_ui(self.refresh_all)
        except Exception as e:
            _emsg = str(e)
            self._post_ui(lambda e=_emsg: self.act_status.configure(
                text=f"Hata: {e}", text_color=COLOR_DANGER))

    def do_fetch_koeri(self):
        self.act_status.configure(text="KOERI'den çekiliyor...", text_color=COLOR_WARNING)
        threading.Thread(target=self._fetch_koeri_worker, daemon=True).start()

    def _fetch_koeri_worker(self):
        try:
            kquakes = fetch_koeri()
            count = 0
            for kq in kquakes:
                try:
                    insert_earthquake(kq, region_tag=kq.get("region_tag", "marmara"))
                    count += 1
                except Exception:
                    pass
            self._post_ui( lambda: self.act_status.configure(
                text=f"KOERI: {count} yeni deprem kaydedildi.", text_color=COLOR_SUCCESS))
            self._post_ui(self.refresh_all)
        except Exception as e:
            _emsg = str(e)
            self._post_ui(lambda e=_emsg: self.act_status.configure(
                text=f"KOERI hatası: {e}", text_color=COLOR_DANGER))

    def do_alert(self):
        self.act_status.configure(text="Alarm kontrolü...", text_color=COLOR_WARNING)
        threading.Thread(target=self._alert_worker, daemon=True).start()

    def _alert_worker(self):
        try:
            r = get_comprehensive_risk_report(region="marmara")
            pred = EarthquakePredictor(region="marmara").predict_short_term()
            alerted = check_and_alert(r, pred)
            msg = f"Alarm {'GÖNDERİLDİ' if alerted else 'gerek yok'} (risk: {r['composite_risk_score']:.3f})"
            self._post_ui( lambda: self.act_status.configure(
                text=msg, text_color=COLOR_SUCCESS if alerted else COLOR_TEXT))
        except Exception as e:
            _emsg = str(e)
            self._post_ui(lambda e=_emsg: self.act_status.configure(
                text=f"Hata: {e}", text_color=COLOR_DANGER))

    def copy_ai_analysis(self):
        """AI analiz metnini oluştur ve panoya kopyala/ kaydet."""
        if not self.risk_report or not self.prediction:
            messagebox.showinfo("Bilgi", "Önce verileri güncelleyin.")
            return

        text = build_analysis_prompt(self.risk_report, self.prediction, self.recurrence_data)

        # Panoya kopyala
        self.clipboard_clear()
        self.clipboard_append(text)

        # Kaydet seçeneği
        resp = messagebox.askyesno(
            "AI Analiz Raporu",
            "Analiz metni panoya kopyalandı!\n\n"
            "Bir yapay zeka modeline yapıştırarak\n"
            "doğal dil yorumu alabilirsiniz.\n\n"
            "Dosyaya da kaydetmek ister misiniz?"
        )
        if resp:
            fp = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Metin Dosyası", "*.txt")],
                title="AI Analiz Raporunu Kaydet"
            )
            if fp:
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(text)
                messagebox.showinfo("Başarılı", f"Rapor kaydedildi:\n{fp}")

    def test_api(self):
        base = self.api_base.get().strip().rstrip("/") or "https://sismikharita.com"
        key = self.api_key.get().strip()
        self.api_status.configure(text="Bağlantı test ediliyor...", text_color=COLOR_WARNING)
        threading.Thread(target=self._test_api_worker, args=(base, key), daemon=True).start()

    def _test_api_worker(self, base, key):
        try:
            import requests
            from deprem_izleme.config import FETCH_TIMEOUT
            headers = {"User-Agent": "DepremAnaliz-Marmara/1.0"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            r = requests.get(base + "/api.php", params={"limit": 1},
                             headers=headers, timeout=FETCH_TIMEOUT)
            r.raise_for_status()
            n = r.json().get("count", "?")
            self._post_ui( lambda: self.api_status.configure(
                text=f"Bağlantı OK (örnek kayıt: {n})", text_color=COLOR_SUCCESS))
        except Exception as e:
            _emsg = str(e)
            self._post_ui(lambda e=_emsg: self.api_status.configure(
                text=f"Hata: {e}", text_color=COLOR_DANGER))

    def save_api(self):
        from deprem_izleme.config import save_settings, clean_api_base
        base = clean_api_base(self.api_base.get())
        save_settings({"api_base": base,
                       "api_key": self.api_key.get().strip()})
        self.api_base.delete(0, "end")
        self.api_base.insert(0, base)
        self.api_status.configure(text="Kaydedildi", text_color=COLOR_SUCCESS)

    def test_tel(self):
        self.tel_status.configure(text="Gönderiliyor...", text_color=COLOR_WARNING)
        token = self.tel_token.get()
        chat = self.tel_chat.get()
        threading.Thread(target=self._test_tel_worker, args=(token, chat), daemon=True).start()

    def _test_tel_worker(self, token, chat):
        try:
            from deprem_izleme.notifier import _load_telegram_config, send_telegram_message
            from deprem_izleme.notifier import save_telegram_config
            save_telegram_config(token, chat)
            _load_telegram_config()
            ok = send_telegram_message("Test mesajı başarılı!")
            self._post_ui(lambda: self.tel_status.configure(
                text="Gönderildi!" if ok else "Hata - token/chat ID kontrol",
                text_color=COLOR_SUCCESS if ok else COLOR_DANGER))
        except Exception as e:
            _emsg = str(e)
            self._post_ui(lambda e=_emsg: self.tel_status.configure(
                text=f"Hata: {e}", text_color=COLOR_DANGER))

    def save_tel_filters(self):
        from deprem_izleme.config import save_settings
        try:
            thr = float(self.tel_threshold.get().strip() or 0.6)
        except Exception:
            thr = 0.6
        thr = min(1.0, max(0.0, thr))
        try:
            cd = float(self.tel_cooldown.get().strip() or 6)
        except Exception:
            cd = 6
        cd = max(0.0, cd)
        levels = [k for k, cb in self.tel_lv.items() if cb.get()]
        save_settings({"telegram_enabled": bool(self.tel_enable.get()),
                       "telegram_threshold": thr,
                       "telegram_cooldown_h": cd,
                       "telegram_levels": levels})
        self.tel_threshold.delete(0, "end")
        self.tel_threshold.insert(0, str(thr))
        self.tel_filter_status.configure(text="Filtreler kaydedildi", text_color=COLOR_SUCCESS)
        self.refresh_notif_log()

    def refresh_notif_log(self):
        from deprem_izleme.notifier import get_notification_log
        for w in self.notif_scroll.winfo_children():
            w.destroy()
        logs = get_notification_log(limit=10)
        if not logs:
            ctk.CTkLabel(self.notif_scroll, text="Henüz bildirim kaydı yok.",
                         font=ctk.CTkFont(size=10), text_color=COLOR_TEXT2).pack(anchor="w", padx=8, pady=4)
            return
        for e in logs:
            ok = e.get("ok")
            dot = COLOR_SUCCESS if ok is True else (COLOR_WARNING if ok == "beklemede" else COLOR_DANGER)
            txt = f"{e.get('ts', '?')} · {e.get('type', '?')} · {e.get('reason', '')[:60]}"
            row = ctk.CTkFrame(self.notif_scroll, fg_color="transparent")
            row.pack(fill="x", padx=4, pady=1)
            ctk.CTkFrame(row, fg_color=dot, corner_radius=4, width=8, height=8).pack(side="left", padx=(4, 6))
            ctk.CTkLabel(row, text=txt, font=ctk.CTkFont(size=9),
                         text_color=COLOR_TEXT).pack(side="left")

    def save_tel(self):
        from deprem_izleme.notifier import save_telegram_config
        save_telegram_config(self.tel_token.get(), self.tel_chat.get())
        self.tel_status.configure(text="Kaydedildi", text_color=COLOR_SUCCESS)


def main():
    app = DepremGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
