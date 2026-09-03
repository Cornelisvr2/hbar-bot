"""
coingecko_client.py

Haalt historische prijsdata op van CoinGecko voor BTC en HBAR, en berekent
een rolling correlatie en beta (hoe heftig HBAR reageert op BTC-bewegingen).
Deze waarde vervangt de statische `hbar_btc_beta` in strategy_engine.py
door een waarde die zich aanpast aan het actuele marktregime.

CoinGecko public API docs: https://www.coingecko.com/en/api/documentation
Gratis tier: geen API-key verplicht, wel rate-limited (~10-30 calls/min).
Voor productiegebruik raad ik een (gratis) Demo API-key aan via
https://www.coingecko.com/en/developers/dashboard voor hogere limieten.
"""

import time
import statistics
import requests
from dataclasses import dataclass
from typing import List, Tuple, Optional


COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

# CoinGecko coin-id's (niet de ticker-symbolen)
COINGECKO_ID_BTC = "bitcoin"
COINGECKO_ID_HBAR = "hedera-hashgraph"


@dataclass
class BetaResult:
    window_days: int
    beta: float           # hoe heftig HBAR beweegt t.o.v. BTC (1.0 = gelijke tred)
    correlation: float    # -1.0 tot +1.0, hoe sterk de bewegingen samenhangen
    sample_size: int


class CoinGeckoClient:
    def __init__(self, api_key: Optional[str] = None, session: Optional[requests.Session] = None):
        # api_key is optioneel; zonder key gebruik je de publieke, sterker
        # rate-limited endpoints. Met een gratis Demo-key voeg je hem toe
        # als header x-cg-demo-api-key.
        self.api_key = api_key
        self.session = session or requests.Session()

    def fetch_daily_prices(self, coin_id: str, days: int) -> List[Tuple[float, float]]:
        """
        Geeft een lijst van (timestamp, price) terug, dagelijkse resolutie.
        CoinGecko's market_chart endpoint geeft automatisch dagelijkse
        datapunten terug wanneer days > 90.
        """
        url = f"{COINGECKO_BASE_URL}/coins/{coin_id}/market_chart"
        params = {"vs_currency": "usd", "days": str(days), "interval": "daily"}
        headers = {}
        if self.api_key:
            headers["x-cg-demo-api-key"] = self.api_key

        resp = self.session.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        return [(point[0] / 1000.0, point[1]) for point in data.get("prices", [])]

    @staticmethod
    def _daily_returns(prices: List[float]) -> List[float]:
        returns = []
        for i in range(1, len(prices)):
            prev, curr = prices[i - 1], prices[i]
            if prev > 0:
                returns.append((curr - prev) / prev)
        return returns

    def compute_beta(self, window_days: int = 90) -> BetaResult:
        """
        Berekent beta en correlatie tussen HBAR- en BTC-dagrendementen
        over de opgegeven periode.

        beta = covariantie(hbar_returns, btc_returns) / variantie(btc_returns)
        Een beta van 1.5 betekent: als BTC 1% beweegt, beweegt HBAR
        gemiddeld 1.5% in dezelfde richting.
        """
        btc_series = self.fetch_daily_prices(COINGECKO_ID_BTC, window_days)
        # Kleine pauze om CoinGecko's rate limit niet te raken bij twee
        # calls kort na elkaar.
        time.sleep(1.5)
        hbar_series = self.fetch_daily_prices(COINGECKO_ID_HBAR, window_days)

        btc_prices = [p for _, p in btc_series]
        hbar_prices = [p for _, p in hbar_series]

        # Zorg dat beide reeksen even lang zijn (CoinGecko kan soms 1 extra
        # datapunt geven per coin).
        min_len = min(len(btc_prices), len(hbar_prices))
        btc_prices = btc_prices[-min_len:]
        hbar_prices = hbar_prices[-min_len:]

        btc_returns = self._daily_returns(btc_prices)
        hbar_returns = self._daily_returns(hbar_prices)

        n = min(len(btc_returns), len(hbar_returns))
        btc_returns = btc_returns[-n:]
        hbar_returns = hbar_returns[-n:]

        if n < 5:
            # Te weinig data voor een betrouwbare berekening; val terug op
            # een neutrale aanname.
            return BetaResult(window_days=window_days, beta=1.0, correlation=0.0, sample_size=n)

        beta, correlation = self._beta_and_correlation(hbar_returns, btc_returns)

        return BetaResult(
            window_days=window_days,
            beta=round(beta, 3),
            correlation=round(correlation, 3),
            sample_size=n,
        )

    @staticmethod
    def _beta_and_correlation(y: List[float], x: List[float]) -> Tuple[float, float]:
        mean_x = statistics.mean(x)
        mean_y = statistics.mean(y)

        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / len(x)
        var_x = statistics.pvariance(x)

        beta = cov / var_x if var_x > 0 else 1.0

        std_x = statistics.pstdev(x)
        std_y = statistics.pstdev(y)
        correlation = cov / (std_x * std_y) if std_x > 0 and std_y > 0 else 0.0

        return beta, correlation


class BetaCalculator:
    """
    Wrapper met caching, zodat de strategy_engine niet bij elke evaluatie
    een nieuwe CoinGecko-call hoeft te doen. Beta verandert traag genoeg
    dat 1x per dag herberekenen ruim voldoende is.
    """

    def __init__(self, client: CoinGeckoClient, refresh_interval_hours: float = 24.0,
                 window_days: int = 90):
        self.client = client
        self.refresh_interval_seconds = refresh_interval_hours * 3600
        self.window_days = window_days
        self._cached_result: Optional[BetaResult] = None
        self._last_fetch_time: float = 0.0

    def get_beta(self) -> BetaResult:
        now = time.time()
        if self._cached_result is None or (now - self._last_fetch_time) > self.refresh_interval_seconds:
            self._cached_result = self.client.compute_beta(self.window_days)
            self._last_fetch_time = now
        return self._cached_result


if __name__ == "__main__":
    import os

    api_key = os.environ.get("COINGECKO_API_KEY")  # optioneel
    client = CoinGeckoClient(api_key=api_key)

    for window in (30, 90, 365):
        result = client.compute_beta(window_days=window)
        print(
            f"Window {window}d: beta={result.beta:.3f}, "
            f"correlatie={result.correlation:.3f}, n={result.sample_size}"
        )
        time.sleep(2)  # ruimte tussen windows i.v.m. rate limits
