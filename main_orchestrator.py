"""
main_orchestrator.py

Centrale regellus. Start twee VOLLEDIG ONAFHANKELIJKE asyncio-taken:

1. TradingOrchestrator -- pollt nieuws/sentiment, beslist via
   strategy_engine + safety_override + risk_manager, voert swaps uit
   met eigen, onafhankelijk geconfigureerd kapitaal.
2. LpOrchestrator -- pollt prijs/volatiliteit/sentiment, beheert de
   LP-positie via lp_manager.py met zijn eigen, apart geconfigureerde
   kapitaal.

Nieuwsbron: RssNewsClient i.p.v. CryptoPanicClient (CryptoPanic heeft
geen bruikbare gratis tier meer en blokkeert VPS-IP's via Cloudflare).

Start met DRY_RUN=true (default) -- logt wat er zou gebeuren zonder
daadwerkelijk te swappen of LP-posities te openen.
"""

import asyncio
import os
import time
import subprocess
from typing import Optional

from rss_news_client import RssNewsClient
from llm_sentiment_engine import LlmSentimentEngine
from coingecko_client import CoinGeckoClient, BetaCalculator
from geckoterminal_client import GeckoTerminalClient
from strategy_engine import StrategyEngine, Direction
from safety_override import apply_panic_safety_check
from risk_manager import RiskManager, RiskConfig
from position_planner import build_position_plan, TrailingStopTracker
from lp_manager import LpManager, LpPositionConfig, VolatilityRegime, compute_volatility_regime
from hedera_rpc_client import HederaRpcClient, NetworkConfig
from postgres_client import PostgresClient
import telegram_notify
from config import (
    HEDERA_NETWORK, NETWORK_SETTINGS,
    resolve_testnet_addresses, resolve_mainnet_addresses,
    resolve_testnet_v2_addresses, resolve_mainnet_v2_addresses,
)


TRADING_POLL_INTERVAL_SECONDS = 5 * 60
LP_POLL_INTERVAL_SECONDS = 60
POSITION_MONITOR_INTERVAL_SECONDS = 60  # zelfde cadans als de LP-loop
LP_SENTIMENT_REFRESH_SECONDS = 5 * 60
LP_VOLATILITY_REFRESH_SECONDS = 60 * 60  # 1x per uur, niet elke cyclus

DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"


