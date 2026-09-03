"""
risk_manager.py

Centrale guardrail-laag voor het DIRECTIONELE traden. Dwingt harde
grenzen af die de strategie-laag niet kan overrulen: max trades/dag,
daily loss-limit, dedup van nieuwsitems, cooldown na een trade, en
nonce-locking tussen losgekoppelde subprocessen.

LET OP: bemoeit zich NIET met LP-kapitaal -- LP-beheer (lp_manager.py)
draait als volledig onafhankelijk proces met zijn eigen, apart
geconfigureerde kapitaal (bv. een losse wallet), niet als een gedeelde
fractie van hetzelfde totaal.

Architectuurprincipe: risk_manager.py kan een signaal ALLEEN verzwakken
of blokkeren (naar HOLD), nooit versterken. Zit na strategy_engine.py en
safety_override.py in de keten -- zie PLAN.md voor het architectuurdiagram.
"""

import time
import fcntl
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Optional, Set

from strategy_engine import SignalResult, Direction


@dataclass
class RiskConfig:
    # Eigen, onafhankelijk geconfigureerd kapitaal voor het directionele
    # traden -- GEEN afgeleide fractie van een gedeeld totaal. LP-kapitaal
    # wordt volledig los hiervan beheerd (eigen wallet/instelling), zonder
    # dat risk_manager.py zich daarmee bemoeit.
    trading_capital_usdc: float = 1000.0
    max_trades_per_day: int = 10
    max_daily_loss_pct: float = 0.10       # 10% van trading_capital_usdc
    trade_cooldown_seconds: float = 30 * 60  # 30 min, whipsaw-preventie
    news_dedup_window_hours: float = 24.0
    nonce_lock_path: str = "/tmp/hbar_bot_execution.lock"


@dataclass
class RiskState:
    trades_today: int = 0
    trading_day: str = ""
    daily_pnl_usdc: float = 0.0
    last_trade_at: Optional[float] = None
    processed_news_ids: Set[str] = field(default_factory=set)


