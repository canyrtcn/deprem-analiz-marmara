# Deprem Analiz - Marmara

Marmara Denizi ve İstanbul çevresindeki depremleri izleyen, bilimsel
yöntemlerle risk analizi yapan açık kaynaklı masaüstü uygulaması
(Python + CustomTkinter). İnternetsiz çalışan gömülü harita, çok kaynaklı
veri katmanları ve otomatik güncelleme desteği içerir.

> **Yasal uyarı:** Bu uygulama bir erken uyarı sistemi değildir.
> Sayılar istatistiksel eğilim göstergesidir; resmi deprem bilgileri için
> AFAD (afad.gov.tr) ve Kandilli Rasathanesi'ni (koeri.boun.edu.tr)
> takip edin.

## Özellikler

- **Canlı veri:** Sismik Harita API (anahtar gerekmez, 100 istek/gün) +
  KOERI Kandilli son-deprem listesi. Veriler yerelde SQLite'da tutulur.
- **Gerçek harita:** Natural Earth 10m kıyı çizgileri üzerinde MTA diri
  fay haritası sayısallaştırması (6 segment gerçek iz, 3 segment şematik
  — lejantta belirtilir). Tekerlek-zoom, sürükle-kaydır, tıklayınca
  deprem/fay detayı + en yakın fay hesabı. Uygulama/Sismik/KOERI
  katmanları ve zaman filtresi (24s–30g).
- **Bilimsel analiz:** Gutenberg-Richter b-değeri (Aki 1965 MLE + Utsu
  1966 düzeltmesi, MAXC tamlık +0.2), artçı-ayıklanmış zemin hızdan
  Poisson olasılıkları (Gardner-Knopoff 1974), Türkiye kalibrasyonlu
  artçı öngörüsü (Müderrisoğlu & Yazgan 2020), Coulomb stres transferi,
  fay segment riskleri, b-değeri trendi (BVAL yaklaşımı).
- **Dürüstlük ilkesi:** Kalibre edilmemiş skorlar "olasılık" diye
  sunulmaz; kalibre olasılık yalnızca Poisson bileşenidir (bkz.
  Metodoloji sayfası ve Jordan vd. 2011 ICEF notu). Kısa katalogdan
  büyük-magnitüd dışdeğerlemeleri mertebe tahmini olarak işaretlenir.
- **Grafikler:** günlük maksimum + risk skoru, günlük sayı, b-trendi,
  enerji, FMD + GR uyumu, saatlik/derinlik dağılımları, büyüklük-zaman
  serisi, tam ekran görünüm.
- **Bildirimler:** eşik/seviye/cooldown filtreli Telegram uyarıları,
  bildirim geçmişi.
- **Konfor:** koyu + açık tema, ilk açılışta API kurulum rehberi,
  açılışta + manuel güncelleme denetimi (GitHub Releases).

## Kurulum

### Hazır uygulama (Windows)

1. GitHub Releases sayfasından `deprem-analiz-marmara-win64.zip`
   dosyasını indirin.
2. Zip'i bir klasöre çıkarın, içindeki `deprem-analiz-marmara.exe`
   dosyasını çalıştırın. Kurulum gerekmez (taşınabilir).
3. İlk açılışta karşılama penceresi API kurulumunu anlatır.
   API anahtarı zorunlu değildir.

### Kaynaktan çalıştırma

```bash
pip install -r requirements.txt
python run_gui.py
```

Komut satırı (rapor, geçmiş, alarm, backfill):

```bash
python main.py update
python main.py report
python main.py history weekly
python main.py backfill
```

## API kurulumu

1. Uygulamada sol menüden **Ayarlar** sayfasını açın.
2. **Sismik Harita API** bölümüne API adresini (varsayılan
   `https://sismikharita.com`) ve varsa anahtarınızı yazın.
3. **Kaydet** → **Bağlantıyı Test Et** düğmesine basın.
4. Anahtarsız kullanımda günlük 100 istek limiti vardır; anahtar
   `data/settings.json` dosyasında yerelde saklanır, depoya girmez.

## Derleme ve sürüm çıkarma (geliştiriciler)

