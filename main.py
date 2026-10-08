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

from deprem_izleme.fetcher import fetch_and_store, fetch_recent_and_store
from deprem_izleme.aggregation import (
    compute_weekly_stats, compute_monthly_stats,
    get_comprehensive_risk_report,
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


def cmd_fetch(args):
    """Deprem verilerini çek ve kaydet."""
    count = fetch_and_store(
        days_back=args.days or 7,
        min_magnitude=args.min_mag or 0.0,
        sources=args.sources,
    )
    print(f"{count} yeni deprem kaydedildi.")
    return count


def cmd_update(args):
    """Tüm analizleri çalıştır: fetch -> aggregate -> predict -> alert."""
    # 1. Fetch son depremler
    logger.info("Adım 1: Deprem verileri çekiliyor...")
    count = fetch_recent_and_store(min_magnitude=1.0) if args.fetch else 0

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
    print(f"  Risk Skoru: {risk_report['composite_risk_score']:.4f} ({risk_report['risk_level']})")
    print(f"  Tahmin: {_WTR.get(prediction['warning_level'], '?')} ({prediction['probability']:.1%})")
    print(f"  b-degeri: {risk_report['gutenberg_richter']['b_value']:.4f}")
    print(f"  M>=4.0 7g olasilik: %{risk_report['poisson']['p_m4_7days_pct']:.1f}")
    print(f"  Trend: {_TRT.get(prediction['trend'], '?')}")
    print(f"  Son 24h: {quake_count_24h} deprem")
    print(f"  Alarm: {'GONDERILDI' if alerted else 'Gerek yok'}")
    print(f"{'='*50}\n")

    return {
        "new_quakes": count,
        "weekly": weekly,
        "monthly": monthly,
        "risk_report": risk_report,
        "prediction": prediction,
        "alerted": alerted,
    }


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
        print(f"\n  BIRLESIK RISK: {risk_report['composite_risk_score']:.4f} ({risk_report['risk_level']})")
        print(f"  TAHMIN: {_WTR.get(prediction['warning_level'], '?')} ({prediction['probability']:.1%} olasilik)")
        print(f"\n  Gutenberg-Richter:")
        print(f"     b-degeri: {risk_report['gutenberg_richter']['b_value']:.4f}")
        print(f"     a-degeri: {risk_report['gutenberg_richter']['a_value']:.4f}")
        print(f"     Beklenen Mmax: M{risk_report['gutenberg_richter']['expected_max_magnitude']:.1f}")
        print(f"     Gozlenen Mmax: M{risk_report['gutenberg_richter']['observed_max_magnitude']:.1f}")
        print(f"\n  Poisson Olasiliklar:")
        print(f"     l(M>=3.0): {risk_report['poisson']['lambda_m3_per_day']:.4f} /gun")
        print(f"     l(M>=4.0): {risk_report['poisson']['lambda_m4_per_day']:.4f} /gun")
        print(f"     7 gunde M>=4.0: %{risk_report['poisson']['p_m4_7days_pct']:.1f}")
        print(f"     30 gunde M>=4.0: %{risk_report['poisson']['p_m4_30days_pct']:.1f}")
        print(f"\n  Enerji:")
        print(f"     Toplam: {risk_report['energy']['total_energy_joules']:.2e} J")
        print(f"     TNT: {risk_report['energy']['total_energy_tnt_tons']:.1f} ton")
        print(f"\n  Trend Analizi:")
        print(f"     b-trendi: {prediction.get('b_trend', 0):+.4f}")
        print(f"     Aktivite Z-skor: {prediction.get('anomaly_z_score', 0):.2f}")
        print(f"     Trend yonu: {_TRT.get(prediction.get('trend', 'stable'), '?')}")
        print(f"\n  {prediction['prediction_window_days']} gunluk tahmin:")
        print(f"     M>={prediction['min_magnitude_of_interest']} olasiligi: %{prediction['probability']*100:.1f}")
        print(f"     Beklenen maksimum: M{prediction.get('max_likely_magnitude', '?')}")
        print(f"     Tahmin edilen deprem sayisi: {prediction.get('expected_quake_count', 0):.1f}")
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
        print(f"! Risk skoru esik alti ({risk_report['composite_risk_score']:.3f} < {risk_report.get('threshold', 0.6)}).")
        msg = format_risk_alert(risk_report, prediction)
        print("\n--- Mesaj önizleme ---")
        print(msg)
        ok = input("\nYine de göndermek istiyor musun? (e/h): ").strip().lower() == "e"
        if ok:
            send_telegram_message(msg)
            print("Gönderildi.")
        else:
            print("İptal.")


def cmd_telegram_setup(args):
    """Telegram bot token'ı yapılandır."""
    token = args.token or os.environ.get("DEPREM_TELEGRAM_TOKEN") or input("Telegram Bot Token: ").strip()
    chat_id = args.chat_id or os.environ.get("DEPREM_TELEGRAM_CHAT_ID") or input("Telegram Chat ID: ").strip()

    if not token or not chat_id:
        print("Token veya Chat ID gerekli.")
        return

    os.environ["DEPREM_TELEGRAM_TOKEN"] = token
    os.environ["DEPREM_TELEGRAM_CHAT_ID"] = chat_id

    # Test
    send_telegram_message("🧪 **Deprem Analiz - Marmara**\n\nTelegram bildirimleri aktif!\nAyarlar basariyla tamamlandi.")
    print("Telegram ayarlari yapildi ve test mesaji gonderildi.")


def main():
    parser = argparse.ArgumentParser(
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

    # telegram-setup
    p_tsetup = subparsers.add_parser("telegram-setup", help="Telegram bot kurulum")
    p_tsetup.add_argument("--token", help="Bot token")
    p_tsetup.add_argument("--chat-id", help="Chat ID")

    args = parser.parse_args()

    if args.command == "fetch":
        cmd_fetch(args)
    elif args.command == "update":
        cmd_update(args)
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
        print("  DEPREM IZLEME SISTEMI")
        print("  Son durum raporu hazirlaniyor...")
        print("=" * 50)
        try:
            cmd_report(argparse.Namespace(region="marmara", format="text", days=7, min_mag=4.0))
        except Exception:
            pass
        print()
        input("Kapatmak icin Enter'a basin...")


if __name__ == "__main__":
    main()
