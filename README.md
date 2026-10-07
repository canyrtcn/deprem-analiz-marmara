# Deprem İzleme — Marmara Bölgesi

Marmara Denizi ve İstanbul çevresindeki depremleri izleyen, risk analizi yapan
açık kaynaklı masaüstü uygulaması (Python + CustomTkinter).

## Özellikler

- **Canlı veri:** Sismik Harita API'si (anahtar gerekmez) + KOERI Kandilli
- **Gerçek harita:** Natural Earth kıyı çizgileri üzerinde MTA diri fay
  haritası sayısallaştırması, tıklanabilir deprem noktaları, katmanlar
- **Bilimsel analiz:** Gutenberg-Richter b-değeri (Aki MLE + Utsu düzeltmesi,
  MAXC tamlık), Poisson olasılıkları (Gardner-Knopoff artçı ayıklamalı),
  Omori-Utsu artçı öngörüsü, Coulomb stres transferi, fay segment riskleri
- **Grafikler:** günlük aktivite, b-trendi, enerji, FMD, saatlik/derinlik
  dağılımları, büyüklük-zaman serisi
- **Bildirimler:** eşik/filtre/cooldown ayarlı Telegram uyarıları
- **Tema:** koyu + açık görünüm

## Kurulum

```bash
pip install -r requirements.txt
python run_gui.py
```

Komut satırı (rapor, geçmiş, alarm):

```bash
python main.py update
python main.py report
```

## Derleme (Windows exe)

```bash
python build.py
```

Çıktı: `dist/deprem-izleme/deprem-izleme.exe`. İlk çalıştırmada `data/`
klasörü ve veritabanları otomatik oluşur.

## Veri kaynakları ve atıflar

- Deprem verisi: [Sismik Harita](https://sismikharita.com) (bilgilendirme amaçlıdır;
  resmi veriler için AFAD ve Kandilli Rasathanesi'ne bakın), KOERI
- Kıyı çizgileri: [Natural Earth](https://www.naturalearthdata.com) (public domain)
- Fay izleri: MTA diri fay haritalarının QGIS sayısallaştırması
  ([ozangerger/earthquakes-in-istanbul](https://github.com/ozangerger/earthquakes-in-istanbul))
- Yöntemler: Gutenberg & Richter (1944), Aki (1965), Utsu (1966),
  Gardner & Knopoff (1974), Reasenberg & Jones (1989),
  King, Stein & Lin (1994), Parsons (2004), Schorlemmer & Wiemer (2005),
  Gulia & Wiemer (2019), Wiemer & Wyss (2000)

## Ortam değişkenleri (isteğe bağlı)

| Değişken | Açıklama |
| --- | --- |
| `DEPREM_TELEGRAM_TOKEN` / `DEPREM_TELEGRAM_CHAT_ID` | Telegram bildirimi |
| `DEPREM_START_PAGE` | Açılışta doğrudan sayfa (örn. `harita`) |

Ayarların çoğu uygulama içinden (Ayarlar sayfası, `data/settings.json`)
yapılır; bu dosya depoya girmez.

## Lisans

MIT — bkz. [LICENSE](LICENSE).