```bash
python build.py            # dist/deprem-analiz-marmara/ exe'si
python build.py --release  # + GitHub Release paketi (win64 zip)
```

- Build, `dist/` içindeki kullanıcı `data/` klasörünü **korur**
  (yedekler ve geri yükler).
- Release akışı: `deprem_izleme/version.py` dosyasındaki sürümü
  artırın (`1.0.0` → `1.0.1`), `python build.py --release` ile paketi
  üretin, GitHub'da `v1.0.1` etiketiyle release açıp zip'i ekleyin.
- Uygulama açılışta (sessizce) ve Ayarlar'dan (manuel) yeni release
  denetler; paket bulunduysa indirip `data/` hariç dosyaları
  değiştirir ve yeniden başlar. Depo adresi
  `deprem_izleme/config.py` içindeki `GITHUB_OWNER` / `GITHUB_REPO`
  alanlarındadır.

Taşınabilir (portable) yapı bilinçli tercih edildi: kurulum
gerektirmez ve uygulama kendi kendini tek klasör değişimiyle
güncelleyebilir (kurulum sihirbazı bu akışı zorlaştırırdı).

## Proje yapısı

```
deprem_izleme/
├── gui.py            # arayüz (sayfalar, tema, güncelleme)
├── aggregation.py    # b-değeri, Poisson, Omori, risk skoru
├── analysis.py       # tekrarlama aralıkları, dağılımlar, AI metni
├── predictor.py      # kısa vadeli bileşik gösterge
├── charts.py         # matplotlib figürleri (tembel yüklenir)
├── marmara_canvas.py # gömülü harita (sıfır bağımlılık)
├── coastline.py / sealines.py / fault_traces.py  # gömülü coğrafya
├── fault_segments.py # segment riskleri, tarihsel katalog
├── stress_transfer.py# Coulomb ΔCFF
├── db.py / fetcher.py / fetcher_koeri.py  # veri katmanı
├── notifier.py       # Telegram
├── news_fetcher.py   # Google News RSS
├── updater.py        # GitHub Releases güncelleme
├── tooltips.py       # metrik açıklamaları
├── errors.py         # hata/teşhis kayıtları (yerel)
├── config.py / version.py
main.py / run_gui.py / build.py
assets/                # ikon + sayısallaştırma betikleri
```

## Veri kaynakları ve atıflar

- Deprem verisi: [Sismik Harita](https://sismikharita.com)
  (bilgilendirme amaçlıdır), [KOERI](http://www.koeri.boun.edu.tr/scripts/lst0.asp)
- Kıyı çizgileri: [Natural Earth](https://www.naturalearthdata.com) (public domain)
- Fay izleri: MTA diri fay haritalarının QGIS sayısallaştırması
  ([ozangerger/earthquakes-in-istanbul](https://github.com/ozangerger/earthquakes-in-istanbul))
- Yöntemler: Gutenberg & Richter (1944), Aki (1965), Utsu (1966),
  Gardner & Knopoff (1974), Reasenberg & Jones (1989),
  King, Stein & Lin (1994), Parsons (2004), Wiemer & Wyss (2000),
  Schorlemmer & Wiemer (2005), Gulia & Wiemer (2019),
  Muderrisoglu & Yazgan (2020, doi:10.1007/s11803-020-0553-2),
  Jordan vd. (2011, ICEF, doi:10.4401/ag-5350)

## Gizlilik

Uygulama konum takibi yapmaz, hesap istemez. API anahtarı ve Telegram
bilgileri yalnızca yerel `data/settings.json` dosyasında durur ve bu
dosya sürüm kontrolüne girmez (`.gitignore`). Bildirim/arıza kayıtları
da yereldir.

## Ortam değişkenleri (isteğe bağlı)

| Değişken | Açıklama |
| --- | --- |
| `DEPREM_TELEGRAM_TOKEN` / `DEPREM_TELEGRAM_CHAT_ID` | Telegram bildirimi |
| `DEPREM_START_PAGE` | Açılışta doğrudan sayfa (örn. `harita`) |

## Lisans

MIT — bkz. [LICENSE](LICENSE).