class TradingOrchestrator:
    """Onafhankelijk proces 1: directioneel traden op sentiment."""

    def __init__(self, db):
        self.db = db
        self.rss_news = RssNewsClient()
        self.llm = LlmSentimentEngine()
        self.geckoterminal = GeckoTerminalClient()
        coingecko = CoinGeckoClient(api_key=os.environ.get("COINGECKO_API_KEY"))
        self.beta_calculator = BetaCalculator(coingecko)
        self.strategy = StrategyEngine(beta_calculator=self.beta_calculator)
        self.risk_manager = RiskManager(RiskConfig(
            trading_capital_usdc=float(os.environ.get("TRADING_CAPITAL_USDC", "1000")),
        ))
        self.latest_btc_score = 0.0
        self.latest_hbar_score = 0.0

    async def run_forever(self):
        while True:
            try:
                await self._cycle()
            except Exception as e:
                import traceback
                print(f"FOUT in trading_loop: {e}")
                traceback.print_exc()
                telegram_notify.report_error("trading_loop", str(e))
            await asyncio.sleep(TRADING_POLL_INTERVAL_SECONDS)

    async def _update_sentiment_for_asset(self, asset: str) -> Optional[str]:
        items = self.rss_news.fetch_news(asset, max_age_hours=4.0)
        new_items = [i for i in items if not self.risk_manager.is_news_already_processed(i.id)]
        if not new_items:
            return None
        results = [self.llm.analyze_headline(asset, item.title) for item in new_items]
        published_timestamps = [item.published_at for item in new_items]
        aggregated_score = LlmSentimentEngine.aggregate_with_decay(results, published_timestamps)
        for item, result in zip(new_items, results):
            await self.db.log_sentiment(
                asset=asset, headline=item.title,
                sentiment_score=result.sentiment_score,
                confidence=result.confidence,
                is_idiosyncratic=result.is_idiosyncratic,
                rationale=result.rationale, source="llm",
            )
            self.risk_manager.mark_news_processed(item.id)
        if asset == "BTC":
            self.latest_btc_score = aggregated_score
        else:
            self.latest_hbar_score = aggregated_score
        return new_items[0].id

    async def _cycle(self):
        btc_news_id = await self._update_sentiment_for_asset("BTC")
        hbar_news_id = await self._update_sentiment_for_asset("HBAR")
        news_id = hbar_news_id or btc_news_id
        btc_score = self.latest_btc_score
        hbar_score = self.latest_hbar_score

        signal = self.strategy.evaluate(btc_score, hbar_score)
        signal = apply_panic_safety_check(signal, btc_score, hbar_score)
        signal = self.risk_manager.evaluate_trading_signal(signal, news_id=news_id)

        signal_id = await self.db.log_strategy_signal(
            direction=signal.direction.value, confidence=signal.confidence,
            position_fraction=signal.position_fraction,
            btc_score=btc_score, hbar_score=hbar_score,
            panic_override_triggered="PANIEK-OVERRIDE" in signal.reasoning,
            reasoning=signal.reasoning,
        )

        if signal.direction == Direction.HOLD:
            print(f"[cyclus] HOLD -- btc_score={btc_score:.2f}, hbar_score={hbar_score:.2f}, reden={signal.reasoning}")
            return

        # Positie-check: voorkomt dat de bot 10x bijkoopt op hetzelfde
        # langlopende nieuwsbericht (Gemini-feedback, 23 aug 2026) --
        # bij een reeds open positie wordt een nieuw BUY-signaal genegeerd.
        # De positie-monitor-loop (PositionMonitorOrchestrator) bewaakt de
        # exit via stop-loss/trailing-stop, niet deze cyclus.
        open_positions = await self.db.get_open_positions()
        if signal.direction == Direction.BUY and open_positions:
            print(f"[cyclus] BUY-signaal genegeerd -- al {len(open_positions)} "
                  f"open positie(s), voorkomt stapelen.")
            return

        # Live prijs via GeckoTerminal i.p.v. placeholder.
        try:
            current_price = self.geckoterminal.get_pool_snapshot().price_usd
        except Exception as e:
            print(f"[cyclus] Kon geen live prijs ophalen, sla deze cyclus over: {e}")
            return

        capital = self.risk_manager.max_trading_position_usdc()
        plan = build_position_plan(signal, current_price, total_capital_usdc=capital)
        if plan is None:
            return

        direction = "USDC_TO_HBAR" if plan.direction == "BUY" else "HBAR_TO_USDC"
        amount = plan.usdc_amount if plan.direction == "BUY" else plan.quantity_hbar

        if DRY_RUN:
            print(f"[DRY RUN] Zou traden: {direction}, bedrag={amount:.4f}, prijs={current_price:.5f}, reden={signal.reasoning}")
            return

        with self.risk_manager.acquire_execution_lock():
            result = subprocess.run(
                ["python3", "execute_hbar_swap_standalone.py",
                 "--direction", direction, "--amount", str(amount),
                 "--network", HEDERA_NETWORK, "--engine", "v2"],
                capture_output=True, text=True,
            )

        status = "success" if result.returncode == 0 else "failed"
        self.risk_manager.record_trade_executed(news_id=news_id)

        trade_id = await self.db.log_trade(
            direction=direction, engine="v2", network=HEDERA_NETWORK,
            amount_in=amount, estimated_amount_out=plan.position_value_usdc,
            actual_amount_out=None, tx_hash=None, status=status,
            strategy_signal_id=signal_id,
        )

        # Positie registreren zodat PositionMonitorOrchestrator 'm kan
        # bewaken op stop-loss/trailing-stop -- dit was het ontbrekende
        # stuk dat Gemini terecht signaleerde.
        if status == "success" and plan.direction == "BUY":
            await self.db.open_position(
                entry_price=current_price,
                initial_stop_loss=plan.initial_stop_loss,
                trailing_distance_pct=plan.trailing_distance_pct,
                quantity_hbar=plan.quantity_hbar,
                trade_id=trade_id,
            )

        telegram_notify.report_trade(
            direction=direction, engine="v2", network=HEDERA_NETWORK,
            amount_in=amount, estimated_out=plan.position_value_usdc, status=status,
        )


