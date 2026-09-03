"""
binance_klines_client.py

Haalt historische OHLCV-candles op via Binance's gratis, publieke
klines-API (geen key nodig) -- dit is de databron voor
backtest_pipeline.py's price_lookup_fn, aangezien we minuut-precisie
nodig hebben voor get_price_strictly_at_or_before() (zie eerdere
discussie: CoinGecko's gratis tier geeft voor oudere data alleen
dag-niveau, te grof voor deze toepassing).

We handelen op SaucerSwap (Hedera), maar gebruiken Binance puur als
prijs-REFERENTIE voor het terugtoetsen -- via arbitrage blijft de
HBAR/USDT-koers op Binance nauw gekoppeld aan wat je op SaucerSwap zou
zien.
"""

import time
import requests
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple


BINANCE_BASE_URL = "https://api.binance.com/api/v3"

SYMBOL_BY_ASSET = {
    "BTC": "BTCUSDT",
    "HBAR": "HBARUSDT",
}


@dataclass
class Kline:
    open_time: float  # unix seconds
    open: float
    high: float
    low: float
    close: float
    volume: float


class BinanceKlinesClient:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()

    def get_klines(self, asset: str, interval: str = "1m",
                    start_time: Optional[float] = None,
                    end_time: Optional[float] = None,
                    limit: int = 1000) -> List[Kline]:
        """
        interval: '1m', '5m', '15m', '1h', '1d', etc. (Binance-notatie)
        start_time/end_time: unix seconds (worden hier naar ms omgezet)
        """
        symbol = SYMBOL_BY_ASSET.get(asset)
        if symbol is None:
            raise ValueError(f"Onbekend asset: {asset}")

        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time:
            params["startTime"] = int(start_time * 1000)
        if end_time:
            params["endTime"] = int(end_time * 1000)

        resp = self.session.get(f"{BINANCE_BASE_URL}/klines", params=params, timeout=15)
        resp.raise_for_status()
        raw = resp.json()

        return [
            Kline(
                open_time=k[0] / 1000.0, open=float(k[1]), high=float(k[2]),
                low=float(k[3]), close=float(k[4]), volume=float(k[5]),
            )
            for k in raw
        ]

    def fetch_range(self, asset: str, start_time: float, end_time: float,
                     interval: str = "1m", pause_seconds: float = 0.3) -> List[Kline]:
        """
        Haalt een heel tijdvak op, ook als dat meer dan 1000 candles omvat
        (Binance's limiet per call), door te pagineren.
        """
        all_klines: List[Kline] = []
        current_start = start_time

        while current_start < end_time:
            batch = self.get_klines(asset, interval=interval,
                                     start_time=current_start, end_time=end_time, limit=1000)
            if not batch:
                break
            all_klines.extend(batch)
            current_start = batch[-1].open_time + 1
            time.sleep(pause_seconds)

        return all_klines

    def build_price_lookup_fn(self, asset: str, klines: List[Kline]):
        """
        Bouwt een functie met de exacte signatuur die
        get_price_strictly_at_or_before() in backtest_pipeline.py
        verwacht: (asset, timestamp) -> (price, candle_timestamp) | None.

        Haalt eerst alle relevante candles op (via fetch_range) en zoekt
        daarna lokaal -- veel efficienter dan per nieuwsbericht een losse
        API-call te doen.
        """
        sorted_klines = sorted(klines, key=lambda k: k.open_time)

        def lookup(lookup_asset: str, timestamp: datetime):
            target_ts = timestamp.timestamp()
            # Zoek de laatste candle op of voor het gevraagde moment
            candidate = None
            for k in sorted_klines:
                if k.open_time <= target_ts:
                    candidate = k
                else:
                    break
            if candidate is None:
                return None
            return (candidate.close, datetime.fromtimestamp(candidate.open_time))

        return lookup


if __name__ == "__main__":
    client = BinanceKlinesClient()

    try:
        recent = client.get_klines("HBAR", interval="1h", limit=5)
        print(f"{len(recent)} recente HBAR-candles opgehaald")
        for k in recent:
            print(f"  {datetime.fromtimestamp(k.open_time)}: close={k.close}")
    except requests.exceptions.RequestException as e:
        print(f"Kon Binance niet bereiken vanuit deze omgeving: {e}")
        print("Draai dit script op je VPS voor een live test.")
