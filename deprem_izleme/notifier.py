"""
Telegram bildirim modülü - Risk durumunda uyarı gönderimi
"""
import os
import re
import logging
import requests
from datetime import datetime

from deprem_izleme.config import TELEGRAM_ENABLED, TELEGRAM_RISK_THRESHOLD

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = None
TELEGRAM_CHAT_ID = None
NOTIF_LOG = None  # data/notifications.jsonl (gecikmeli atanır)


def _load_telegram_config():
    """Telegram bot konfigürasyonunu yükle (env öncelikli, sonra ayar dosyası)."""
    global TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    TELEGRAM_TOKEN = (os.environ.get("DEPREM_TELEGRAM_TOKEN")
                      or os.environ.get("TELEGRAM_TOKEN"))
    TELEGRAM_CHAT_ID = (os.environ.get("DEPREM_TELEGRAM_CHAT_ID")
                        or os.environ.get("TELEGRAM_CHAT_ID"))
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        try:
            from deprem_izleme.config import load_settings
            s = load_settings()
            TELEGRAM_TOKEN = TELEGRAM_TOKEN or s.get("telegram_token") or None
            TELEGRAM_CHAT_ID = TELEGRAM_CHAT_ID or s.get("telegram_chat_id") or None
        except Exception:
            pass


def save_telegram_config(token, chat_id):
    """Telegram ayarlarını kalıcı kaydet (ayar dosyası + ortam)."""
    global TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    token = (token or "").strip()
    chat_id = (chat_id or "").strip()
    if token:
        os.environ["DEPREM_TELEGRAM_TOKEN"] = token
        TELEGRAM_TOKEN = token
    if chat_id:
        os.environ["DEPREM_TELEGRAM_CHAT_ID"] = chat_id
        TELEGRAM_CHAT_ID = chat_id
    try:
        from deprem_izleme.config import save_settings
        save_settings({"telegram_token": token, "telegram_chat_id": chat_id})
    except Exception:
        pass


def _escape_md(text):
    """Telegram Markdown (legacy) özel karakterlerini kaçır.

    Dinamik alanlar (yer adı vb.) alt çizgi/yıldız içerirse
    Telegram mesajı reddeder; bu fonksiyon bunu önler.
    """
    if text is None:
        return "?"
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!])", r"\\\1", str(text))


def _notif_settings():
    try:
        from deprem_izleme.config import load_settings
        return load_settings()
    except Exception:
        return {}


def _notif_log_path():
    global NOTIF_LOG
    if NOTIF_LOG:
        return NOTIF_LOG
    try:
        from deprem_izleme.config import DATA_DIR
        NOTIF_LOG = os.path.join(DATA_DIR, "notifications.jsonl")
    except Exception:
        NOTIF_LOG = "notifications.jsonl"
    return NOTIF_LOG


