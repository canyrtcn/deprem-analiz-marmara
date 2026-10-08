"""
Deprem Analiz - Marmara - Ana Orchestrator
"""
import os
import sys
import json
import logging
import argparse
from datetime import datetime, timedelta

# Proje kökünü PATH'e ekle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _RedactedParser(argparse.ArgumentParser):
    """Hata ciktilarinda token-sablonu sizdirmayan parser.

    Kullanicinin komut satirina yazdigi taninmamis argumanlar argparse
    tarafindan yankilanir; gercek token bicimindeki degerler maskelenir.
    """

    def error(self, message):
        try:
            from deprem_izleme.errors import redact
            message = redact(message)
        except Exception:
            pass
        super().error(message)

from deprem_izleme.fetcher import fetch_and_store, fetch_recent_and_store
from deprem_izleme.aggregation import (
    compute_weekly_stats, compute_monthly_stats,
    get_comprehensive_risk_report, report_sufficient,
)
from deprem_izleme.predictor import EarthquakePredictor
from deprem_izleme.notifier import (
    check_and_alert, send_telegram_message,
    telegram_available, format_daily_summary,
    format_risk_alert, send_test_message,
)
from deprem_izleme.db import (
    get_earthquakes, get_stats, get_weekly_history, get_monthly_history, MAIN_DB
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")
_WTR = {"red": "KIRMIZI", "orange": "TURUNCU", "yellow": "SARI", "green": "YEŞİL"}
_TRT = {"increasing": "ARTIYOR", "stable": "STABİL", "decreasing": "AZALIYOR"}


def _fetch_safe(days_back, min_magnitude, sources=None):
    """Fetch sarmalayici: baglanti/redirect hatasinda dost mesaj basar,
    kayitli veriyle devam edilebilsin diye 0 doner.

    Bakim kilidi REDDI farklidir: mesaj basar ve MaintenanceActiveError
    yukseltir (cagiran cikis koduna tasir; sifir-deprem gibi gorunmez).
    """
    from deprem_izleme.fetcher import FetchRedirectError
    from deprem_izleme.config import ApiConfigError
    from deprem_izleme.db import MaintenanceActiveError
    try:
        return fetch_and_store(days_back=days_back,
                               min_magnitude=min_magnitude,
                               sources=sources)
    except MaintenanceActiveError as e:
        print(f"Bakim kilidi aktif: {e} (yazma yapilmadi, veri cekilemedi)")
        raise
    except (ApiConfigError, FetchRedirectError) as e:
        print(f"Baglanti hatasi: {e} (kayitli veri kullaniliyor)")
        return 0
    except Exception as e:
        try:
            from deprem_izleme.errors import redact
            msg = redact(str(e)).split("\n")[0][:160]
        except Exception:
            msg = "baglanti hatasi"
        print(f"Baglanti hatasi: {msg} (kayitli veri kullaniliyor)")
        return 0


def cmd_fetch(args):
    """Deprem verilerini çek ve kaydet. Doner: cikis kodu (0/1)."""
    from deprem_izleme.db import MaintenanceActiveError
    try:
        count = _fetch_safe(
            days_back=args.days or 7,
            min_magnitude=args.min_mag or 0.0,
            sources=args.sources,
        )
    except MaintenanceActiveError:
        return 1
    _bump_cli_counter()
    print(f"{count} yeni deprem kaydedildi.")
    return 0


def _bump_cli_counter(n=1):
    """CLI çekişlerini kalıcı kotaya işle (GUI sayacıyla aynı havuz)."""
    try:
        import datetime as _dt
        from deprem_izleme.config import load_settings, save_settings
        today = _dt.date.today().isoformat()
        s = load_settings()
        cur = s.get("api_used", 0) + n if s.get("api_date") == today else n
        save_settings({"api_used": cur, "api_date": today})
    except Exception:
        pass


def cmd_update(args):
    """Tüm analizleri çalıştır: fetch -> aggregate -> predict -> alert.
    Doner: cikis kodu (bakim reddinde 1, analiz iptal edilir)."""
    from deprem_izleme.db import MaintenanceActiveError
    # 1. Fetch son depremler
    logger.info("Adım 1: Deprem verileri çekiliyor...")
    try:
        count = _fetch_safe(1, min_magnitude=1.0) if args.fetch else 0
    except MaintenanceActiveError:
        return 1
    if args.fetch:
        _bump_cli_counter()

    # 2. Haftalık istatistik
    logger.info("Adım 2: Haftalık istatistikler hesaplanıyor...")
    weekly = compute_weekly_stats(region=args.region)

    # 3. Aylık istatistik
    logger.info("Adım 3: Aylık istatistikler hesaplanıyor...")
    monthly = compute_monthly_stats(region=args.region)

    # 4. Risk raporu
    logger.info("Adım 4: Kapsamlı risk raporu...")
    risk_report = get_comprehensive_risk_report(region=args.region)

    # 5. Tahmin
    logger.info("Adım 5: Kısa vadeli tahmin...")
    predictor = EarthquakePredictor(region=args.region)
    prediction = predictor.predict_short_term(days_ahead=7, min_mag_of_interest=4.0)

    # 6. Alert kontrolü
    logger.info("Adım 6: Alarm kontrolü...")
    alerted = check_and_alert(risk_report, prediction)

    # Özet
    quake_count_24h = get_stats(region=args.region)["son_24h"]
    print(f"\n{'='*50}")
    print(f"  {args.region.title()} - Deprem Durum Raporu")
    print(f"  {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"{'='*50}")
    _m_suf = report_sufficient(risk_report)
    _m_score_txt = (f"{risk_report['composite_risk_score']:.4f} ({risk_report['risk_level']})"
                    if _m_suf else "- (yetersiz veri)")
    print(f"  Risk Skoru: {_m_score_txt}")
    _m_pp = prediction.get('poisson_probability')
    print(f"  Tahmin: {_WTR.get(prediction.get('warning_level'), '?')} (Poisson: " + (f"%{_m_pp*100:.1f}" if _m_pp is not None else "-") + ")")
    print(f"  b-degeri: {risk_report['gutenberg_richter']['b_value']:.4f}")
    _m_p7 = risk_report['poisson']['p_m4_7days_pct']
    print(f"  M>=4.0 7g olasilik: " + (f"%{_m_p7:.1f}" if _m_p7 is not None else "- (yetersiz veri)"))
    print(f"  Trend: {_TRT.get(prediction['trend'], '?')}")
    print(f"  Son 24h: {quake_count_24h} deprem")
    _albl = {"sent": "GONDERILDI", "send_failed": "GONDERILEMEDI (hata)",
             "cooldown": "beklemede (cooldown)", "disabled": "kapali",
             "not_needed": "Gerek yok"}.get(
                 getattr(check_and_alert, "last_status", "not_needed"), "?")
    print(f"  Alarm: {_albl}")
    print(f"{'='*50}\n")

    return 0


def cmd_report(args):
    """Risk raporu goster (JSON)."""
    risk_report = get_comprehensive_risk_report(region=args.region)
    predictor = EarthquakePredictor(region=args.region)
    prediction = predictor.predict_short_term(
        days_ahead=args.days or 7,
        min_mag_of_interest=args.min_mag or 4.0,
    )

    output = {
        "timestamp": datetime.now().isoformat(),
        "region": args.region,
        "risk_report": risk_report,
        "prediction": prediction,
    }

    if args.format == "json":
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        # Terminal dostu cikti - emoji kullanma
        print()
        print("=" * 60)
        print(f"   {risk_report['region'].title()} - Kapsamli Deprem Risk Raporu")
        print(f"   {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        print("=" * 60)
        print(f"\n  BIRLESIK RISK: " + (f"{risk_report['composite_risk_score']:.4f} ({risk_report['risk_level']})"
              if report_sufficient(risk_report) else "- (yetersiz veri)"))
        _r_pp = prediction.get('poisson_probability')
        _r_ci = prediction.get('composite_index')
        print(f"  TAHMIN: {_WTR.get(prediction.get('warning_level'), '?')} (Poisson: " + (f"%{_r_pp*100:.1f}" if _r_pp is not None else "-") + ")")
        if _r_ci is not None:
            print(f"  Aktivite Gostergesi: {_r_ci*100:.0f}/100 (boyutsuz, kalibre edilmemis)")
        else:
            print("  Aktivite Gostergesi: - (yetersiz veri)")
        print(f"\n  Gutenberg-Richter:")
        print(f"     b-degeri: {risk_report['gutenberg_richter']['b_value']:.4f}")
        print(f"     a-degeri: {risk_report['gutenberg_richter']['a_value']:.4f}")
        _r_em = risk_report['gutenberg_richter']['expected_max_magnitude']
        print(f"     Beklenen Mmax: " + (f"M{_r_em:.1f}" if _r_em is not None else "- (yetersiz veri)"))
        print(f"     Gozlenen Mmax: M{risk_report['gutenberg_richter']['observed_max_magnitude']:.1f}")
        print(f"\n  Poisson Olasiliklar (kalibre edilmemis):")
        print(f"     l(M>=3.0): {risk_report['poisson']['lambda_m3_per_day']:.4f} /gun")
        print(f"     l(M>=4.0): {risk_report['poisson']['lambda_m4_per_day']:.4f} /gun")
        _r_p7 = risk_report['poisson']['p_m4_7days_pct']
        _r_p30 = risk_report['poisson']['p_m4_30days_pct']
        print(f"     7 gunde M>=4.0: " + (f"%{_r_p7:.1f}" if _r_p7 is not None else "- (yetersiz veri)"))
        print(f"     30 gunde M>=4.0: " + (f"%{_r_p30:.1f}" if _r_p30 is not None else "- (yetersiz veri)"))
        print(f"\n  Enerji:")
        print(f"     Toplam: {risk_report['energy']['total_energy_joules']:.2e} J")
        print(f"     TNT: {risk_report['energy']['total_energy_tnt_tons']:.1f} ton")
        print(f"\n  Trend Analizi:")
        print(f"     b-trendi: {prediction.get('b_trend', 0):+.4f}")
        print(f"     Aktivite Z-skor: {prediction.get('anomaly_z_score', 0):.2f}")
        print(f"     Trend yonu: {_TRT.get(prediction.get('trend', 'stable'), '?')}")
        print(f"\n  {prediction['prediction_window_days']} gunluk tahmin (bilesik gosterge):")
        _r_mp = prediction.get('poisson_probability')
        print(f"     M>={prediction['min_magnitude_of_interest']} olasiligi (Poisson): " + (f"%{_r_mp*100:.1f}" if _r_mp is not None else "- (yetersiz veri)"))
        _r_mm = prediction.get('max_likely_magnitude')
        print(f"     Beklenen maksimum: " + (f"M{_r_mm}" if _r_mm is not None else "- (yetersiz veri)"))
        _r_ec = prediction.get('expected_quake_count')
        print(f"     Tahmin edilen deprem sayisi: " + (f"{_r_ec:.1f}" if _r_ec is not None else "- (yetersiz veri)"))
        print(f"\n  Sismisite:")
        print(f"     Toplam deprem (30g): {risk_report['quake_count']}")
        counts = get_stats(region=args.region)
        print(f"     Son 24 saat: {counts.get('son_24h', 0)}")
        print(f"     Son 7 gun: {counts.get('son_7g', 0)}")
        print("=" * 60)
        print()

    return output


def cmd_backfill(args):
    """Geçmiş haftalık/aylık tablolarını geriye dönük doldur."""
    from deprem_izleme.aggregation import backfill_history
    w, m = backfill_history(weeks=args.weeks, months=args.months, region=args.region)
    print(f"{w} hafta, {m} ay yazıldı ({args.region}).")


def cmd_history(args):
    """Geçmiş istatistikleri göster."""
    if args.period == "weekly":
        stats_list = get_weekly_history(limit=args.limit, region=args.region)
        print(f"\n  Haftalik Deprem Istatistikleri - {args.region}")
        print(f"{'-'*80}")
        print(f"{'Hafta':<12} {'Deprem':>7} {'Min':>6} {'Max':>6} {'Ort':>6} {'Enerji(J)':>14} {'b-deger':>8} {'Risk':>6}")
        print(f"{'-'*80}")
        for s in stats_list:
            print(f"{s['year']}-W{s['week']:<4} {s['quake_count']:>7} {s['min_mag']:>5.1f} {s['max_mag']:>5.1f} {s['avg_mag']:>5.2f} {s['total_energy_j']:>13.2e} {s['b_value']:>7.3f} {s['risk_score']:>5.3f}")
    else:
        stats_list = get_monthly_history(limit=args.limit, region=args.region)
        print(f"\n  Aylik Deprem Istatistikleri - {args.region}")
        print(f"{'-'*80}")
        print(f"{'Ay':<10} {'Deprem':>7} {'Min':>6} {'Max':>6} {'Ort':>6} {'Enerji(J)':>14} {'b-deger':>8} {'Risk':>6}")
        print(f"{'-'*80}")
        for s in stats_list:
            print(f"{s['year']}-{s['month']:02d}{'':<4} {s['quake_count']:>7} {s['min_mag']:>5.1f} {s['max_mag']:>5.1f} {s['avg_mag']:>5.2f} {s['total_energy_j']:>13.2e} {s['b_value']:>7.3f} {s['risk_score']:>5.3f}")


def cmd_alert(args):
    """Manuel uyarı gönder / test et."""
    if args.test:
        ok = send_test_message()
        print(f"{'OK' if ok else 'FAIL'} Test mesaji {'gonderildi' if ok else 'gonderilemedi'}.")
        return

    risk_report = get_comprehensive_risk_report(region=args.region)
    predictor = EarthquakePredictor(region=args.region)
    prediction = predictor.predict_short_term()

    alerted = check_and_alert(risk_report, prediction)
    if not alerted:
        try:
            from deprem_izleme.config import load_settings as _ls
            _thr = float(_ls().get("telegram_threshold", 0.7) or 0.7)
        except Exception:
            _thr = 0.7
        if report_sufficient(risk_report):
            print(f"! Risk skoru esik alti ({risk_report['composite_risk_score']:.3f} < {_thr:.2f}).")
        else:
            print("! Veri yetersiz - risk esik karsilastirmasi yapilmadi.")
        msg = format_risk_alert(risk_report, prediction)
        print("\n--- Mesaj önizleme ---")
        print(msg)
        ok = input("\nYine de göndermek istiyor musun? (e/h): ").strip().lower() == "e"
        if ok:
            sent = bool(send_telegram_message(msg))
            print("Gönderildi." if sent else "GÖNDERİLEMEDİ (Telegram hatası, loga bakın).")
            return 0 if sent else 2
        else:
            print("İptal.")


def cmd_telegram_setup(args):
    """Telegram bot token'ı yapılandır (token yalnizca env/getpass ile)."""
    import getpass
    token = (os.environ.get("DEPREM_TELEGRAM_TOKEN")
             or getpass.getpass("Telegram Bot Token (gizli giris): ").strip())
    chat_id = (getattr(args, "chat_id", None)
               or os.environ.get("DEPREM_TELEGRAM_CHAT_ID")
               or input("Telegram Chat ID: ").strip())

    if not token or not chat_id:
        print("Token veya Chat ID gerekli.")
        return

    os.environ["DEPREM_TELEGRAM_TOKEN"] = token
    os.environ["DEPREM_TELEGRAM_CHAT_ID"] = chat_id

    # Kalıcı kaydet (yoksa yeniden başlatınca unutulur)
    try:
        from deprem_izleme.notifier import save_telegram_config
        save_telegram_config(token, chat_id)
    except Exception:
        pass

    # Test
    _setup_ok = bool(send_telegram_message("🧪 <b>Deprem Analiz - Marmara</b>\n\nTelegram bildirimleri aktif!\nAyarlar basariyla tamamlandi."))
    print("Telegram ayarlari yapildi ve test mesaji gonderildi." if _setup_ok
          else "Telegram ayarlari kaydedildi ANCAK test mesaji gonderilemedi (token/chat ID ya da ag hatasi).")


def main():
    parser = _RedactedParser(
        description="Deprem Analiz - Marmara",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnek kullanım:
  python main.py fetch                   # Son 7 gün verisini çek
  python main.py fetch --days 1          # Son 24 saat
  python main.py update                  # Tam güncelleme + analiz + alarm
  python main.py report                  # Risk raporu göster
  python main.py report --format json    # JSON çıktı
  python main.py history weekly          # Haftalık geçmiş
  python main.py history monthly         # Aylık geçmiş
  python main.py alert --test            # Telegram test mesajı
  python main.py alert                   # Manuel risk bildirimi
  python main.py telegram-setup          # Telegram kurulum

Telegram kurulumda token ASLA komut satirina yazilmaz:
  set DEPREM_TELEGRAM_TOKEN=...          # Windows (oturumluk)
  python main.py telegram-setup          # token gizli sorulur (getpass)
        """
    )
    subparsers = parser.add_subparsers(dest="command")

    # fetch
    p_fetch = subparsers.add_parser("fetch", help="Deprem verilerini API'den çek")
    p_fetch.add_argument("--days", type=int, default=7, help="Kaç gün geri")
    p_fetch.add_argument("--min-mag", type=float, default=0.0, help="Minimum magnitüd")
    p_fetch.add_argument("--sources", default="kandilli,afad", help="Kaynak(lar)")

    # update
    p_update = subparsers.add_parser("update", help="Tam güncelleme: fetch+aggregate+predict+alert")
    p_update.add_argument("--region", default="marmara", help="Bölge (marmara/istanbul)")
    p_update.add_argument("--no-fetch", dest="fetch", action="store_false", help="Fetch yapma")

    # report
    p_report = subparsers.add_parser("report", help="Risk raporu göster")
    p_report.add_argument("--region", default="marmara")
    p_report.add_argument("--format", choices=["text", "json"], default="text")
    p_report.add_argument("--days", type=int, default=7, help="Tahmin penceresi (gün)")
    p_report.add_argument("--min-mag", type=float, default=4.0, help="İlgilenilen minimum magnitüd")

    # history
    p_hist = subparsers.add_parser("history", help="Geçmiş istatistikler")
    p_hist.add_argument("period", choices=["weekly", "monthly"], help="Dönem")
    p_hist.add_argument("--region", default="marmara")
    p_hist.add_argument("--limit", type=int, default=24, help="Kayıt sayısı")

    # backfill
    p_bf = subparsers.add_parser("backfill", help="Geçmiş tabloları doldur")
    p_bf.add_argument("--region", default="marmara")
    p_bf.add_argument("--weeks", type=int, default=26)
    p_bf.add_argument("--months", type=int, default=12)

    # alert
    p_alert = subparsers.add_parser("alert", help="Alarm/uyarı")
    p_alert.add_argument("--region", default="marmara")
    p_alert.add_argument("--test", action="store_true", help="Test mesajı")

    # telegram-setup (token icin --token YOKTUR: guvenlik karariyla kaldirildi;
    # yontem: DEPREM_TELEGRAM_TOKEN ortam degiskeni veya gizli giris)
    p_tsetup = subparsers.add_parser("telegram-setup", help="Telegram bot kurulum",
        description="Token komut satirina yazilmaz. DEPREM_TELEGRAM_TOKEN "
                    "ortam degiskeni yoksa gizli sorulur.")
    p_tsetup.add_argument("--chat-id", help="Chat ID")

    args = parser.parse_args()

    try:
        from deprem_izleme.db_state import ensure_setup
        ensure_setup()
    except Exception:
        pass
    try:
        from deprem_izleme.db import check_db_compat
        _ok, _msg = check_db_compat()
        if not _ok:
            print(_msg)
            return 1
    except Exception:
        pass

    if args.command == "fetch":
        return cmd_fetch(args)
    elif args.command == "update":
        return cmd_update(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "history":
        cmd_history(args)
    elif args.command == "backfill":
        cmd_backfill(args)
    elif args.command == "alert":
        cmd_alert(args)
    elif args.command == "telegram-setup":
        cmd_telegram_setup(args)
    else:
        # Hiç argüman verilmedi (çift tıklandı) - rapor göster, bekle
        parser.print_help()
        print()
        print("=" * 50)
        print("  DEPREM ANALİZ - MARMARA")
        print("  Son durum raporu hazirlaniyor...")
        print("=" * 50)
        try:
            cmd_report(argparse.Namespace(region="marmara", format="text", days=7, min_mag=4.0))
        except Exception:
            pass
        print()
        input("Kapatmak icin Enter'a basin...")


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main() or 0)
