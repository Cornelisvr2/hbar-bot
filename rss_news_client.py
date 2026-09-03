"""
rss_news_client.py

Vervangt cryptopanic_client.py als primaire nieuwsbron. Reden: CryptoPanic
heeft (1) geen bruikbare gratis tier meer (goedkoopste betaald plan
~$179-199/maand), en (2) blokkeert verkeer vanaf VPS/datacenter-IP's via
Cloudflare, ongeacht of de token geldig is (bevestigd 22 aug 2026).

RSS-feeds van gevestigde nieuwssites zijn gratis en zitten zelden achter
dit soort bot-bescherming. Nadeel t.o.v. CryptoPanic: geen ingebouwde
community-votes/importance-vlaggen -- puur de ruwe headline + samenvatting,
die we vervolgens aan llm_sentiment_engine.py voeren voor de eigenlijke
sentiment-beoordeling (wat toch al de primaire methode was, CryptoPanic's
votes waren aanvullend).
"""

import time
import hashlib
import feedparser
from dataclasses import dataclass
from typing import List, Optional


# Bekende, betrouwbare crypto-nieuwsfeeds. Geen enkele vereist een API-key.
RSS_FEEDS_BY_ASSET = {
    "BTC": [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss/tag/bitcoin",
    ],
    "HBAR": [
        "https://cointelegraph.com/rss/tag/hedera-hashgraph",
        # Hedera-specifiek nieuws is dunner gezaaid dan BTC -- de algemene
        # crypto-feed hieronder vangt bredere Hedera-vermeldingen op die
        # niet altijd apart getagd zijn.
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        # Google News RSS -- werkt op elk zoekwoord, geen afhankelijkheid
        # van de exacte tag-URL-structuur van een specifieke nieuwssite.
        "https://news.google.com/rss/search?q=hedera+hbar+when:7d&hl=en-US&gl=US&ceid=US:en",
    ],
}

# Simpele keyword-filter voor de bredere feeds, om te voorkomen dat elk
# BTC-artikel per ongeluk als "HBAR-nieuws" wordt meegeteld als het toevallig
# via dezelfde algemene feed binnenkomt.
ASSET_KEYWORDS = {
    "BTC": ["bitcoin", "btc"],
    "HBAR": ["hedera", "hbar", "hashgraph"],
}

# Automatisch gegenereerde valuta-omreken-pagina's (bv. van Bybit) bevatten
# toevallig "HBAR" of "BTC" maar zijn geen nieuws -- expliciet uitsluiten.
JUNK_TITLE_PATTERNS = [
    "convert ",  # "Convert 10 HBAR to OMR - Bybit" e.d.
]


def _is_junk_title(title: str) -> bool:
    lowered = title.lower()
    return any(lowered.startswith(pattern) for pattern in JUNK_TITLE_PATTERNS)


@dataclass
class RssNewsItem:
    id: str            # deterministisch gegenereerd uit de URL (RSS heeft geen stabiele id zoals CryptoPanic)
    title: str
    summary: str
    published_at: float  # unix timestamp
    url: str
    source_feed: str


class RssNewsClient:
    def __init__(self, feeds_by_asset: Optional[dict] = None):
        self.feeds_by_asset = feeds_by_asset or RSS_FEEDS_BY_ASSET

    def fetch_news(self, asset: str, max_age_hours: float = 24.0) -> List[RssNewsItem]:
        """
        Haalt recent nieuws op voor een asset (BTC of HBAR) uit de
        bijbehorende RSS-feeds, gefilterd op keyword-relevantie en leeftijd.
        """
        feeds = self.feeds_by_asset.get(asset, [])
        keywords = [k.lower() for k in ASSET_KEYWORDS.get(asset, [])]
        cutoff = time.time() - max_age_hours * 3600

        items: List[RssNewsItem] = []
        seen_ids = set()

        for feed_url in feeds:
            parsed = feedparser.parse(feed_url)

            for entry in parsed.entries:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                link = entry.get("link", "")

                # Keyword-relevantiefilter (nodig voor de bredere feeds
                # die niet asset-specifiek getagd zijn)
                combined_text = f"{title} {summary}".lower()
                if not any(kw in combined_text for kw in keywords):
                    continue
                if _is_junk_title(title):
                    continue

                published_ts = self._parse_published(entry)
                if published_ts < cutoff:
                    continue

                item_id = hashlib.sha256(link.encode()).hexdigest()[:16]
                if item_id in seen_ids:
                    continue  # zelfde artikel via meerdere feeds
                seen_ids.add(item_id)

                items.append(RssNewsItem(
                    id=item_id, title=title, summary=summary,
                    published_at=published_ts, url=link, source_feed=feed_url,
                ))

        items.sort(key=lambda x: x.published_at, reverse=True)
        return items

    @staticmethod
    def _parse_published(entry) -> float:
        # feedparser geeft published_parsed als time.struct_time terug
        parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed_time:
            return time.mktime(parsed_time)
        return time.time()  # fallback als de feed geen datum meegeeft


if __name__ == "__main__":
    client = RssNewsClient()

    for asset in ("BTC", "HBAR"):
        print(f"\n--- {asset} ---")
        try:
            items = client.fetch_news(asset, max_age_hours=48)
            print(f"{len(items)} relevante items gevonden (laatste 48u)")
            for item in items[:3]:
                print(f"  - {item.title[:80]}")
        except Exception as e:
            print(f"Fout bij ophalen: {e}")