def log_notification(ntype, reason, ok):
    """Bildirim girişimini kayıt defterine ekle (ok: True/False/'beklemede')."""
    import json as _json
    try:
        with open(_notif_log_path(), "a", encoding="utf-8") as f:
            f.write(_json.dumps({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "type": ntype, "reason": reason, "ok": ok,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def get_notification_log(limit=20):
    """Son bildirim kayıtları (yeniden eskiye)."""
    import json as _json
    try:
        with open(_notif_log_path(), "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        out = []
        for ln in lines[-limit:]:
            try:
                out.append(_json.loads(ln))
            except Exception:
                pass
        return list(reversed(out))
    except Exception:
        return []


def _last_alert_ts():
    """Son başarılı risk bildiriminin zamanı (epoch) ya da None."""
    from datetime import datetime as _dt
    last = None
    for e in get_notification_log(limit=200):
        if e.get("type") == "risk" and e.get("ok") is True:
            try:
                ts = _dt.fromisoformat(e["ts"]).timestamp()
                last = max(last or 0, ts)
            except Exception:
                pass
    return last


def telegram_available():
    """Telegram bildirim için bot ayarları var mı?"""
    if TELEGRAM_TOKEN is None or TELEGRAM_CHAT_ID is None:
        _load_telegram_config()
    return bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)


def send_telegram_message(message, parse_mode="Markdown"):
    """Telegram üzerinden mesaj gönder."""
    if not TELEGRAM_ENABLED:
        logger.info("Telegram bildirimleri devre disi.")
        return False

    if not telegram_available():
        logger.warning("Telegram bot ayarlanmamis (TELEGRAM_TOKEN / CHAT_ID).")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Telegram mesaji gonderildi.")
        return True
    except Exception as e:
        logger.error(f"Telegram mesaji gonderilemedi: {e}")
        return False


def _risk_emoji(level):
    norm = (level or "").replace("Ç", "C").replace("Ö", "O").replace("Ü", "U") \
        .replace("Ğ", "G").replace("Ş", "S").replace("İ", "I").upper()
    return {"COK YUKSEK": "🚨", "YUKSEK": "⚠️", "ORTA": "📊",
            "DUSUK": "✅", "COK DUSUK": "✅", "VERI YOK": "⚪"}.get(norm, "📊")


def _warning_emoji(warning):
    return {"red": "🔴", "orange": "🟠", "yellow": "🟡", "green": "🟢"}.get(warning, "⚪")


def format_risk_alert(risk_report, prediction):
    """Risk alarm mesajini formatla."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    risk_level = risk_report["risk_level"]
    re = _risk_emoji(risk_level)
    warning = prediction.get("warning_level", "green")
    we = _warning_emoji(warning)
    wtr = {"red": "KIRMIZI", "orange": "TURUNCU",
           "yellow": "SARI", "green": "YEŞİL"}.get(warning, warning.upper())

    lines = [
        f"{we} **DEPREM RISK RAPORU** {re}",
        f"📍 {_escape_md(risk_report['region'].title())} Bolgesi",
        f"🕐 {now}",
        "",
        f"**📊 Bilesik Risk Skoru:** {risk_report['composite_risk_score']:.3f} ({risk_level})",
        f"**🔮 On-Tahmin Seviyesi:** {wtr} ({prediction['probability']:.1%})",
        "",
        "**📈 Gutenberg-Richter:**",
        f" b-degeri: {risk_report['gutenberg_richter']['b_value']:.3f} (ref: 1.0)",
        f" Beklenen Mmax: M{risk_report['gutenberg_richter']['expected_max_magnitude']:.1f}",
        f" Gozlenen Mmax: M{risk_report['gutenberg_richter']['observed_max_magnitude']:.1f}",
        "",
        "**⚡ Poisson (M>=4.0):**",
        f" 7 gunluk olasilik: %{risk_report['poisson']['p_m4_7days_pct']:.1f}",
        f" 30 gunluk olasilik: %{risk_report['poisson']['p_m4_30days_pct']:.1f}",
        "",
        "**🔋 Enerji:**",
        f" Toplam: {risk_report['energy']['total_energy_joules']:.2e} J",
        f" TNT esd.: {risk_report['energy']['total_energy_tnt_tons']:.1f} ton",
        "",
        "**📉 Trend:**",
        f" b-trendi: {prediction.get('b_trend', 0):+.4f} (negatif = risk artisi)",
        f" Aktivite Z-skor: {prediction.get('anomaly_z_score', 0):.2f}",
        f" Yon: { {'increasing': 'ARTIYOR', 'stable': 'STABİL', 'decreasing': 'AZALIYOR'}.get(prediction.get('trend', 'stable'), '?') }",
        "",
        f"**🔮 {wtr} seviyesinde uyari**",
        f" {prediction['prediction_window_days']} gun icinde M>={prediction['min_magnitude_of_interest']} olasiligi: %{prediction['probability']*100:.1f}",
        f" Beklenen en buyuk: M{prediction.get('max_likely_magnitude', '?')}",
        "",
        "🤖 _Deprem Analiz - Marmara_",
    ]
    return "\n".join(lines)


def format_daily_summary(stats, quake_count_24h):
    """Gunluk ozet mesaj."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    lines = [
        f"📋 **Gunluk Deprem Ozeti** \u2014 {now}",
        f"📍 Marmara Bolgesi",
        "",
        f"**Son 24 saat:** {quake_count_24h} deprem",
        f"**Haftalik toplam:** {stats.get('quake_count', '?')} deprem",
        f"**En buyuk:** M{stats.get('max_mag', '?')}",
        f"**Ortalama:** M{stats.get('avg_mag', '?')}",
        f"**Risk skoru:** {stats.get('risk_score', '?')}",
        "",
    ]
    if stats.get("max_mag_expected"):
        lines.append(f"📈 Beklenen Mmax: M{stats['max_mag_expected']}")
    lines.append("")
    lines.append("🤖 _Deprem Analiz - Marmara_")
    return "\n".join(lines)


def check_and_alert(risk_report, prediction):
    """
    Risk kontrolü yap, koşullar sağlanırsa Telegram bildirimi gönder.

    Tetikleyiciler (ayarlanabilir):
    - Bileşik risk ≥ eşik (varsayılan 0.7, YÜKSEK bandı)
    - Uyarı seviyesi seçili düzeylerde (varsayılan kırmızı/turuncu)
    - risk ≥ 0.4 + anomali Z ≥ 2.5
    Aynı risk için bekleme süresi (varsayılan 6 sa) içinde tekrar gönderilmez.
    """
    s = _notif_settings()
    if not s.get("telegram_enabled", True):
        return False

    try:
        threshold = float(s.get("telegram_threshold", TELEGRAM_RISK_THRESHOLD)
                          or TELEGRAM_RISK_THRESHOLD)
    except Exception:
        threshold = TELEGRAM_RISK_THRESHOLD
    levels = s.get("telegram_levels", ["red", "orange"]) or []
    try:
        cooldown_h = float(s.get("telegram_cooldown_h", 6) or 0)
    except Exception:
        cooldown_h = 0

    risk_score = risk_report["composite_risk_score"]
    warning = prediction.get("warning_level", "green")

    should_alert = False
    reason = ""
    if risk_score >= threshold:
        should_alert = True
        reason = f"risk_skoru={risk_score:.3f} >= esik={threshold:.2f}"
    elif warning in levels:
        should_alert = True
        reason = f"uyari_seviyesi={warning}"
    elif risk_score >= 0.4 and prediction.get("anomaly_z_score", 0) >= 2.5:
        should_alert = True
        reason = f"anomali_z={prediction.get('anomaly_z_score', 0):.1f}"

    if not should_alert:
        logger.info(f"Risk skoru {risk_score:.3f}, esik alti. Uyari gerekmez.")
        return False

    if cooldown_h > 0:
        last = _last_alert_ts()
        if last and (datetime.now().timestamp() - last) < cooldown_h * 3600:
            logger.info(f"Uyari beklemede (cooldown): {reason}")
            log_notification("risk", reason + " (beklemede: cooldown)", "beklemede")
            return False

    msg = format_risk_alert(risk_report, prediction)
    success = send_telegram_message(msg)
    log_notification("risk", reason, success)
    if success:
        logger.info(f"TELEGRAM UYARISI GONDERILDI — {reason}")
    else:
        logger.warning(f"Telegram uyarisi gonderilemedi — {reason}")
    return success


def send_test_message():
    """Test mesaji gonder."""
    if not telegram_available():
        _load_telegram_config()
    if not telegram_available():
        logger.error("Telegram ayarlari eksik.")
        log_notification("test", "ayar eksik", False)
        return False

    msg = (
        "🧪 **Deprem Analiz - Marmara Test**\n\n"
        "Merhaba! Bu bir test mesajidir.\n"
        "Sistem calisiyor ve bildirimler aktif.\n\n"
        "🤖 _Deprem Analiz - Marmara_"
    )
    ok = send_telegram_message(msg)
    log_notification("test", "manuel test", ok)
    return ok


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    send_test_message()