class PositionMonitorOrchestrator:
    """
    Onafhankelijk proces 3: bewaakt open directionele posities op
    stop-loss/trailing-stop. Ontbrak eerder volledig -- TrailingStopTracker
    en de open_positions-tabel bestonden al, maar niets koppelde ze aan
    elkaar in de live loop (Gemini-feedback, 23 aug 2026).
    """

    def __init__(self, db):
        self.db = db
        self.geckoterminal = GeckoTerminalClient()

    async def run_forever(self):
        while True:
            try:
                await self._cycle()
            except Exception as e:
                import traceback
                print(f"FOUT in position_monitor_loop: {e}")
                traceback.print_exc()
                telegram_notify.report_error("position_monitor_loop", str(e))
            await asyncio.sleep(POSITION_MONITOR_INTERVAL_SECONDS)

    async def _cycle(self):
        positions = await self.db.get_open_positions()
        if not positions:
            return

        try:
            current_price = self.geckoterminal.get_pool_snapshot().price_usd
        except Exception as e:
            telegram_notify.report_error("position_monitor_loop: prijs ophalen", str(e))
            return

        for pos in positions:
            tracker = TrailingStopTracker(
                entry_price=pos["entry_price"],
                trailing_distance_pct=pos["trailing_distance_pct"] or 0.05,
                initial_stop_loss=pos["initial_stop_loss"],
            )
            # Hydrateer met de al bekende hoogste prijs, zodat een herstart
            # van de bot geen eerder bereikte piek "vergeet".
            tracker.highest_price = max(pos["highest_price_seen"], current_price)

            exit_triggered = tracker.should_exit(current_price)
            await self.db.update_highest_price(pos["id"], tracker.highest_price)

            unrealized_pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"] * 100

            if not exit_triggered:
                print(f"[position_monitor] Positie {pos['id']}: prijs={current_price:.5f}, "
                      f"PnL={unrealized_pnl_pct:+.2f}%, stop={tracker.update(current_price):.5f}")
                continue

            print(f"[position_monitor] EXIT getriggerd voor positie {pos['id']}: "
                  f"prijs={current_price:.5f} <= stop, PnL={unrealized_pnl_pct:+.2f}%")

            if DRY_RUN:
                print(f"[DRY RUN] Zou positie {pos['id']} sluiten (HBAR_TO_USDC, "
                      f"{pos['quantity_hbar']:.4f} HBAR)")
                continue

            result = subprocess.run(
                ["python3", "execute_hbar_swap_standalone.py",
                 "--direction", "HBAR_TO_USDC", "--amount", str(pos["quantity_hbar"]),
                 "--network", HEDERA_NETWORK, "--engine", "v2"],
                capture_output=True, text=True,
            )
            status = "success" if result.returncode == 0 else "failed"

            if status == "success":
                await self.db.close_position(pos["id"])

            telegram_notify.report_trade(
                direction="HBAR_TO_USDC", engine="v2", network=HEDERA_NETWORK,
                amount_in=pos["quantity_hbar"], estimated_out=pos["quantity_hbar"] * current_price,
                status=status,
            )
            if status != "success":
                telegram_notify.report_error(
                    "position_monitor_loop",
                    f"Exit-swap mislukt voor positie {pos['id']} -- positie blijft open, handmatige actie nodig.",
                )


