"""
Telegram bildirim modülü - Risk durumunda uyarı gönderimi
"""
import os
import re
import logging
import requests
from datetime import datetime

from deprem_izleme.config import TELEGRAM_ENABLED, TELEGRAM_RISK_THRESHOLD
from deprem_izleme.aggregation import report_sufficient

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
    """Telegram HTML özel karakterlerini kaçır (tek standart: HTML).

    Dinamik alanlar (yer adı vb.) <>& içerirse Telegram mesajı
    reddeder; bu fonksiyon bunu önler. Tum sablonlar <b>/<i> kullanir.
    """
    import html as _html
    if text is None:
        return "?"
    return _html.escape(str(text), quote=False)


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


def send_telegram_message(message, parse_mode="HTML"):
    """Telegram üzerinden mesaj gönder (tek standart: HTML)."""
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
        resp = requests.post(url, json=payload, timeout=10,
                             allow_redirects=False)
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            logger.error("Telegram yonlendirmesi izlenmedi (token korunumu).")
            return False
        resp.raise_for_status()
        logger.info("Telegram mesaji gonderildi.")
        return True
    except requests.HTTPError as e:
        code = None
        try:
            code = e.response.status_code if e.response is not None else None
        except Exception:
            code = None
        hint = {
            400: "istek bicimi/chat ID hatali",
            401: "bot token gecersiz",
            429: "hiz siniri (biraz bekleyin)",
            500: "Telegram sunucu hatasi",
        }.get(code, "API hatasi")
        logger.error(f"Telegram API hatasi (HTTP {code}): {hint}.")
        return False
    except requests.Timeout:
        logger.error("Telegram baglanti zaman asimi (ag/tip: Timeout).")
        return False
    except requests.ConnectionError:
        logger.error("Telegram baglantisi kurulamadi (ag/tip: ConnectionError).")
        return False
    except Exception as e:
        from deprem_izleme.errors import redact
        logger.error(f"Telegram mesaji gonderilemedi: {redact(e)}")
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
    _nsuf0 = report_sufficient(risk_report)
    risk_level = (risk_report["risk_level"] if _nsuf0
                  else "— (yetersiz veri)")
    re = _risk_emoji(risk_report["risk_level"]) if _nsuf0 else "⚪"
    warning = prediction.get("warning_level")
    we = _warning_emoji(warning)
    wtr = {"red": "KIRMIZI", "orange": "TURUNCU",
           "yellow": "SARI", "green": "YEŞİL"}.get(warning, "—")
    _pp = prediction.get("poisson_probability")
    _pp_txt = f"%{_pp*100:.1f}" if _pp is not None else "— (yetersiz veri)"
    _ci = prediction.get("composite_index")
    _ci_txt = (f"{_ci*100:.0f}/100 (boyutsuz)" if _ci is not None
               else "— (yetersiz veri)")
    _rp7 = risk_report['poisson']['p_m4_7days_pct']
    _rp30 = risk_report['poisson']['p_m4_30days_pct']
    _rp7_txt = f"%{_rp7:.1f}" if _rp7 is not None else "— (yetersiz veri)"
    _rp30_txt = f"%{_rp30:.1f}" if _rp30 is not None else "— (yetersiz veri)"
    _rmmax = risk_report['gutenberg_richter']['expected_max_magnitude']
    _rmmax_txt = f"M{_rmmax:.1f}" if _rmmax is not None else "— (yetersiz veri)"
    _pmmax = prediction.get('max_likely_magnitude')
    _pmmax_txt = f"M{_pmmax}" if _pmmax is not None else "— (yetersiz veri)"
    _nscore_txt = (f"{risk_report['composite_risk_score']:.3f} ({risk_level})"
                   if _nsuf0 else "— (yetersiz veri)")

    lines = [
        f"{we} <b>DEPREM RISK RAPORU</b> {re}",
        f"📍 {_escape_md(risk_report['region'].title())} Bolgesi",
        f"🕐 {now}",
        "",
        f"<b>📊 Bilesik Risk Skoru:</b> {_nscore_txt}",
        f"<b>🔮 On-Tahmin Seviyesi:</b> {wtr} (Aktivite: {_ci_txt})",
        "",
        "<b>📈 Gutenberg-Richter:</b>",
        f" b-degeri: {risk_report['gutenberg_richter']['b_value']:.3f} (ref: 1.0)",
        f" Beklenen Mmax: {_rmmax_txt}",
        f" Gozlenen Mmax: M{risk_report['gutenberg_richter']['observed_max_magnitude']:.1f}",
        "",
        "<b>⚡ Poisson (M&gt;=4.0, kalibre edilmemis):</b>",
        f" 7 gunluk olasilik: {_rp7_txt}",
        f" 30 gunluk olasilik: {_rp30_txt}",
        "",
        "<b>🔋 Enerji:</b>",
        f" Toplam: {risk_report['energy']['total_energy_joules']:.2e} J",
        f" TNT esd.: {risk_report['energy']['total_energy_tnt_tons']:.1f} ton",
        "",
        "<b>📉 Trend:</b>",
        f" b-trendi: {prediction.get('b_trend', 0):+.4f} (negatif = risk artisi)",
        f" Aktivite Z-skor: {prediction.get('anomaly_z_score', 0):.2f}",
        f" Yon: { {'increasing': 'ARTIYOR', 'stable': 'STABİL', 'decreasing': 'AZALIYOR'}.get(prediction.get('trend', 'stable'), '?') }",
        "",
        f"<b>🔮 {wtr} seviyesinde uyari</b>",
        f" {prediction['prediction_window_days']} gun icinde M&gt;={prediction['min_magnitude_of_interest']} olasiligi (Poisson): {_pp_txt}",
        f" Beklenen en buyuk: {_pmmax_txt}",
        "",
        "🤖 <i>Deprem Analiz - Marmara</i>",
    ]
    return "\n".join(lines)


