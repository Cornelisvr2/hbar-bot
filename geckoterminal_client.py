"""
geckoterminal_client.py

Haalt on-chain DEX-pooldata op via GeckoTerminal's gratis publieke API --
vult de databehoefte die we eerder identificeerden voor het kalibreren
van LP-parameters (cooldown, range-breedte) op basis van echte
poolactiviteit, i.p.v. alleen prijsdata.

LET OP: deze sandbox kan api.geckoterminal.com niet bereiken (niet op de
toegestane domeinenlijst). Draai dit script op je VPS, die heeft gewone
uitgaande internettoegang.

Geen API-key nodig voor de publieke endpoints (wel rate-limited, zie
GeckoTerminal's documentatie voor de actuele limieten).
"""

import time
import requests
from dataclasses import dataclass
from typing import List, Optional
from retry_utils import retry_with_backoff


GECKOTERMINAL_BASE_URL = "https://api.geckoterminal.com/api/v2"
HEDERA_NETWORK_ID = "hedera-hashgraph"

# Bevestigd via GeckoTerminal UI (22 aug 2026): actieve WHBAR/USDC V2-pool,
# $3.2M TVL, $2.7M 24u-volume. Zie config.py voor de bron.
DEFAULT_WHBAR_USDC_POOL_ADDRESS = "0xc5b707348da504e9be1bd4e21525459830e7b11d"


@dataclass
class PoolSnapshot:
    pool_address: str
    price_usd: float
    volume_24h_usd: float
    liquidity_usd: float
    transactions_24h: int
    buys_24h: int
    sells_24h: int
    volume_1h_usd: float = 0.0  # (8 sep 2026) voor de "nu"-variant van de Fees-APR


@dataclass
class OhlcvCandle:
    timestamp: int  # unix seconds
    open: float
    high: float
    low: float
    close: float
    volume: float