class LpOrchestrator:
    """Onafhankelijk proces 2: LP-beheer, eigen kapitaal, eigen cadans."""

    def __init__(self, db):
        self.db = db
        self.geckoterminal = GeckoTerminalClient()
        self.rss_news = RssNewsClient()
        self.llm = LlmSentimentEngine()
        self._cached_hbar_sentiment = 0.0
        self._last_sentiment_refresh = 0.0
        self._processed_news_ids: set = set()

        self._cached_volatility_regime = VolatilityRegime.NORMAL
        self._last_volatility_refresh = 0.0

        # Circuit breaker tegen GeckoTerminal-storingen (Gemini-feedback,
        # 23 aug 2026): exponential backoff i.p.v. elke minuut opnieuw
        # falen, en een limiet op Telegram-meldingen zodat een langdurige
        # storing niet honderden berichten stuurt.
        self._consecutive_failures = 0
        self._last_error_notification_at = 0.0

        self.lp_capital_usdc = float(os.environ.get("LP_CAPITAL_USDC", "1000"))
        self.lp_manager: Optional[LpManager] = None
        self._token0_is_whbar = True
        self._hbar_decimals = 8
        self._usdc_decimals = 6

        private_key = os.environ.get("HEDERA_LP_PRIVATE_KEY") or os.environ.get("HEDERA_BOT_PRIVATE_KEY", "")
        settings = NETWORK_SETTINGS[HEDERA_NETWORK]
        network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
        self.rpc_client = HederaRpcClient(network, private_key) if private_key else None

        if self.rpc_client:
            self._setup_lp_manager()
        else:
            print("[lp_loop] Geen HEDERA_LP_PRIVATE_KEY/HEDERA_BOT_PRIVATE_KEY -- lp_manager blijft ongekoppeld.")

    def _setup_lp_manager(self):
        try:
            if HEDERA_NETWORK == "testnet":
                base = resolve_testnet_addresses()
                v2 = resolve_testnet_v2_addresses()
            else:
                base = resolve_mainnet_addresses()
                v2 = resolve_mainnet_v2_addresses()

            whbar_addr = base.whbar_token
            usdc_addr = base.usdc
            self._hbar_decimals = 8
            self._usdc_decimals = base.usdc_decimals

            if int(whbar_addr, 16) < int(usdc_addr, 16):
                token0, token1 = whbar_addr, usdc_addr
                token0_decimals, token1_decimals = self._hbar_decimals, self._usdc_decimals
                self._token0_is_whbar = True
            else:
                token0, token1 = usdc_addr, whbar_addr
                token0_decimals, token1_decimals = self._usdc_decimals, self._hbar_decimals
                self._token0_is_whbar = False

            lp_config = LpPositionConfig(
                position_manager_address=v2.position_manager,
                token0=token0, token1=token1,
                fee_tier=int(os.environ.get("LP_FEE_TIER", "3000")),
                token0_decimals=token0_decimals, token1_decimals=token1_decimals,
            )
            self.lp_manager = LpManager(self.rpc_client, lp_config)
            print(f"[lp_loop] lp_manager gekoppeld ({HEDERA_NETWORK}), token0_is_whbar={self._token0_is_whbar}")
        except ValueError as e:
            print(f"[lp_loop] lp_manager NIET gekoppeld -- {e}")
            self.lp_manager = None

    async def run_forever(self):
        while True:
            try:
                await self._cycle()
            except Exception as e:
                import traceback
                print(f"FOUT in lp_loop: {e}")
                traceback.print_exc()
                telegram_notify.report_error("lp_loop", str(e))
            await asyncio.sleep(LP_POLL_INTERVAL_SECONDS)

    async def _refresh_sentiment_if_due(self) -> float:
        if (time.time() - self._last_sentiment_refresh) < LP_SENTIMENT_REFRESH_SECONDS:
            return self._cached_hbar_sentiment

        items = self.rss_news.fetch_news("HBAR", max_age_hours=4.0)
        new_items = [i for i in items if i.id not in self._processed_news_ids]
        if new_items:
            results = [self.llm.analyze_headline("HBAR", item.title) for item in new_items]
            published_timestamps = [item.published_at for item in new_items]
            self._cached_hbar_sentiment = LlmSentimentEngine.aggregate_with_decay(results, published_timestamps)
            for item in new_items:
                self._processed_news_ids.add(item.id)
        self._last_sentiment_refresh = time.time()
        return self._cached_hbar_sentiment

    def _refresh_volatility_regime_if_due(self) -> VolatilityRegime:
        if (time.time() - self._last_volatility_refresh) < LP_VOLATILITY_REFRESH_SECONDS:
            return self._cached_volatility_regime

        try:
            candles = self.geckoterminal.get_historical_ohlcv(timeframe="hour", limit=48)
            closes = [c.close for c in candles]
            hourly_returns = [
                (closes[i] - closes[i - 1]) / closes[i - 1]
                for i in range(1, len(closes)) if closes[i - 1] > 0
            ]
            self._cached_volatility_regime = compute_volatility_regime(hourly_returns)
        except Exception as e:
            print(f"[lp_loop] Kon volatiliteit niet verversen, behoud vorige regime: {e}")

        self._last_volatility_refresh = time.time()
        return self._cached_volatility_regime

    def _split_capital_to_amounts(self, current_price: float) -> tuple:
        half_usdc_value = self.lp_capital_usdc / 2
        hbar_amount = half_usdc_value / current_price

        hbar_raw = int(hbar_amount * (10 ** self._hbar_decimals))
        usdc_raw = int(half_usdc_value * (10 ** self._usdc_decimals))

        if self._token0_is_whbar:
            return hbar_raw, usdc_raw
        else:
            return usdc_raw, hbar_raw

    async def _cycle(self):
        try:
            snapshot = self.geckoterminal.get_pool_snapshot()
            current_price = snapshot.price_usd
            self._consecutive_failures = 0  # reset bij succes
        except Exception as e:
            self._consecutive_failures += 1

            # Exponential backoff: extra wachttijd bovenop de normale
            # 1-minuut-cyclus, oplopend tot een plafond van 5 minuten.
            backoff_seconds = min(2 ** self._consecutive_failures, 300)
            print(f"[lp_loop] Prijs ophalen mislukt (poging {self._consecutive_failures}): "
                  f"{e} -- extra wachttijd {backoff_seconds}s")
            await asyncio.sleep(backoff_seconds)

            # Telegram-melding maximaal 1x per 15 minuten tijdens een
            # aanhoudende storing, i.p.v. elke minuut opnieuw.
            if time.time() - self._last_error_notification_at > 15 * 60:
                telegram_notify.report_error(
                    "lp_loop: prijs ophalen",
                    f"{e} (poging {self._consecutive_failures}, "
                    f"volgende melding op zijn vroegst over 15 min)",
                )
                self._last_error_notification_at = time.time()
            return

        hbar_sentiment = await self._refresh_sentiment_if_due()
        volatility_regime = self._refresh_volatility_regime_if_due()

        if DRY_RUN or self.lp_manager is None:
            print(f"[DRY RUN / niet gekoppeld] LP-cyclus: prijs={current_price:.5f}, "
                  f"sentiment={hbar_sentiment:.2f}, regime={volatility_regime.value}, "
                  f"kapitaal={self.lp_capital_usdc} USDC")
            return

        amount0, amount1 = self._split_capital_to_amounts(current_price)

        rebalanced = self.lp_manager.rebalance_if_needed(
            current_price=current_price,
            amount0=amount0, amount1=amount1,
            volatility_regime=volatility_regime,
            sentiment_direction=hbar_sentiment,
        )
        if rebalanced:
            telegram_notify.report_lp_rebalance(
                action="herbalanceerd", price=current_price,
                tick_lower=self.lp_manager.state.tick_lower,
                tick_upper=self.lp_manager.state.tick_upper,
            )


