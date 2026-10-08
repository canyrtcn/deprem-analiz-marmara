# Deprem Analiz — Marmara

**Marmara Denizi ve İstanbul çevresindeki deprem kayıtlarını takip etmek, görselleştirmek ve istatistiksel olarak incelemek için geliştirilmiş Windows masaüstü uygulaması.**

![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D4?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square)
![Lisans](https://img.shields.io/badge/License-MIT-43A047?style=flat-square)
![Arayüz](https://img.shields.io/badge/UI-CustomTkinter-495057?style=flat-square)
![Veritabanı](https://img.shields.io/badge/Database-SQLite-003B57?style=flat-square)
[![Son sürüm](https://img.shields.io/badge/Release-v1.0.1-6F42C1?style=flat-square)](https://github.com/canyrtcn/deprem-analiz-marmara/releases/tag/v1.0.1)

MIT lisanslı, açık kaynaklı bu Python, CustomTkinter ve SQLite tabanlı uygulama; deprem kayıtlarını yerel olarak saklar, harita ve grafikler üzerinden sunar, uygun veri koşullarında istatistiksel göstergeler hesaplar ve isteğe bağlı Telegram bildirimleri sağlar.

> [!IMPORTANT]
> **Deprem erken uyarı sistemi değildir.** Depremlerin ne zaman, nerede veya hangi büyüklükte gerçekleşeceğini güvenilir biçimde öngördüğü iddia edilmez. Olasılık olarak gösterilen değerler, varsayımlara bağlı **kalibre edilmemiş model çıktılarıdır**; bileşik aktivite/risk puanları ise olasılık değildir. Acil durumlarda ve resmî bilgilendirmelerde [AFAD](https://www.afad.gov.tr/) ile [Kandilli Rasathanesi](https://www.koeri.boun.edu.tr/) duyurularını esas alın.

## Uygulama görünümü

![Deprem Analiz — Marmara, açık tema ana ekran](assets/demo_ana_ekran_acik_tema.png)

*Arayüz tanıtımındaki deprem kayıtları ve metrikler **sentetik demo verileridir**. Gerçek ölçüm, güncel sismik durum veya operasyonel tahmin olarak yorumlanmamalıdır.*

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

Haritadaki fay çizgileri bilgilendirme amaçlı sayısallaştırılmış/şematik gösterimler içerir; resmî fay konumu, afet riski veya mühendislik değerlendirmesi yerine geçmez.

## İndirme ve kurulum

### Windows için hazır paket

**[Son sürüm: v1.0.1 — GitHub Releases](https://github.com/canyrtcn/deprem-analiz-marmara/releases/tag/v1.0.1)**

1. `deprem-analiz-marmara-win64.zip` paketini indirin.
2. ZIP arşivini bilgisayarınızda yazma izniniz olan bir klasöre çıkarın.
3. Klasördeki `deprem-analiz-marmara.exe` dosyasını çalıştırın. Ayrı bir kurulum sihirbazı gerekmez.
4. İlk açılışta sunulan API/ayarlar rehberini izleyin. API anahtarı zorunlu değildir; anahtarsız kullanımda sağlayıcının kota sınırları uygulanabilir.

> **Sürüm yükseltirken:** Mevcut `data/` klasörünüzü yedekleyin. Yeni paketi açtıktan sonra, verilerinizin yeni uygulama klasöründe korunmasını sağlayın; eski klasörü veya kişisel veri dosyalarını kontrol etmeden silmeyin. Release ZIP'i kullanıcı verilerini içermez.

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

## Veri kaynakları ve hesaplamaların yorumlanması

- **Kayıt kaynakları:** [Sismik Harita](https://sismikharita.com) ve [Kandilli/KOERI](https://www.koeri.boun.edu.tr/). Kaynakların güncellik, erişilebilirlik, büyüklük türü ve revizyon uygulamaları farklı olabilir. Ağ hatası, “deprem yok” sonucuyla aynı değildir.
- **Büyüklük türleri:** ML, Mw ve MD farklı ölçümlerdir. Uygulama bu türleri bilimsel dönüşüm yapmadan birbirine eşdeğer kabul etmez. Bazı kaynak/tür ayrımları mevcut v1 veritabanında tam olarak korunmaz.
- **Poisson modeli:** Katalog yeterliliği ve gözlem aralığı koşullarına bağlı, kalibre edilmemiş istatistiksel olasılıklar sağlar; fiziksel deprem tehlikesi tahmini değildir.
- **Bileşik skor:** Görsel karşılaştırma için kullanılan boyutsuz bir aktivite/risk göstergesidir. Yüzdelik deprem olasılığı olarak okunmamalıdır.
- **Omori modeli:** Her kayıt için geçerli değildir; doğrulanmış Mw türünde, Mw ≥ 5.9 uygun anaşok koşulu aranır.
- **Coulomb açıklamaları:** Arayüzdeki basitleştirilmiş gösterim, doğrulanmış bir ΔCFF çözümü veya deprem tetikleme hesabı değildir.
- **Eksik veri:** Yeterli ve uygun kayıt bulunmadığında uygulama bazı sayısal alanları hesaplamaz; “—” veya “yetersiz veri” gösterebilir.

Bu proje bilimsel kavramları erişilebilir kılmayı ve deprem verisini incelemeyi amaçlar; resmî tehlike haritası, erken uyarı hizmeti veya afet kararı destek sistemi değildir.

## Telegram bildirimleri

Telegram kullanımı isteğe bağlıdır. Ayarlar ekranından yapılandırılabilir veya terminalde gizli token girişiyle kurulabilir:

```bash
python main.py telegram-setup
```

Bot tokenını `--token` gibi komut satırı parametrelerine yazmayın. Gönderim durumu, başarılı/başarısız/atlanan işlemleri ayırt edecek şekilde raporlanır. Gerçek mesaj gönderebilmek için ağ erişimi ve geçerli Telegram bilgileri gerekir.

## Güncelleme ve bilinen sınırlamalar

- **v1.0.1'de otomatik güncelleme indirme/kurma devre dışıdır.** Yeni sürüm denetimi bilgi vermek içindir. Yeni paketi GitHub Releases üzerinden elle edinin.
- GitHub Releases erişilemiyorsa sürüm denetimi “Denetlenemedi” gösterebilir; bu, yeni sürümün bulunmadığının kanıtı değildir.
- Mevcut dağıtım **v1 SQLite şemasıyla** çalışır. Yeni olay/gözlem/sürüm veritabanı mimarisine canlı geçiş bu sürümde etkin değildir.
- Bazı gelişmiş istatistiksel modüllerin ve veri akışlarının bilinen sınırlamaları bulunmaktadır; çıktılar bilimsel uzman değerlendirmesinin yerine geçmez.
- Uygulama, mevcut kayıtları ağ bağlantısı olmadan görüntüleyebilir; yeni deprem verilerinin indirilmesi için ilgili kaynaklara bağlantı gerekir.

Önceki sürümler ve değişiklik açıklamaları için [Releases](https://github.com/canyrtcn/deprem-analiz-marmara/releases) sayfasına bakın.

## Gizlilik ve yerel veriler

Uygulama hesap açmayı veya konum takibini gerektirmez. Deprem veritabanları, ayarlar ve bildirim kayıtları yerel `data/` dizininde (gerekirse yazılabilir kullanıcı veri dizininde) tutulur. `data/settings.json` Git tarafından hariç tutulur; **Git tarafından hariç tutulması dosyanın şifrelendiği anlamına gelmez.** API anahtarlarını, Telegram kimlik bilgilerini ve yedekleri özel tutun; gerçek veri dosyalarını GitHub'a yüklemeyin.

| Ortam değişkeni | Amaç |
| --- | --- |
| `DEPREM_TELEGRAM_TOKEN` | Telegram bot tokenı |
| `DEPREM_TELEGRAM_CHAT_ID` | Telegram hedef sohbet kimliği |
| `DEPREM_START_PAGE` | GUI açılış sayfası (örn. `harita`) |
| `DEPREM_DEV=1` | Yerel geliştirme modu; üretim kullanımı için önerilmez |

Not: Uygulama `.env` dosyası okumaz; yukarıdaki değişkenler işletim sistemi ortamında tanımlanmalıdır. `.env.example` yalnızca başvurulacak değer listesidir.

## Geliştirme ve paketleme

```bash
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python build.py
python build.py --release
```

`python build.py`, `dist/` altında taşınabilir Windows uygulamasını üretir. `--release` seçeneği ayrıca ZIP oluşturur; **GitHub'a otomatik olarak release yayımlamaz**. Dağıtım ZIP'ine `data/` kullanıcı klasörü eklenmez.

Ana modüller `deprem_izleme/` paketinde; GUI giriş noktası `run_gui.py`, CLI `main.py`, paketleyici `build.py` dosyasındadır.

## Kaynaklar ve atıflar

Bu bölümde **uygulamanın hesaplamalarında yararlanılan yöntemsel çalışmalar**, **Marmara'nın sismotektoniğini açıklayan bilimsel yayınlar** ve **veri/harita kaynakları** ayrı gösterilmiştir. Makaleye atıf verilmesi, çalışmadaki bütün sonuçların veya parametrelerin uygulamaya eksiksiz aktarıldığı, bağımsız olarak doğrulandığı ya da uygulamanın yazarlar tarafından onaylandığı anlamına gelmez.

### Deprem istatistiği ve katalog analizi

| Çalışma | Uygulamadaki ilişki |
| --- | --- |
| **Gutenberg & Richter (1944)** — [*Frequency of earthquakes in California*](https://doi.org/10.1785/BSSA0340040185) | Deprem büyüklüğü–frekans ilişkisi (`a` ve `b` parametreleri). |
| **Aki (1965)** — [*Maximum likelihood estimate of b in the formula log N = a − bM and its confidence limits*](https://doi.org/10.15083/0000033631) | Gutenberg–Richter `b` değerinin maksimum olabilirlik yaklaşımı. |
| **Utsu (1966)** — [*A Statistical Significance Test of the Difference in b-value between Two Earthquake Groups*](https://doi.org/10.4294/jpe1952.14.37) | `b` değerinin istatistiksel değerlendirilmesine ilişkin klasik çalışma. |
| **Shi & Bolt (1982)** — [*The standard error of the magnitude-frequency b value*](https://doi.org/10.1785/BSSA0720051677) | `b` değeri belirsizliğine ilişkin yöntemsel referans; tam güven aralığı uygulamasıyla karıştırılmamalıdır. |
| **Wiemer & Wyss (2000)** — [*Minimum Magnitude of Completeness in Earthquake Catalogs*](https://doi.org/10.1785/0119990114) | Katalog tamlık büyüklüğü (`Mc`), MAXC ve uygunluk kontrolleri. |
| **Woessner & Wiemer (2005)** — [*Assessing the Quality of Earthquake Catalogues: Estimating the Magnitude of Completeness and Its Uncertainty*](https://doi.org/10.1785/0120040007) | `Mc` tahmini ile belirsizlik ve doğrulama ayrımı. |
| **Gardner & Knopoff (1974)** — [*Is the sequence of earthquakes in Southern California, with aftershocks removed, Poissonian?*](https://doi.org/10.1785/BSSA0640051363) | Zaman/uzaklık pencereleriyle artçı kümelerinin ayıklanmasına dayanak. |
| **Hanks & Kanamori (1979)** — [*A moment magnitude scale*](https://doi.org/10.1029/JB084iB05p02348) | Sismik moment ve moment büyüklüğü ilişkisine ilişkin arka plan. Farklı katalog büyüklük türleri doğrudan eşitlenmez. |
| **Schorlemmer, Wiemer & Wyss (2005)** — [*Variations in earthquake-size distribution across different stress regimes*](https://doi.org/10.1038/nature04094) | `b` değerinin fiziksel/tektonik yorumundaki kısıtlara ilişkin arka plan. |

### Artçı modelleri ve bilimsel tahmin sınırları

| Çalışma | Uygulamadaki ilişki |
| --- | --- |
| **Reasenberg & Jones (1989)** — [*Earthquake Hazard After a Mainshock in California*](https://doi.org/10.1126/science.243.4895.1173) | Anaşok sonrası artçı aktivitesinin istatistiksel modellenmesi için temel referans. |
| **Müderrisoğlu & Yazgan (2020)** — [*Development of an aftershock occurrence model calibrated for Turkey and the resulting likelihoods*](https://doi.org/10.1007/s11803-020-0553-2) | Türkiye artçı dizileriyle elde edilen Omori modeli parametreleri (`a = −1.90`, `b = 1.11`, `c = 0.05`, `p = 1.20`); uygun anaşok koşulları dışında uygulanmaz. |
| **Gulia & Wiemer (2019)** — [*Real-time discrimination of earthquake foreshocks and aftershocks*](https://doi.org/10.1038/s41586-019-1606-4) | Deprem dizilerinin yorumlanmasına ilişkin literatür; makaledeki özgül sınıflandırma yöntemi uygulamada doğrulanmış olarak sunulmaz. |
| **Jordan ve diğerleri (2011)** — [*Operational Earthquake Forecasting: State of Knowledge and Guidelines for Utilization*](https://doi.org/10.4401/ag-5350) | Operasyonel tahminlerde belirsizlik, iletişim ve kullanım sınırları için çerçeve. |

### Marmara fay sistemi, tarihsel deprem etkinliği ve gerilme

| Çalışma | Uygulamadaki ilişki |
| --- | --- |
| **Le Pichon ve diğerleri (2001)** — [*The active Main Marmara Fault*](https://doi.org/10.1016/S0012-821X(01)00449-6) | Marmara Denizi ana fay geometrisi ve bölgesel tektonik arka plan. |
| **Ambraseys (2002)** — [*The Seismic Activity of the Marmara Sea Region over the Last 2000 Years*](https://doi.org/10.1785/0120000843) | Tarihsel Marmara deprem kataloğu ve sismisite yorumları için kaynak. |
| **Armijo ve diğerleri (2005)** — [*Submarine fault scarps in the Sea of Marmara pull-apart*](https://doi.org/10.1029/2004GC000896) | Denizaltı fay morfolojisi ve segmentasyonuna ilişkin bölgesel çalışma. |
| **Parsons (2004)** — [*Recalculated probability of M ≥ 7 earthquakes beneath the Sea of Marmara, Turkey*](https://doi.org/10.1029/2003JB002667) | Marmara için olasılıksal tehlike araştırmalarına tarihsel/bilimsel bağlam; makaledeki bölgesel olasılıklar uygulamanın kendi kalibre edilmemiş çıktılarıyla eşdeğer değildir. |
| **Rockwell ve diğerleri (2009)** — [*Palaeoseismology of the North Anatolian fault near the Marmara Sea*](https://doi.org/10.1144/SP316.3) | Fay segmentasyonu, paleosismoloji ve tekrarlama bağlamı. |
| **Martínez-Garzón ve diğerleri (2026; çevrimiçi 2025)** — [*Progressive eastward rupture of the Main Marmara fault toward Istanbul*](https://doi.org/10.1126/science.adz0072) | Marmara'daki yakın dönem kırılmaların bilimsel yorumu; uygulamadaki fay tehlike puanlarının bu makaleyle doğrulandığı anlamına gelmez. |
| **King, Stein & Lin (1994)** — [*Static stress changes and the triggering of earthquakes*](https://doi.org/10.1785/BSSA0840030935) | Coulomb gerilme değişimi kavramının temel referansı. |
| **Okada (1992)** — [*Internal deformation due to shear and tensile faults in a half-space*](https://doi.org/10.1785/BSSA0820021018) | Elastik yarı uzay deformasyonu için referans; uygulamadaki basitleştirilmiş gösterim tam Okada çözümü değildir. |
| **Wells & Coppersmith (1994)** — [*New empirical relationships among magnitude, rupture length, rupture width, rupture area, and surface displacement*](https://doi.org/10.1785/BSSA0840040974) | Kırılma boyutları ile büyüklük arasındaki ampirik ilişkilerin arka planı. |

### Veri, harita ve coğrafi atıflar

| Kaynak | Kullanım ve kapsam |
| --- | --- |
| [Sismik Harita](https://sismikharita.com) | Deprem kaydı/API kaynağı; kullanım kotası ve kapsama koşulları sağlayıcıya bağlıdır. |
| [Kandilli Rasathanesi / KOERI](https://www.koeri.boun.edu.tr/) | Son depremler ve kaynak bazlı kayıt karşılaştırmaları. |
| [AFAD](https://deprem.afad.gov.tr/) | Resmî deprem bilgilerini kontrol etmek için başvuru kaynağı; uygulamanın bütün kayıtları doğrudan AFAD'dan çektiği anlamına gelmez. |
| [Natural Earth](https://www.naturalearthdata.com/) — [kullanım koşulları](https://www.naturalearthdata.com/about/terms-of-use/) | Harita/kıyı çizgilerinin coğrafi altlığı; Natural Earth verileri kamu malıdır (*public domain*). |
| [MTA — Türkiye Diri Fay Haritası](https://tdfh.mta.gov.tr/) | Fay gösterimleri için kurumsal referans. Uygulamadaki çizgiler resmî haritanın bire bir ve güncel kopyası değildir. |
| [ozangerger/earthquakes-in-istanbul](https://github.com/ozangerger/earthquakes-in-istanbul) | Fay geometrilerinin sayısallaştırılmasında belirtilen üçüncü taraf kaynak. **Kaynak göstermek, kod/veri yeniden dağıtım izni değildir; bu verilerin lisans/izin durumu ayrıca teyit edilmelidir.** |

> **Bilimsel ve hukuki kapsam:** Kaynak çalışmalar uygulamanın hesaplamalarıyla aynı değildir; birçok bileşen sadeleştirilmiş, kalibre edilmemiş veya yalnızca bilgilendirme amaçlıdır. Makale referansları bilimsel geçerlilik garantisi sağlamaz. Özellikle üçüncü taraf fay koordinatlarının dağıtım hakları doğrulanmadan projenin herkese açık yayını için lisans uygunluğu varsayılmamalıdır.

## Lisans

Kaynak kod [MIT Lisansı](LICENSE) altında açık kaynak olarak sunulmaktadır.