class GeckoTerminalClient:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()

    # Klasse-brede cache (1 sep 2026, na een gevonden 429-snelheids-
    # limiet-fout die het dashboard liet crashen bij gelijktijdige
    # aanvragen) -- GECEDEELD over ALLE instanties van deze klasse
    # (bot, dashboard, Telegram-rapport maken elk hun EIGEN instantie
    # aan, dus een instantie-eigen cache zou niet helpen). Korte
    # levensduur (15s) -- ruim voldoende om gelijktijdige aanvragen op
    # te vangen, zonder de bot's eigen, live handelsbeslissingen
    # merkbaar te vertragen (die draaien toch al op een ~60s-cyclus).
    _snapshot_cache: dict = {}
    _SNAPSHOT_CACHE_TTL_SECONDEN = 15

    @retry_with_backoff(max_retries=3, base_delay=2.0,
                          exceptions=(requests.exceptions.RequestException,))
    def get_pool_snapshot(self, pool_address: str = DEFAULT_WHBAR_USDC_POOL_ADDRESS) -> PoolSnapshot:
        """Actuele momentopname van een pool -- prijs, volume, liquiditeit.
        Retry-met-backoff (28 aug 2026): vangt incidentele 502's/verbroken
        verbindingen op, zonder dat elke transiente netwerkhapering meteen
        een Telegram-foutmelding oplevert."""
        nu = time.time()
        gecached = GeckoTerminalClient._snapshot_cache.get(pool_address)
        if gecached and (nu - gecached[0]) < GeckoTerminalClient._SNAPSHOT_CACHE_TTL_SECONDEN:
            return gecached[1]

        url = f"{GECKOTERMINAL_BASE_URL}/networks/{HEDERA_NETWORK_ID}/pools/{pool_address}"
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()["data"]["attributes"]

        snapshot = PoolSnapshot(
            pool_address=pool_address,
            price_usd=float(data.get("base_token_price_usd", 0)),
            volume_24h_usd=float(data.get("volume_usd", {}).get("h24", 0)),
            liquidity_usd=float(data.get("reserve_in_usd", 0)),
            volume_1h_usd=float(data.get("volume_usd", {}).get("h1", 0)),
            transactions_24h=int(data.get("transactions", {}).get("h24", {}).get("buys", 0))
            + int(data.get("transactions", {}).get("h24", {}).get("sells", 0)),
            buys_24h=int(data.get("transactions", {}).get("h24", {}).get("buys", 0)),
            sells_24h=int(data.get("transactions", {}).get("h24", {}).get("sells", 0)),
        )
        GeckoTerminalClient._snapshot_cache[pool_address] = (nu, snapshot)
        return snapshot

    _volume_7d_cache: dict = {}

    def get_avg_daily_volume_7d(self, pool_address: str = DEFAULT_WHBAR_USDC_POOL_ADDRESS) -> float:
        """(8 sep 2026) Gemiddeld dagvolume over de laatste 7 afgesloten dag-candles (1u cache)."""
        hit = self._volume_7d_cache.get(pool_address)
        if hit and time.time() - hit[0] < 3600:
            return hit[1]
        candles = self.get_historical_ohlcv(pool_address=pool_address, timeframe="day", limit=8)
        # GeckoTerminal geeft nieuwste eerst; de eerste is de lopende (onvolledige) dag
        closed = candles[1:8] if len(candles) > 1 else candles
        avg = sum(c.volume for c in closed) / len(closed) if closed else 0.0
        self._volume_7d_cache[pool_address] = (time.time(), avg)
        return avg

    def get_historical_ohlcv(
        self,
        pool_address: str = DEFAULT_WHBAR_USDC_POOL_ADDRESS,
        timeframe: str = "hour",  # 'day', 'hour', of 'minute'
        aggregate: int = 1,
        limit: int = 500,
        before_timestamp: Optional[int] = None,
    ) -> List[OhlcvCandle]:
        """
        Historische candles inclusief volume per candle -- dit is de
        tijdreeks die de eerdere momentopname mist, en die nodig is om
        de LP-cooldown/breedte daadwerkelijk te backtesten (zie
        PLAN.md, sectie "Dubbele rol van de bot").
        """
        url = (
            f"{GECKOTERMINAL_BASE_URL}/networks/{HEDERA_NETWORK_ID}/pools/"
            f"{pool_address}/ohlcv/{timeframe}"
        )
        params = {"aggregate": aggregate, "limit": limit}
        if before_timestamp:
            params["before_timestamp"] = before_timestamp

        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        raw_candles = resp.json()["data"]["attributes"]["ohlcv_list"]

        return [
            OhlcvCandle(
                timestamp=int(c[0]), open=float(c[1]), high=float(c[2]),
                low=float(c[3]), close=float(c[4]), volume=float(c[5]),
            )
            for c in raw_candles
        ]

    def fetch_full_history(
        self,
        pool_address: str = DEFAULT_WHBAR_USDC_POOL_ADDRESS,
        timeframe: str = "hour",
        total_candles_needed: int = 24 * 90,  # 90 dagen aan uur-candles
        pause_seconds: float = 1.0,
    ) -> List[OhlcvCandle]:
        """
        Haalt meer geschiedenis op dan één API-call toelaat, door
        achteruit in de tijd te pagineren via before_timestamp.
        Nuttig om een dataset op te bouwen voor de LP-parameter-backtest.
        """
        all_candles: List[OhlcvCandle] = []
        before_ts = None

        while len(all_candles) < total_candles_needed:
            batch = self.get_historical_ohlcv(
                pool_address, timeframe=timeframe, limit=500, before_timestamp=before_ts
            )
            if not batch:
                break
            all_candles.extend(batch)
            before_ts = batch[-1].timestamp
            time.sleep(pause_seconds)

        return all_candles[:total_candles_needed]


if __name__ == "__main__":
    client = GeckoTerminalClient()

    print("--- Actuele pool-snapshot ---")
    try:
        snapshot = client.get_pool_snapshot()
        print(f"Prijs: ${snapshot.price_usd:.5f}")
        print(f"24u volume: ${snapshot.volume_24h_usd:,.0f}")
        print(f"Liquiditeit: ${snapshot.liquidity_usd:,.0f}")
        print(f"24u transacties: {snapshot.transactions_24h} ({snapshot.buys_24h} buy / {snapshot.sells_24h} sell)")
    except requests.exceptions.RequestException as e:
        print(f"Kon GeckoTerminal niet bereiken vanuit deze omgeving: {e}")
        print("Draai dit script op je VPS voor een live test.")
