"""
messari_news_client.py

Aanvullende nieuwsbron naast rss_news_client.py (27 aug 2026). Zelfde
interface (fetch_news(asset, max_age_hours) -> lijst met .id/.title/
.summary/.published_at/.url/.source_feed) zodat de orchestrator beide
bronnen simpelweg kan samenvoegen.

Structuur volledig bevestigd via Messari's eigen documentatie (27 aug
2026, inclusief kind-attributen):
- GET https://api.messari.io/news/v1/news/feed
- Header: X-Messari-API-Key
- assetIds-parameter accepteert slugs (bevestigd via /news/v1/news/assets:
  data[].slug, bv. "bitcoin", "hedera")
- publishedAfter/publishedBefore in RFC3339
- Elk nieuwsitem: data.title, data.url, data.publishTimeMillis (LET OP:
  milliseconden-timestamp, geen RFC3339-string), data.description
  (optioneel), data.assets, data.sentiment (Messari's EIGEN
  sentiment-inschatting -- momenteel niet gebruikt, maar op termijn
  mogelijk bruikbaar als extra signaal naast onze eigen LLM-analyse),
  data.source, data.category/subcategory (optioneel). GEEN los
  "id"-veld voor een item zelf -- we genereren zelf een deterministische
  id uit de URL.
"""

import os
import time
import requests
from dataclasses import dataclass
from typing import List, Optional

MESSARI_NEWS_URL = "https://api.messari.io/news/v1/news/feed"

# Bevestigd via /news/v1/news/assets (27 aug 2026).
ASSET_SLUGS = {
    "BTC": "bitcoin",
    "HBAR": "hedera",
}


@dataclass
class MessariNewsItem:
    id: str
    title: str
    summary: str
    published_at: float
    url: str
    source_feed: str = "messari"


class MessariNewsClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("MESSARI_API_KEY")

    def fetch_news(self, asset: str, max_age_hours: float = 24.0) -> List[MessariNewsItem]:
        if not self.api_key:
            print("[messari] Geen MESSARI_API_KEY ingesteld -- sla deze bron over.")
            return []

        asset_slug = ASSET_SLUGS.get(asset)
        if not asset_slug:
            return []

        import datetime
        published_after = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=max_age_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            resp = requests.get(
                MESSARI_NEWS_URL,
                headers={"X-Messari-API-Key": self.api_key},
                params={
                    "assetIds": [asset_slug],
                    "publishedAfter": published_after,
                    "limit": 20,
                    "sort": 2,  # DESC (nieuwste eerst)
                },
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            print(f"[messari] Ophalen mislukt ({e}) -- sla deze bron voor nu over, "
                  f"RSS-feeds blijven werken.")
            return []

        raw_items = payload.get("data", [])
        if not isinstance(raw_items, list):
            print(f"[messari] Onverwachte response-vorm (geen 'data'-lijst) -- "
                  f"mogelijk is de API-structuur veranderd sinds dit gebouwd is.")
            return []

        results = []
        for raw in raw_items:
            title = raw.get("title", "")
            url = raw.get("url", "")
            if not title:
                continue

            publish_time_millis = raw.get("publishTimeMillis")
            published_at = (
                publish_time_millis / 1000.0 if publish_time_millis else time.time()
            )

            results.append(MessariNewsItem(
                id=f"messari-{url or title}",
                title=title,
                summary=raw.get("description", "")[:500],
                published_at=published_at,
                url=url,
            ))

        return results