class _NullDb:
    async def log_sentiment(self, *a, **kw): return -1
    async def log_strategy_signal(self, *a, **kw): return -1
    async def log_trade(self, *a, **kw): return -1
    async def get_open_positions(self, *a, **kw): return []
    async def open_position(self, *a, **kw): return -1
    async def update_highest_price(self, *a, **kw): pass
    async def close_position(self, *a, **kw): pass


async def main():
    db = PostgresClient()
    try:
        await db.connect()
    except EnvironmentError:
        print("WAARSCHUWING: geen DATABASE_URL -- draait zonder Postgres-logging.")
        db = _NullDb()

    # Alleen lokaal loggen, niet naar Telegram -- bij elke herstart tijdens
    # ontwikkelen/debuggen (docker compose up --force-recreate) stuurde dit
    # eerder een aparte Telegram-melding, wat al snel spam werd (23 aug
    # 2026: tientallen meldingen op een dag). Belangrijke gebeurtenissen
    # (trades, regime-overgangen, fouten) blijven wel naar Telegram gaan.
    print("HBAR Bot orchestrator gestart (RegimeOrchestrator)" + (" (DRY RUN)" if DRY_RUN else ""))

    # 23 aug 2026: TradingOrchestrator, LpOrchestrator en
    # PositionMonitorOrchestrator zijn vervangen door RegimeOrchestrator,
    # die het volledige samengevoegde kapitaal (EUR 2.000) beheert via een
    # alles-of-niets regime-schakelaar (LP_MODE/BULLISH_REFLEX/
    # BEARISH_REFLEX). De drie oude klassen blijven in dit bestand staan
    # (niet verwijderd) voor het geval een apart, gegradueerd tradingbudget
    # ooit weer gewenst is -- zie PLAN.md.
    from regime_orchestrator import RegimeOrchestrator
    regime = RegimeOrchestrator(db)

    await asyncio.gather(
        regime.run_forever(),
    )


if __name__ == "__main__":
    asyncio.run(main())
