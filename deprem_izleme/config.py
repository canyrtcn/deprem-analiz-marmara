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
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
_settings_cache = None

DEFAULT_SETTINGS = {
    "api_base": API_BASE,
    "api_key": "",
    "appearance": "light",
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


def save_settings(patch):
    """Ayarları diske yazar (sadece verilen anahtarlar)."""
    global _settings_cache
    s = load_settings()
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


def clean_api_base(value):
    """Kullanıcı girdisini güvenli API köküne indirger (http/https zorunlu)."""
    v = (value or "").strip().rstrip("/")
    if not v:
        return API_BASE
    if "://" not in v:
        v = "https://" + v
    if v.split("://", 1)[0].lower() not in ("http", "https"):
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
