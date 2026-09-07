"""
sauce_reinvest.py -- (7 sep 2026, op verzoek) Herinvesteren van SAUCE die
via LARI-airdrops binnenkomt.

Ontwerp (afgesproken):
- Standaard UIT (SAUCE_REINVEST_ENABLED=false). LARI-SAUCE wordt NOOIT
  automatisch geswapt zonder deze expliciete instelling.
- Alleen in LP_MODE. Drie voorwaarden, alle drie waar:
    1. SAUCE-waarde >= SAUCE_REINVEST_MIN_USD (default 10) -- gas van
       swap + HTS-approve (~1 HBAR) blijft dan < 1%.
    2. SAUCE/HBAR-koers op of boven het 7-daags gemiddelde
       (SAUCE_REINVEST_MA_DAYS) -- nooit in een dip verkopen.
    3. ... OF het saldo ligt er al >= SAUCE_REINVEST_MAX_HOLD_DAYS (30):
       dan swappen ongeacht de koers, zodat SAUCE nooit onbeperkt blijft
       liggen.
- Swap SAUCE -> HBAR. Daarna doet het bestaande mechanisme de rest:
  reserve blijft staan, bijstorten pas boven MIN_DEPLOYABLE_CAPITAL_HBAR.
- Handmatig forceren via Telegram: /swapsauce.

Koersen: SAUCE/USD en HBAR/USD via GeckoTerminal (dag-candles van de
SAUCE/WHBAR- en WHBAR/USDC-pool), verhouding = SAUCE in HBAR.
Toestand (wanneer SAUCE voor het eerst gezien is) staat in een klein
JSON-bestand op de gedeelde ./logs-map, zodat het herstarts overleeft.
"""

import json
import os
import time
from dataclasses import dataclass
from typing import Optional

SAUCE_TOKEN_EVM = "0x00000000000000000000000000000000000b2ad5"  # 0.0.731861
SAUCE_DECIMALS = 6

STATE_FILE = os.environ.get("SAUCE_REINVEST_STATE_FILE", "/app/logs/sauce_reinvest_state.json")


def _cfg_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class SauceReinvestConfig:
    enabled: bool = _cfg_bool("SAUCE_REINVEST_ENABLED", False)
    min_usd: float = float(os.environ.get("SAUCE_REINVEST_MIN_USD", "10"))
    ma_days: int = int(os.environ.get("SAUCE_REINVEST_MA_DAYS", "7"))
    max_hold_days: int = int(os.environ.get("SAUCE_REINVEST_MAX_HOLD_DAYS", "30"))
    check_interval_seconds: int = int(os.environ.get("SAUCE_REINVEST_CHECK_SECONDS", "3600"))


@dataclass
class SauceDecision:
    sauce_balance: float
    sauce_price_usd: float
    value_usd: float
    sauce_in_hbar: Optional[float]
    ma_in_hbar: Optional[float]
    held_days: float
    should_swap: bool
    reason: str


