"""
cryptopanic_client.py

Haalt nieuws op van de CryptoPanic API, apart gefilterd op BTC en HBAR,
en berekent per currency een tijdsgewogen sentiment-score tussen -1 en +1.

CryptoPanic API docs: https://cryptopanic.com/developers/api/
Vereist een (gratis) API-token: https://cryptopanic.com/developers/api/
"""

import time
import math
import requests
from dataclasses import dataclass
from typing import List, Optional


CRYPTOPANIC_BASE_URL = "https://cryptopanic.com/api/v1/posts/"

# Halfwaardetijd (in uren) voor het tijdsverval van nieuws-items.
# Een item van precies deze leeftijd weegt nog voor 50% mee.
SENTIMENT_HALF_LIFE_HOURS = 3.0

# Extra gewicht voor items die CryptoPanic zelf als "important" markeert.
IMPORTANT_NEWS_MULTIPLIER = 1.5


@dataclass
class NewsItem:
    id: int
    title: str
    published_at: float  # unix timestamp
    positive_votes: int
    negative_votes: int
    important_votes: int
    url: str


@dataclass
class SentimentResult:
    currency: str
    score: float          # -1.0 (zeer negatief) tot +1.0 (zeer positief)
    news_velocity: int     # aantal items in het lookback-window
    items: List[NewsItem]  # ruwe items, handig voor logging/debug


class CryptoPanicClient:
    def __init__(self, api_token: str, session: Optional[requests.Session] = None):
        self.api_token = api_token
        self.session = session or requests.Session()

    def fetch_news(self, currency: str, kind: str = "news", limit_pages: int = 1) -> List[NewsItem]:
        """
        Haalt nieuws op voor een specifieke currency (bijv. 'BTC' of 'HBAR').
        kind: 'news' of 'media'. Meestal wil je 'news'.
        """
        items: List[NewsItem] = []
        url = CRYPTOPANIC_BASE_URL
        params = {
            "auth_token": self.api_token,
            "currencies": currency,
            "kind": kind,
            "public": "true",
        }

        for _ in range(limit_pages):
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            for entry in data.get("results", []):
                votes = entry.get("votes", {})
                published_str = entry.get("published_at")
                published_ts = self._parse_timestamp(published_str)

                items.append(
                    NewsItem(
                        id=entry["id"],
                        title=entry.get("title", ""),
                        published_at=published_ts,
                        positive_votes=votes.get("positive", 0),
                        negative_votes=votes.get("negative", 0),
                        important_votes=votes.get("important", 0),
                        url=entry.get("url", ""),
                    )
                )

            next_url = data.get("next")
            if not next_url:
                break
            url = next_url
            params = {}  # 'next' url bevat de query al

        return items

    def compute_sentiment(self, currency: str, lookback_hours: float = 6.0) -> SentimentResult:
        """
        Haalt nieuws op en berekent een tijdsgewogen sentiment-score voor de currency.

        Score-logica per item:
          raw = (positive_votes - negative_votes) / max(1, positive_votes + negative_votes)
          weight = tijdsverval (exponentieel) * important_multiplier (indien van toepassing)

        Eindscore = gewogen gemiddelde van alle raw-scores, geclipt tussen -1 en +1.
        """
        raw_items = self.fetch_news(currency, kind="news", limit_pages=2)
        now = time.time()
        cutoff = now - lookback_hours * 3600

        relevant_items = [item for item in raw_items if item.published_at >= cutoff]

        if not relevant_items:
            return SentimentResult(currency=currency, score=0.0, news_velocity=0, items=[])

        weighted_sum = 0.0
        weight_total = 0.0

        for item in relevant_items:
            age_hours = max(0.0, (now - item.published_at) / 3600.0)
            decay = math.pow(0.5, age_hours / SENTIMENT_HALF_LIFE_HOURS)

            total_votes = item.positive_votes + item.negative_votes
            raw_score = (item.positive_votes - item.negative_votes) / max(1, total_votes)

            multiplier = IMPORTANT_NEWS_MULTIPLIER if item.important_votes > 0 else 1.0
            weight = decay * multiplier * max(1, total_votes)  # meer votes = meer gewicht

            weighted_sum += raw_score * weight
            weight_total += weight

        final_score = weighted_sum / weight_total if weight_total > 0 else 0.0
        final_score = max(-1.0, min(1.0, final_score))

        return SentimentResult(
            currency=currency,
            score=final_score,
            news_velocity=len(relevant_items),
            items=relevant_items,
        )

    @staticmethod
    def _parse_timestamp(iso_string: Optional[str]) -> float:
        if not iso_string:
            return time.time()
        try:
            # CryptoPanic geeft ISO 8601 met 'Z' terug, bijv. 2026-08-21T10:00:00Z
            struct_time = time.strptime(iso_string.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
            return struct_time.timestamp() if hasattr(struct_time, "timestamp") else time.mktime(struct_time)
        except (ValueError, TypeError):
            return time.time()


if __name__ == "__main__":
    # Snelle handmatige test — vervang door je eigen token
    import os

    token = os.environ.get("CRYPTOPANIC_API_TOKEN", "")
    if not token:
        print("Zet CRYPTOPANIC_API_TOKEN als env var om te testen.")
    else:
        client = CryptoPanicClient(token)
        btc_result = client.compute_sentiment("BTC")
        hbar_result = client.compute_sentiment("HBAR")
        print(f"BTC sentiment: {btc_result.score:.3f} (n={btc_result.news_velocity})")
        print(f"HBAR sentiment: {hbar_result.score:.3f} (n={hbar_result.news_velocity})")
