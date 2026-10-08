"""
Haber çekici - Deprem haberleri (Google News RSS).

Not: Eski sürüm Nitter (Twitter) üzerinden bilim insanı paylaşımlarını
çekiyordu; Nitter 2024'te kapandı, istekler 6'şar saniye asılı kalıp
zaman aşımına uğruyordu. Kaldırıldı - sadece hızlı RSS.
"""
import logging
import re
import html
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import requests

from deprem_izleme.config import NEWS_TIMEOUT

logger = logging.getLogger(__name__)

# Haber kaynakları (arama URL'leri)
NEWS_SOURCES = [
    ("Google News - İstanbul Deprem",
     "https://news.google.com/rss/search?q=İstanbul+deprem+son+dakika&hl=tr&gl=TR&ceid=TR:tr"),
    ("Google News - Marmara Deprem",
     "https://news.google.com/rss/search?q=Marmara+deprem+risk+İstanbul&hl=tr&gl=TR&ceid=TR:tr"),
]

# Önbellek
_news_cache = []
_cache_time = None
_CACHE_SECONDS = 600


def _parse_pubdate(s):
    """RSS pubDate -> sıralanabilir timestamp (hata toleranslı)."""
    try:
        dt = parsedate_to_datetime(s.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp(), dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return 0, (s or "")[:25]


def fetch_news(max_items=20):
    """
    Deprem haberlerini çek (Google News RSS).
    Döner: [{kaynak, başlık, link, tarih, tip}]
    """
    global _news_cache, _cache_time

    # 10 dakikalık önbellek
    if _cache_time and (datetime.now() - _cache_time).total_seconds() < _CACHE_SECONDS and _news_cache:
        return _news_cache[:max_items]

    news = []

    # Google News RSS'den haberler
    for name, url in NEWS_SOURCES:
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=NEWS_TIMEOUT)
            if resp.status_code == 200:
                # RSS'i parse et
                items = re.findall(r'<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>.*?<pubDate>(.*?)</pubDate>',
                                   resp.text, re.DOTALL)
                for title, link, pub_date in items[:10]:
                    # Sıra önemli: önce CDATA (aksi halde tag-temizliği
                    # ilk '>'ye kadar her şeyi yer), sonra unescape+tag
                    title = title.replace('<![CDATA[', '').replace(']]>', '')
                    title = html.unescape(title)
                    title = re.sub(r'<.*?>', '', title).strip()
                    if title and len(title) > 10:
                        sort_ts, nice_date = _parse_pubdate(pub_date)
                        news.append({
                            "kaynak": name,
                            "baslik": title[:140],
                            "link": link.strip(),
                            "tarih": nice_date,
                            "tip": "haber",
                            "_sort": sort_ts,
                        })
        except Exception as e:
            logger.debug(f"RSS hatası {name}: {e}")

    # Tarihe göre sırala (yeniden eskiye)
    news.sort(key=lambda x: x.pop("_sort", 0), reverse=True)

    _news_cache = news
    _cache_time = datetime.now()

    logger.info(f"{len(news)} haber çekildi")
    return news[:max_items]


def fetch_news_simple():
    """Basit haber çekme - hata toleranslı."""
    try:
        return fetch_news(max_items=30)
    except Exception as e:
        logger.error(f"Haber çekme hatası: {e}")
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    news = fetch_news()
    for n in news[:10]:
        icon = "📰" if n["tip"] == "haber" else "🐦"
        print(f"{icon} {n['kaynak'][:20]}: {n['baslik'][:60]}")