class SauceReinvestor:
    def __init__(self, rpc_client, gecko, config: Optional[SauceReinvestConfig] = None):
        self.rpc = rpc_client
        self.gecko = gecko
        self.cfg = config or SauceReinvestConfig()
        self._last_check_at = 0.0
        self._state = self._load_state()

    # ------------------------------------------------------------------ state
    def _load_state(self) -> dict:
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(self._state, f)
        except Exception:
            pass

    # --------------------------------------------------------------- reads
    def sauce_balance(self) -> float:
        from swap_executor import ERC20_ABI
        c = self.rpc.w3.eth.contract(address=SAUCE_TOKEN_EVM, abi=ERC20_ABI)
        return c.functions.balanceOf(self.rpc.address).call() / (10 ** SAUCE_DECIMALS)

    def _sauce_pool_address(self) -> Optional[str]:
        """SAUCE/WHBAR-pool met de meeste liquiditeit (fee-tier 1500/3000/500)."""
        from config import resolve_mainnet_v2_addresses, resolve_mainnet_addresses
        v2 = resolve_mainnet_v2_addresses()
        base = resolve_mainnet_addresses()
        factory_abi = [{"name": "getPool", "type": "function", "stateMutability": "view",
                        "inputs": [{"name": "a", "type": "address"}, {"name": "b", "type": "address"},
                                   {"name": "fee", "type": "uint24"}],
                        "outputs": [{"name": "pool", "type": "address"}]}]
        liq_abi = [{"name": "liquidity", "type": "function", "stateMutability": "view",
                    "inputs": [], "outputs": [{"name": "", "type": "uint128"}]}]
        factory = self.rpc.w3.eth.contract(address=v2.factory, abi=factory_abi)
        best, best_liq, best_fee = None, -1, None
        for fee in (1500, 3000, 500):
            addr = factory.functions.getPool(SAUCE_TOKEN_EVM, base.whbar_token, fee).call()
            if int(addr, 16) == 0:
                continue
            liq = self.rpc.w3.eth.contract(address=addr, abi=liq_abi).functions.liquidity().call()
            if liq > best_liq:
                best, best_liq, best_fee = addr, liq, fee
        self._sauce_fee_tier = best_fee
        return best

    def _price_series_in_hbar(self, days: int) -> tuple[Optional[float], Optional[float]]:
        """(huidige SAUCE-in-HBAR, gemiddelde over `days` dagen) via GeckoTerminal."""
        from pool_range_analysis import fetch_sauce_price_usd
        pool = self._sauce_pool_address()
        if not pool:
            return None, None
        sauce_candles = self.gecko.get_historical_ohlcv(pool_address=pool, timeframe="day", limit=days + 1)
        hbar_candles = self.gecko.get_historical_ohlcv(timeframe="day", limit=days + 1)
        hbar_by_day = {c.timestamp // 86400: c.close for c in hbar_candles}
        ratios = []
        for c in sauce_candles[:days]:
            h = hbar_by_day.get(c.timestamp // 86400)
            if h and h > 0:
                ratios.append(c.close / h)
        if not ratios:
            return None, None
        current = fetch_sauce_price_usd() / self.gecko.get_pool_snapshot().price_usd
        return current, sum(ratios) / len(ratios)

    # ------------------------------------------------------------- decide
    def evaluate(self, force: bool = False) -> SauceDecision:
        from pool_range_analysis import fetch_sauce_price_usd
        bal = self.sauce_balance()
        price = fetch_sauce_price_usd() if bal > 0 else 0.0
        value = bal * price

        if bal <= 0:
            self._state.pop("first_seen_at", None)
            self._save_state()
            return SauceDecision(bal, price, value, None, None, 0.0, False, "geen SAUCE in wallet")

        if "first_seen_at" not in self._state:
            self._state["first_seen_at"] = time.time()
            self._save_state()
        held_days = (time.time() - self._state["first_seen_at"]) / 86400

        if force:
            return SauceDecision(bal, price, value, None, None, held_days, True, "handmatig geforceerd (/swapsauce)")
        if value < self.cfg.min_usd:
            return SauceDecision(bal, price, value, None, None, held_days, False,
                                 f"waarde ${value:.2f} < drempel ${self.cfg.min_usd:.2f}")
        if held_days >= self.cfg.max_hold_days:
            return SauceDecision(bal, price, value, None, None, held_days, True,
                                 f"maximale wachttijd bereikt ({held_days:.0f} dagen)")
        try:
            cur, ma = self._price_series_in_hbar(self.cfg.ma_days)
        except Exception as e:
            return SauceDecision(bal, price, value, None, None, held_days, False, f"koershistorie niet beschikbaar: {str(e)[:80]}")
        if cur is None or ma is None:
            return SauceDecision(bal, price, value, cur, ma, held_days, False, "koershistorie leeg")
        if cur >= ma:
            return SauceDecision(bal, price, value, cur, ma, held_days, True,
                                 f"SAUCE/HBAR {cur:.4f} >= {self.cfg.ma_days}d-gemiddelde {ma:.4f}")
        return SauceDecision(bal, price, value, cur, ma, held_days, False,
                             f"SAUCE/HBAR {cur:.4f} < {self.cfg.ma_days}d-gemiddelde {ma:.4f} -- wachten")

    # ------------------------------------------------------------ execute
    def swap_all_to_hbar(self) -> Optional[str]:
        """SAUCE -> WHBAR -> HBAR via SwapExecutorV2's generieke token-pad."""
        from swap_executor_v2 import SwapExecutorV2, build_swap_config_v2
        from config import HEDERA_NETWORK
        bal = self.sauce_balance()
        if bal <= 0:
            return None
        pool = self._sauce_pool_address()
        if not pool:
            raise RuntimeError("Geen SAUCE/WHBAR-pool gevonden")
        cfg = build_swap_config_v2(HEDERA_NETWORK, fee_tier=self._sauce_fee_tier)
        ex = SwapExecutorV2(self.rpc, cfg)
        res = ex.swap_token_to_hbar(SAUCE_TOKEN_EVM, SAUCE_DECIMALS, bal, self._sauce_fee_tier)
        if res.status == "success":
            self._state.pop("first_seen_at", None)
            self._state["last_swap"] = {"at": time.time(), "sauce": bal, "tx": res.tx_hash}
            self._save_state()
        return res.tx_hash

    # ---------------------------------------------------------- orchestr.
    async def maybe_run(self, in_lp_mode: bool, force: bool = False) -> Optional[SauceDecision]:
        """Aan te roepen vanuit de hoofdlus; doet hoogstens elk uur iets."""
        now = time.time()
        if not force:
            if not self.cfg.enabled or not in_lp_mode:
                return None
            if now - self._last_check_at < self.cfg.check_interval_seconds:
                return None
        self._last_check_at = now
        d = self.evaluate(force=force)
        if d.sauce_balance > 0:
            print(f"[sauce] {d.sauce_balance:.2f} SAUCE (${d.value_usd:.2f}), {d.held_days:.1f}d in wallet -- "
                  f"{'SWAP' if d.should_swap else 'wachten'}: {d.reason}")
        if not d.should_swap:
            return d
        import telegram_notify
        try:
            tx = self.swap_all_to_hbar()
            telegram_notify.send_telegram_message(
                f"LARI-SAUCE herinvesteerd: {d.sauce_balance:.2f} SAUCE (${d.value_usd:.2f}) -> HBAR. "
                f"Reden: {d.reason}. tx: {tx}")
        except Exception as e:
            telegram_notify.report_error("sauce_reinvest", f"SAUCE-swap mislukt: {str(e)[:300]}")
        return d
