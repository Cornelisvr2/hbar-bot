"""
depeg_guard.py -- (8 sep 2026, op verzoek) USDC-depeg-noodstop.

Drie signalen; bij >= 2 gelijktijdig, twee metingen achter elkaar (>= 60 s
uit elkaar), gaat de noodstop af:
  1. SaucerSwap-API priceUsd van USDC (0.0.456858) < DEPEG_THRESHOLD (0,98)
  2. Externe USDC/USD (CoinGecko) < DEPEG_THRESHOLD
  3. Pool-implied: HBAR-prijs in USDC (onze pool, on-chain) wijkt meer dan
     DEPEG_POOL_DIVERGENCE (2%) af van HBAR/USDT op Binance -- het signaal
     dat ECHT telt, want het gaat om de USDC in onze pool.
Waarschuwing (alleen Telegram) zodra signaal 1 of 2 < DEPEG_WARN (0,995).

Actie bij noodstop (regime_orchestrator._execute_depeg_halt):
  positie sluiten (fees mee), alle USDC -> HBAR met ruimere slippage
  (DEPEG_SWAP_SLIPPAGE, 3%), en de bot in DEPEG_HALT: 100% HBAR, niets
  meer doen tot handmatig /resume. Bewust geen automatische herstart.
"""

import os
import time
from dataclasses import dataclass
from typing import Optional

DEPEG_THRESHOLD = float(os.environ.get("DEPEG_THRESHOLD", "0.98"))
DEPEG_WARN = float(os.environ.get("DEPEG_WARN", "0.995"))
DEPEG_POOL_DIVERGENCE = float(os.environ.get("DEPEG_POOL_DIVERGENCE", "0.02"))
DEPEG_CONFIRM_SECONDS = int(os.environ.get("DEPEG_CONFIRM_SECONDS", "60"))
DEPEG_SWAP_SLIPPAGE = float(os.environ.get("DEPEG_SWAP_SLIPPAGE", "0.03"))
DEPEG_ENABLED = os.environ.get("DEPEG_GUARD_ENABLED", "true").lower() in ("1", "true", "yes", "on")
USDC_TOKEN_ID = "0.0.456858"


@dataclass
class DepegReading:
    at: float
    saucerswap_usdc_usd: Optional[float]
    coingecko_usdc_usd: Optional[float]
    pool_hbar_usdc: Optional[float]
    binance_hbar_usdt: Optional[float]
    signals: list
    is_warning: bool

    @property
    def divergence(self) -> Optional[float]:
        if self.pool_hbar_usdc and self.binance_hbar_usdt:
            return self.pool_hbar_usdc / self.binance_hbar_usdt - 1
        return None

    def summary(self) -> str:
        div = self.divergence
        return (f"SaucerSwap USDC={self.saucerswap_usdc_usd if self.saucerswap_usdc_usd is not None else 'n/b'} | "
                f"CoinGecko USDC={self.coingecko_usdc_usd if self.coingecko_usdc_usd is not None else 'n/b'} | "
                f"pool HBAR/USDC={self.pool_hbar_usdc:.5f} vs Binance {self.binance_hbar_usdt:.5f} "
                f"({div*100:+.2f}%)" if div is not None else
                f"SaucerSwap USDC={self.saucerswap_usdc_usd} | CoinGecko USDC={self.coingecko_usdc_usd} | pool-divergentie n/b")


class DepegGuard:
    def __init__(self):
        self._pending_since: Optional[float] = None
        self._pending_signals: list = []
        self._last_warn_at = 0.0
        self.last_reading: Optional[DepegReading] = None

    # ------------------------------------------------------------ bronnen
    @staticmethod
    def _saucerswap_usdc() -> Optional[float]:
        import requests
        try:
            r = requests.get(f"https://api.saucerswap.finance/tokens/{USDC_TOKEN_ID}", timeout=10)
            r.raise_for_status()
            return float(r.json().get("priceUsd"))
        except Exception:
            return None

    @staticmethod
    def _coingecko_usdc() -> Optional[float]:
        import requests
        try:
            r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                             params={"ids": "usd-coin", "vs_currencies": "usd"}, timeout=10)
            r.raise_for_status()
            return float(r.json()["usd-coin"]["usd"])
        except Exception:
            return None

    # ------------------------------------------------------------- check
    def check(self, pool_hbar_usdc: Optional[float], binance_hbar_usdt: Optional[float]) -> tuple:
        """
        Geeft (halt: bool, reading) terug. halt=True alleen na bevestiging
        (>= 2 signalen, twee metingen >= DEPEG_CONFIRM_SECONDS uit elkaar).
        """
        if not DEPEG_ENABLED:
            return False, None
        ss = self._saucerswap_usdc()
        cg = self._coingecko_usdc()
        signals = []
        if ss is not None and ss < DEPEG_THRESHOLD:
            signals.append("saucerswap")
        if cg is not None and cg < DEPEG_THRESHOLD:
            signals.append("coingecko")
        if pool_hbar_usdc and binance_hbar_usdt:
            if abs(pool_hbar_usdc / binance_hbar_usdt - 1) > DEPEG_POOL_DIVERGENCE:
                signals.append("pool_divergence")
        warn = any(p is not None and p < DEPEG_WARN for p in (ss, cg))
        reading = DepegReading(time.time(), ss, cg, pool_hbar_usdc, binance_hbar_usdt, signals, warn)
        self.last_reading = reading

        if len(signals) >= 2:
            if self._pending_since is None:
                self._pending_since = reading.at
                self._pending_signals = signals
                return False, reading
            if reading.at - self._pending_since >= DEPEG_CONFIRM_SECONDS:
                return True, reading
            return False, reading
        self._pending_since = None
        self._pending_signals = []
        return False, reading

    def should_warn(self, reading: DepegReading) -> bool:
        if not reading.is_warning:
            return False
        if time.time() - self._last_warn_at < 3600:
            return False
        self._last_warn_at = time.time()
        return True
