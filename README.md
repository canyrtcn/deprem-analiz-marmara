# Deprem Analiz — Marmara

**Marmara Denizi ve İstanbul çevresindeki deprem verilerini takip edin, harita ve grafiklerle inceleyin, bilimsel yöntemlere dayalı istatistiksel göstergeleri keşfedin.**

![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D4?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square)
![Lisans](https://img.shields.io/badge/License-MIT-43A047?style=flat-square)
![Arayüz](https://img.shields.io/badge/UI-CustomTkinter-495057?style=flat-square)
![Veritabanı](https://img.shields.io/badge/Database-SQLite-003B57?style=flat-square)
[![Son sürüm](https://img.shields.io/badge/Release-v1.0.1-6F42C1?style=flat-square)](https://github.com/canyrtcn/deprem-analiz-marmara/releases/tag/v1.0.1)

**Deprem Analiz — Marmara**, Python, CustomTkinter ve SQLite ile geliştirilmiş açık kaynaklı bir Windows masaüstü uygulamasıdır. Deprem kayıtlarını yerel olarak saklar, geçmiş etkinliği analiz eder ve isteğe bağlı Telegram bildirimleri sunar.

> [!IMPORTANT]
> ### ⚠️ Önemli
>
> **Depremlerin zamanı, yeri ve büyüklüğü önceden kesin olarak tahmin edilemez.** Bu proje, deprem verilerini analiz etmek ve bilimsel modelleri görselleştirmek amacıyla geliştirilmiş **deneysel bir uygulamadır; erken uyarı sistemi değildir.** İstatistiksel model çıktıları kesin deprem tahmini olarak değerlendirilmemelidir. Resmî duyurular için [AFAD](https://www.afad.gov.tr/) ve [Kandilli Rasathanesi](https://www.koeri.boun.edu.tr/) kaynaklarını takip edin.

## Uygulama görünümü

![Deprem Analiz — Marmara, açık tema ana ekran](assets/demo_ana_ekran_acik_tema.png)

*Ekran görüntüsünde arayüzü tanıtmak için hazırlanmış **sentetik örnek veriler** kullanılmıştır.*

## Özellikler

| Alan | Açıklama |
| --- | --- |
| **Deprem takibi** | Sismik Harita API ve Kandilli/KOERI kaynaklarından kayıt çekme; kaynağa ve zamana göre inceleme |
| **Harita** | Gömülü Marmara haritası, deprem noktaları, sayısallaştırılmış fay çizgileri, yakınlaştırma ve etkileşim |
| **Risk ve aktivite göstergeleri** | Deprem sıklığı, büyüklük, derinlik ve diğer istatistiklerden oluşturulan açıklamalı bileşik göstergeler |
| **İstatistiksel analiz** | Gutenberg–Richter b-değeri, büyüklük-frekans dağılımı, katalog tamlığı ve Poisson modeli |
| **Artçı aktivitesi** | Uygun anaşok ve büyüklük türü koşullarında Omori temelli model çıktıları |
| **Grafikler ve geçmiş** | Zaman serileri, büyüklük/derinlik dağılımları, enerji, eğilimler ve dönemsel raporlar |
| **Bildirimler** | Kullanıcı tarafından yapılandırılan eşiklere göre Telegram bildirimleri ve bildirim geçmişi |
| **Arayüz** | Açık/koyu tema, metodoloji açıklamaları ve yerel veriyle çevrimdışı inceleme |

## İndirme ve kurulum

### Windows için hazır paket

**[Son sürüm: v1.0.1 — GitHub Releases](https://github.com/canyrtcn/deprem-analiz-marmara/releases/tag/v1.0.1)**

1. `deprem-analiz-marmara-win64.zip` paketini indirin.
2. ZIP arşivini bilgisayarınızda yazma izniniz olan bir klasöre çıkarın.
3. Klasördeki `deprem-analiz-marmara.exe` dosyasını çalıştırın. Ayrı bir kurulum sihirbazı gerekmez.
4. İlk açılışta sunulan API/ayarlar rehberini izleyin. API anahtarı zorunlu değildir; anahtarsız kullanımda sağlayıcının kota sınırları uygulanabilir.

> **Güncelleme notu:** Yeni sürüme geçmeden önce `data/` klasörünüzü yedekleyin. ZIP paketi kişisel verilerinizi içermez.

### Kaynak koddan çalıştırma

Python 3.10 veya daha yeni bir Python 3 sürümü önerilir.

```bash
python -m pip install -r requirements.txt
python run_gui.py
```

Komut satırı üzerinden örnek işlemler:

```bash
python main.py fetch --days 7
python main.py update
python main.py report
python main.py history weekly
python main.py backfill
```

Kullanılabilir diğer seçenekler için `python main.py --help` komutunu çalıştırın.

## Analiz yöntemleri

Uygulama, deprem kataloglarından elde edilen verileri farklı istatistiksel yöntemlerle değerlendirir:

| Yöntem | Ne gösterir? |
| --- | --- |
| **Gutenberg–Richter** | Deprem büyüklüklerinin görülme sıklığını ve `a`/`b` parametrelerini inceler. |
| **Katalog tamlığı (Mc)** | Büyüklük-frekans analizinin dayandığı katalog yeterliliğini değerlendirir. |
| **Poisson modeli** | Seçilen büyüklük eşiği ve zaman aralığı için istatistiksel olay olasılıkları üretir. |
| **Omori–Utsu** | Uygun anaşok dizilerinde artçı deprem etkinliğinin zamana bağlı değişimini modeller. |
| **Aktivite ve risk göstergeleri** | Deprem sıklığı, büyüklük, derinlik ve eğilimleri bir araya getirerek karşılaştırmalı puanlar sunar. |
| **Fay ve bölgesel inceleme** | Marmara fay segmentlerini, tarihsel deprem kayıtlarını ve ilgili bilimsel çalışmaları harita üzerinde birleştirir. |

Hesaplamalar mevcut kayıtların kapsamına göre değişebilir; yeterli veri olmadığında ilgili gösterge hesaplanmayabilir. Bileşik aktivite/risk puanları **deprem olasılığı yüzdesi değildir**.

Deprem kayıtları [Sismik Harita](https://sismikharita.com) ve [Kandilli/KOERI](https://www.koeri.boun.edu.tr/) üzerinden alınır. ML, Mw ve MD farklı büyüklük türleridir.

Yöntemlerin bilimsel dayanakları ve Marmara literatürü aşağıdaki [Kaynaklar ve atıflar](#kaynaklar-ve-atıflar) bölümündedir.

## Telegram bildirimleri

İsteğe bağlı Telegram bildirimlerini uygulamanın Ayarlar ekranından veya aşağıdaki komutla yapılandırabilirsiniz:

```bash
python main.py telegram-setup
```

Bildirimler, seçtiğiniz eşiklere göre gönderilir. Bot tokenınızı paylaşmayın; komut satırına doğrudan parametre olarak yazmak yerine güvenli giriş yöntemini kullanın.

## Güncellemeler

Uygulama yeni sürümleri bildirebilir; indirme ve kurulum [GitHub Releases](https://github.com/canyrtcn/deprem-analiz-marmara/releases) üzerinden **elle yapılır**. Otomatik güncelleme indirme ve kurma **devre dışıdır**.

Önceki sürümleri ve değişikliklerini [Releases](https://github.com/canyrtcn/deprem-analiz-marmara/releases) sayfasında bulabilirsiniz.

## Gizlilik ve yerel veriler

Deprem kayıtları, kullanıcı ayarları ve bildirim geçmişi bilgisayarınızda saklanır. Hesap oluşturmanız veya konum paylaşmanız gerekmez. API anahtarları ve Telegram bilgilerinizin bulunduğu ayar dosyalarını güvenli tutun.

### Ortam değişkenleri

| Değişken | Açıklama |
| --- | --- |
| `DEPREM_TELEGRAM_TOKEN` | Telegram bot tokenı |
| `DEPREM_TELEGRAM_CHAT_ID` | Bildirimlerin gönderileceği sohbet kimliği |
| `DEPREM_START_PAGE` | Açılışta gösterilecek sayfa |
| `DEPREM_DEV=1` | Geliştirme ortamı seçeneği |

Uygulama `.env` dosyasını otomatik okumaz; değişkenler işletim sistemi ortamında tanımlanır. `.env.example` örnek yapılandırma dosyasıdır.

## Geliştirme ve paketleme

```bash
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python build.py
python build.py --release
```

`python build.py` taşınabilir Windows uygulamasını `dist/` altında oluşturur. `--release` seçeneği dağıtım için ZIP paketi hazırlar; kullanıcıya ait `data/` klasörü pakete alınmaz.

Ana modüller `deprem_izleme/` paketinde; GUI giriş noktası `run_gui.py`, CLI `main.py`, paketleyici `build.py` dosyasındadır.

## Kaynaklar ve atıflar

Uygulamanın istatistiksel yaklaşımlarına ve Marmara'nın sismotektonik yapısına ışık tutan bilimsel çalışmalar aşağıda yer alıyor. Her yayının projeyle bağlantısı kısaca özetlenmiştir.

### Deprem istatistiği ve katalog analizi

| Çalışma | Bilimsel katkısı ve projeyle bağlantısı |
| --- | --- |
| **Gutenberg & Richter (1944)** — [*Frequency of earthquakes in California*](https://doi.org/10.1785/BSSA0340040185) | Deprem büyüklüğü–frekans yasası; `a` ve `b` parametrelerinin temeli. |
| **Aki (1965)** — [*Maximum likelihood estimate of b in the formula log N = a − bM and its confidence limits*](https://doi.org/10.15083/0000033631) | `b` değerinin maksimum olabilirlik yöntemiyle hesaplanması. |
| **Utsu (1966)** — [*A Statistical Significance Test of the Difference in b-value between Two Earthquake Groups*](https://doi.org/10.4294/jpe1952.14.37) | Farklı deprem gruplarının `b` değerlerini istatistiksel olarak karşılaştırma yaklaşımı. |
| **Shi & Bolt (1982)** — [*The standard error of the magnitude-frequency b value*](https://doi.org/10.1785/BSSA0720051677) | `b` değerinin standart hatası ve belirsizlik analizi. |
| **Wiemer & Wyss (2000)** — [*Minimum Magnitude of Completeness in Earthquake Catalogs*](https://doi.org/10.1785/0119990114) | Katalog tamlık büyüklüğünün (`Mc`) ve büyüklük-frekans dağılımının değerlendirilmesi. |
| **Woessner & Wiemer (2005)** — [*Assessing the Quality of Earthquake Catalogues: Estimating the Magnitude of Completeness and Its Uncertainty*](https://doi.org/10.1785/0120040007) | Katalog kalitesi ve `Mc` tahmininin nicel değerlendirilmesi. |
| **Gardner & Knopoff (1974)** — [*Is the sequence of earthquakes in Southern California, with aftershocks removed, Poissonian?*](https://doi.org/10.1785/BSSA0640051363) | Artçı kümelerini ayıklama ve arka plan sismisitesini inceleme yöntemi. |
| **Hanks & Kanamori (1979)** — [*A moment magnitude scale*](https://doi.org/10.1029/JB084iB05p02348) | Sismik moment ve moment büyüklüğü (`Mw`) arasındaki temel bağıntı. |
| **Schorlemmer, Wiemer & Wyss (2005)** — [*Variations in earthquake-size distribution across different stress regimes*](https://doi.org/10.1038/nature04094) | `b` değerinin farklı tektonik gerilme ortamlarında değişimine ilişkin bulgular. |

### Artçı sismisitesi ve istatistiksel modeller

| Çalışma | Bilimsel katkısı ve projeyle bağlantısı |
| --- | --- |
| **Reasenberg & Jones (1989)** — [*Earthquake Hazard After a Mainshock in California*](https://doi.org/10.1126/science.243.4895.1173) | Anaşok sonrası artçı etkinliğinin istatistiksel modellenmesi. |
| **Müderrisoğlu & Yazgan (2020)** — [*Development of an aftershock occurrence model calibrated for Turkey and the resulting likelihoods*](https://doi.org/10.1007/s11803-020-0553-2) | Türkiye'deki `Mw ≥ 5.9` anaşok dizilerine dayanan Omori modeli kalibrasyonu. |
| **Gulia & Wiemer (2019)** — [*Real-time discrimination of earthquake foreshocks and aftershocks*](https://doi.org/10.1038/s41586-019-1606-4) | Öncü ve artçı deprem dizilerinin gerçek zamanlı ayrımına ilişkin araştırma. |
| **Jordan ve diğerleri (2011)** — [*Operational Earthquake Forecasting: State of Knowledge and Guidelines for Utilization*](https://doi.org/10.4401/ag-5350) | Operasyonel deprem tahmini modellerinin bilimsel çerçevesi ve sonuçların iletişimi. |

### Marmara fay sistemi, tarihsel deprem etkinliği ve gerilme

| Çalışma | Bilimsel katkısı ve projeyle bağlantısı |
| --- | --- |
| **Le Pichon ve diğerleri (2001)** — [*The active Main Marmara Fault*](https://doi.org/10.1016/S0012-821X(01)00449-6) | Ana Marmara Fayı'nın geometrisi ve aktif tektonik yapısı. |
| **Ambraseys (2002)** — [*The Seismic Activity of the Marmara Sea Region over the Last 2000 Years*](https://doi.org/10.1785/0120000843) | Marmara'nın uzun dönem tarihsel deprem etkinliği. |
| **Armijo ve diğerleri (2005)** — [*Submarine fault scarps in the Sea of Marmara pull-apart*](https://doi.org/10.1029/2004GC000896) | Marmara Denizi tabanındaki fay izleri ve segment morfolojisi. |
| **Parsons (2004)** — [*Recalculated probability of M ≥ 7 earthquakes beneath the Sea of Marmara, Turkey*](https://doi.org/10.1029/2003JB002667) | Marmara için olasılıksal sismik tehlike araştırmaları. |
| **Rockwell ve diğerleri (2009)** — [*Palaeoseismology of the North Anatolian fault near the Marmara Sea*](https://doi.org/10.1144/SP316.3) | Kuzey Anadolu Fayı'nda paleosismoloji, kırılma geçmişi ve segmentasyon. |
| **Martínez-Garzón ve diğerleri (2026; çevrimiçi 2025)** — [*Progressive eastward rupture of the Main Marmara fault toward Istanbul*](https://doi.org/10.1126/science.adz0072) | 2025 Marmara deprem dizisi ve doğuya ilerleyen fay kırılmalarının analizi. |
| **King, Stein & Lin (1994)** — [*Static stress changes and the triggering of earthquakes*](https://doi.org/10.1785/BSSA0840030935) | Statik gerilme değişimleri ve Coulomb gerilmesi yaklaşımı. |
| **Okada (1992)** — [*Internal deformation due to shear and tensile faults in a half-space*](https://doi.org/10.1785/BSSA0820021018) | Elastik yarı uzayda fay kaynaklı deformasyonun matematiksel temeli. |
| **Wells & Coppersmith (1994)** — [*New empirical relationships among magnitude, rupture length, rupture width, rupture area, and surface displacement*](https://doi.org/10.1785/BSSA0840040974) | Deprem büyüklüğü ile kırılma boyutları arasındaki ampirik ilişkiler. |

### Veri ve harita kaynakları

| Kaynak | Kullanım ve kapsam |
| --- | --- |
| [Sismik Harita](https://sismikharita.com) | Deprem katalogları ve güncel kayıtların temini. |
| [Kandilli Rasathanesi / KOERI](https://www.koeri.boun.edu.tr/) | Kandilli deprem kataloğu ve bölgesel kayıtların incelenmesi. |
| [AFAD](https://deprem.afad.gov.tr/) | Resmî deprem verileri ve güncel duyurular için referans. |
| [Natural Earth](https://www.naturalearthdata.com/) | Marmara kıyı çizgisi ve temel coğrafi altlık. |
| [MTA — Türkiye Diri Fay Haritası](https://tdfh.mta.gov.tr/) | Türkiye'nin diri fay sistemine ilişkin kurumsal harita referansı. |
| [ozangerger/earthquakes-in-istanbul](https://github.com/ozangerger/earthquakes-in-istanbul) | MTA temelli fay izlerinin sayısallaştırılması için yararlanılan kaynak proje. |

## Lisans

Kaynak kod [MIT Lisansı](LICENSE) altında açık kaynak olarak sunulmaktadır.