def format_daily_summary(stats, quake_count_24h):
    """Gunluk ozet mesaj."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    lines = [
        f"📋 <b>Gunluk Deprem Ozeti</b> — {now}",
        f"📍 Marmara Bolgesi",
        "",
        f"<b>Son 24 saat:</b> {quake_count_24h} deprem",
        f"<b>Haftalik toplam:</b> {stats.get('quake_count', '?')} deprem",
        f"<b>En buyuk:</b> M{stats.get('max_mag', '?')}",
        f"<b>Ortalama:</b> M{stats.get('avg_mag', '?')}",
        f"<b>Risk skoru:</b> {stats.get('risk_score', '?')}",
        "",
    ]
    if stats.get("max_mag_expected"):
        lines.append(f"📈 Beklenen Mmax: M{stats['max_mag_expected']}")
    lines.append("")
    lines.append("🤖 <i>Deprem Analiz - Marmara</i>")
    return "\n".join(lines)


def check_and_alert(risk_report, prediction):
    """
    Risk kontrolü yap, koşullar sağlanırsa Telegram bildirimi gönder.

    Tetikleyiciler (ayarlanabilir):
    - Bileşik risk ≥ eşik (varsayılan 0.7, YÜKSEK bandı)
    - Uyarı seviyesi seçili düzeylerde (varsayılan kırmızı/turuncu)
    - risk ≥ 0.4 + anomali Z ≥ 2.5
    Aynı risk için bekleme süresi (varsayılan 6 sa) içinde tekrar gönderilmez.

    Doner: True (gonderildi) / False (gonderilmedi).
    Yan etki: check_and_alert.last_status — "sent" | "not_needed" |
    "cooldown" | "send_failed" | "disabled". Cagiran "gerek yok" ile
    "gonderilemedi"yi bu alanla ayirt eder.
    """
    check_and_alert.last_status = "not_needed"
    s = _notif_settings()
    if not s.get("telegram_enabled", True):
        check_and_alert.last_status = "disabled"
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
    warning = prediction.get("warning_level") or "green"

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
        check_and_alert.last_status = "not_needed"
        return False

    if cooldown_h > 0:
        last = _last_alert_ts()
        if last and (datetime.now().timestamp() - last) < cooldown_h * 3600:
            logger.info(f"Uyari beklemede (cooldown): {reason}")
            log_notification("risk", reason + " (beklemede: cooldown)", "beklemede")
            check_and_alert.last_status = "cooldown"
            return False

    msg = format_risk_alert(risk_report, prediction)
    success = send_telegram_message(msg)
    log_notification("risk", reason, success)
    if success:
        logger.info(f"TELEGRAM UYARISI GONDERILDI — {reason}")
        check_and_alert.last_status = "sent"
    else:
        logger.warning(f"Telegram uyarisi gonderilemedi — {reason}")
        check_and_alert.last_status = "send_failed"
    return success


check_and_alert.last_status = "not_needed"


def send_test_message():
    """Test mesaji gonder."""
    if not telegram_available():
        _load_telegram_config()
    if not telegram_available():
        logger.error("Telegram ayarlari eksik.")
        log_notification("test", "ayar eksik", False)
        return False

    msg = (
        "🧪 <b>Deprem Analiz - Marmara Test</b>\n\n"
        "Merhaba! Bu bir test mesajidir.\n"
        "Sistem calisiyor ve bildirimler aktif.\n\n"
        "🤖 <i>Deprem Analiz - Marmara</i>"
    )
    ok = send_telegram_message(msg)
    log_notification("test", "manuel test", ok)
    return ok


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    send_test_message()
