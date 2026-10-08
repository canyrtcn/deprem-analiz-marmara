"""
Konfigürasyon - Marmara Denizi & İstanbul bounding box ve parametreler
"""
import os
import json

# Bounding box: Marmara Denizi + İstanbul
# Kabaca: 40.5°K - 41.5°K, 27.0°D - 30.0°D
MARMARA_BBOX = {
    "min_lat": 40.5,
    "max_lat": 41.5,
    "min_lon": 27.0,
    "max_lon": 30.0,
}

# İstanbul özel (daha dar)
ISTANBUL_BBOX = {
    "min_lat": 40.9,
    "max_lat": 41.3,
    "min_lon": 28.5,
    "max_lon": 29.5,
}

# API
API_BASE = "https://sismikharita.com"
API_ENDPOINT = f"{API_BASE}/api.php"
API_LIMIT = 1000  # max per request
DAILY_LIMIT = 100  # free tier

# Ağ zaman aşımları (saniye) - KOERI bu ağdan yanıt vermiyor, kısa tut
FETCH_TIMEOUT = 12
KOERI_TIMEOUT = 8
NEWS_TIMEOUT = 6

# Veritabanı - hem normal Python hem PyInstaller exe için
import sys
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")


def _ensure_writable_data_dir():
    """Exe salt-okunur yere kurulduysa (örn. Program Files) veriyi
    kullanıcının AppData klasörüne taşı (yoksa uygulama açılmaz)."""
    global DATA_DIR, MAIN_DB, WEEKLY_DB, MONTHLY_DB, SETTINGS_PATH
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        probe = os.path.join(DATA_DIR, ".yazma_testi")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return
    except Exception:
        pass
    try:
        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        alt = os.path.join(local, "DepremAnalizMarmara", "data")
        os.makedirs(alt, exist_ok=True)
        DATA_DIR = alt
        MAIN_DB = os.path.join(DATA_DIR, "depremler.db")
        WEEKLY_DB = os.path.join(DATA_DIR, "haftalik.db")
        MONTHLY_DB = os.path.join(DATA_DIR, "aylik.db")
        SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
    except Exception:
        pass


_ensure_writable_data_dir()
MAIN_DB = os.path.join(DATA_DIR, "depremler.db")
WEEKLY_DB = os.path.join(DATA_DIR, "haftalik.db")
MONTHLY_DB = os.path.join(DATA_DIR, "aylik.db")

# Risk parametreleri
# Gutenberg-Richter
B_VALUE_REF = 1.0  # Referans b-değeri (Türkiye için ~0.9-1.1)
MAGNITUDE_OF_INTEREST = 4.0  # ilgilendiğimiz min büyüklük

# Poisson zaman bazlı
RISK_WINDOW_DAYS = 7  # 1 haftalık risk penceresi

# Omori-Utsu (artçı sismisite)
OMORI_C = 0.5    # gün
OMORI_P = 1.0    # tipik üs

# Moment magnitüd (enerji) - Hanks & Kanamori
# Mw = (2/3)*log10(M0) - 10.7 => M0 = 10^(1.5*(Mw+10.7))
# 1 J = 1 Nm

# Kullanıcı ayarları (API anahtarı, görünüm, telegram) - data/settings.json
# NOT: _ensure_writable_data_dir() yukarıda gerekirse DATA_DIR ile birlikte
# bunu da yönlendirmiştir; burada tekrar ezme.
try:
    SETTINGS_PATH
except NameError:
    SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
_settings_cache = None
_settings_lock = None


def _get_lock():
    """Ayar okuma/yazma kilidi (eşzamanlı kayıt kaybını önler)."""
    global _settings_lock
    if _settings_lock is None:
        try:
            import threading as _th
            _settings_lock = _th.Lock()
        except Exception:
            pass
    return _settings_lock

DEFAULT_SETTINGS = {
    "api_base": API_BASE,
    "api_key": "",
    "appearance": "light",
    "welcome_shown": False,
    "auto_update_check": True,
    "telegram_token": "",
    "telegram_chat_id": "",
    "telegram_enabled": True,
    "telegram_threshold": 0.6,
    "telegram_cooldown_h": 6,
    "telegram_levels": ["red", "orange"],
    "api_used": 0,
    "api_date": "",
}


def load_settings():
    """Kayıtlı ayarları varsayılanlarla birleştirerek döndürür."""
    global _settings_cache
    if _settings_cache is not None:
        return dict(_settings_cache)
    lock = _get_lock()
    try:
        if lock:
            lock.acquire()
        s = dict(DEFAULT_SETTINGS)
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    disk = json.load(f)
                if isinstance(disk, dict):
                    for k in s:
                        if disk.get(k) is not None:
                            s[k] = disk[k]
        except Exception:
            pass
        _settings_cache = dict(s)
        return dict(s)
    finally:
        try:
            if lock:
                lock.release()
        except Exception:
            pass


def save_settings(patch):
    """Ayarları diske yazar (sadece verilen anahtarlar)."""
    global _settings_cache
    lock = _get_lock()
    try:
        if lock:
            lock.acquire()
        # Kilidin İÇİNDE taze oku (önbellek bayat olabilir)
        s = dict(DEFAULT_SETTINGS)
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    disk = json.load(f)
                if isinstance(disk, dict):
                    for k in s:
                        if disk.get(k) is not None:
                            s[k] = disk[k]
        except Exception:
            pass
        for k, v in (patch or {}).items():
            if k in DEFAULT_SETTINGS and v is not None:
                s[k] = v
        try:
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(s, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        _settings_cache = dict(s)
        return dict(s)
    finally:
        try:
            if lock:
                lock.release()
        except Exception:
            pass


def clean_api_base(value):
    """Kullanıcı girdisini güvenli API köküne indirger (http/https zorunlu)."""
    v = (value or "").strip().rstrip("/")
    if not v:
        return API_BASE
    if "://" not in v:
        v = "https://" + v
    scheme, _, rest = v.partition("://")
    if scheme.lower() not in ("http", "https"):
        return API_BASE
    # Host gerçekten adres olmalı (şema-aldatmacası/boş host elenir)
    host = rest.split("/", 1)[0].split("?", 1)[0]
    if not host or any(ch.isspace() for ch in host) or "@" in host:
        return API_BASE
    bare = host.split(":")[0].lower()
    if bare != "localhost" and not bare.startswith("[") and "." not in bare:
        return API_BASE
    return v


def get_api_endpoint():
    return clean_api_base(load_settings().get("api_base")) + "/api.php"


def get_api_key():
    return (load_settings().get("api_key") or "").strip()


# Telegram
TELEGRAM_ENABLED = True
TELEGRAM_RISK_THRESHOLD = 0.6  # 0-1 scale, 0.6+ triggers alert

# Cron
FETCH_INTERVAL_MINUTES = 60  # her saat başı çek (günde ~24 req)

# Uygulama kimliği + güncelleme kanalı (GitHub Releases)
# NOT: Depo adı değişirse burayı güncelleyin (Ayarlar'daki GitHub
# bağlantısıyla aynı depoyu göstermelidir).
from deprem_izleme.version import __version__ as APP_VERSION
from deprem_izleme.version import APP_NAME
GITHUB_OWNER = "canyrtcn"
GITHUB_REPO = "deprem-analiz-marmara"
GITHUB_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_API_LATEST = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
# Release'e eklenen taşınabilir paket adı (build.py --release ile üretilir)
UPDATE_ASSET_NAME = "deprem-analiz-marmara-win64.zip"