class RiskManager:
    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
        self.state = RiskState()

    def _check_day_reset(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.state.trading_day != today:
            self.state.trading_day = today
            self.state.trades_today = 0
            self.state.daily_pnl_usdc = 0.0

    def is_news_already_processed(self, news_id: str) -> bool:
        return news_id in self.state.processed_news_ids

    def mark_news_processed(self, news_id: str):
        self.state.processed_news_ids.add(news_id)
        # In productie: periodiek ids opschonen ouder dan news_dedup_window_hours
        # (bv. via een aparte achtergrondtaak of bij elke dag-reset).

    def is_in_cooldown(self) -> bool:
        if self.state.last_trade_at is None:
            return False
        return (time.time() - self.state.last_trade_at) < self.config.trade_cooldown_seconds

    def max_trading_position_usdc(self) -> float:
        """Kapitaal beschikbaar voor directioneel traden -- onafhankelijk
        geconfigureerd, niet gedeeld met of afgeleid van de LP-positie."""
        return self.config.trading_capital_usdc

    def evaluate_trading_signal(self, signal: SignalResult,
                                  news_id: Optional[str] = None) -> SignalResult:
        """
        Past harde guardrails toe op een signaal (na strategy_engine +
        safety_override). Kan het signaal alleen verzwakken/blokkeren.
        """
        self._check_day_reset()

        if signal.direction == Direction.HOLD:
            return signal

        if news_id is not None and self.is_news_already_processed(news_id):
            return self._blocked(signal, "Nieuwsbericht al eerder verwerkt (dedup).")

        if self.is_in_cooldown():
            remaining_min = (self.config.trade_cooldown_seconds - (time.time() - self.state.last_trade_at)) / 60
            return self._blocked(signal, f"Cooldown actief, nog {remaining_min:.1f} min.")

        if self.state.trades_today >= self.config.max_trades_per_day:
            return self._blocked(signal, f"Max trades/dag ({self.config.max_trades_per_day}) bereikt.")

        max_loss = self.config.max_daily_loss_pct * self.config.trading_capital_usdc
        if self.state.daily_pnl_usdc <= -max_loss:
            return self._blocked(signal, f"Daily loss-limit bereikt ({self.state.daily_pnl_usdc:.2f} USDC).")

        # Positiegrootte mag nooit meer zijn dan 100% van het TOEGEWEZEN
        # trading-kapitaal (niet het volledige bot-kapitaal) -- de harde
        # cap die de 50/50-scheiding afdwingt.
        if signal.position_fraction > 1.0:
            signal = replace(
                signal, position_fraction=1.0,
                reasoning=signal.reasoning + " [risk_manager: afgekapt op 100% toegewezen tradingkapitaal]",
            )

        return signal

    def record_trade_executed(self, news_id: Optional[str] = None, pnl_usdc: float = 0.0):
        """Aanroepen NA een daadwerkelijk uitgevoerde trade."""
        self._check_day_reset()
        self.state.trades_today += 1
        self.state.last_trade_at = time.time()
        self.state.daily_pnl_usdc += pnl_usdc
        if news_id is not None:
            self.mark_news_processed(news_id)

    def _blocked(self, signal: SignalResult, reason: str) -> SignalResult:
        return replace(
            signal, direction=Direction.HOLD, confidence=0.0, position_fraction=0.0,
            reasoning=f"GEBLOKKEERD door risk_manager: {reason} (origineel: {signal.reasoning})",
        )

    def acquire_execution_lock(self, timeout_seconds: float = 30.0) -> "_FileLock":
        """
        Voorkomt dat twee losgekoppelde subprocessen (bv. een swap en
        een LP-rebalance) gelijktijdig een transactie bouwen en dezelfde
        nonce grijpen. Gebruik:
            with risk_manager.acquire_execution_lock():
                subprocess.run([...])
        """
        return _FileLock(self.config.nonce_lock_path, timeout_seconds)


class _FileLock:
    def __init__(self, path: str, timeout_seconds: float):
        self.path = path
        self.timeout_seconds = timeout_seconds
        self._fh = None

    def __enter__(self):
        self._fh = open(self.path, "w")
        start = time.time()
        while True:
            try:
                fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.time() - start > self.timeout_seconds:
                    self._fh.close()
                    raise TimeoutError(f"Kon execution lock niet krijgen binnen {self.timeout_seconds}s")
                time.sleep(0.5)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._fh:
            fcntl.flock(self._fh, fcntl.LOCK_UN)
            self._fh.close()


if __name__ == "__main__":
    from strategy_engine import SignalResult, Direction

    rm = RiskManager()
    print(f"Trading-kapitaal (onafhankelijk geconfigureerd): {rm.max_trading_position_usdc()} USDC")

    signal = SignalResult(
        direction=Direction.BUY, confidence=0.8, position_fraction=0.1,
        reasoning="Test-signaal", btc_score=0.1, hbar_score=0.8,
    )

    # Eerste keer: moet doorgelaten worden
    result1 = rm.evaluate_trading_signal(signal, news_id="news_001")
    print(f"\nEerste evaluatie: {result1.direction.value} (verwacht: buy)")

    rm.record_trade_executed(news_id="news_001")

    # Tweede keer, zelfde nieuws-id: moet geblokkeerd worden door dedup
    result2 = rm.evaluate_trading_signal(signal, news_id="news_001")
    print(f"Zelfde nieuws opnieuw: {result2.direction.value} (verwacht: hold, dedup)")

    # Nieuw nieuws, maar binnen cooldown: moet ook geblokkeerd worden
    result3 = rm.evaluate_trading_signal(signal, news_id="news_002")
    print(f"Nieuw nieuws binnen cooldown: {result3.direction.value} (verwacht: hold, cooldown)")

    # Lock-mechanisme testen
    with rm.acquire_execution_lock(timeout_seconds=5):
        print("\nExecution lock verkregen en weer vrijgegeven -- werkt.")
