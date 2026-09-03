"""
position_planner.py

Vertaalt het VIX Rider-patroon (entry price, initial stop-loss, trailing
stop, risk amount, position value) naar HBAR-posities op een spot-DEX
(geen leverage/shorting -- je houdt HBAR of USDC, niets ertussenin).

Vertaling van concepten:
- BUY-signaal  -> open een HBAR-positie (USDC -> HBAR), met een
  initial_stop_loss (exit terug naar USDC als de prijs te ver daalt) en
  een trailing_stop die meebeweegt met de hoogste bereikte prijs, om
  winst te beschermen zodra de trade in de plus staat.
- SELL-signaal -> sluit een bestaande HBAR-positie (HBAR -> USDC).
  Geen stop-loss/trailing nodig, want de bestemming (USDC) is stabiel.
- HOLD         -> geen plan, geen actie.
"""

from dataclasses import dataclass
from typing import Optional

from strategy_engine import SignalResult, Direction


DEFAULT_TOTAL_CAPITAL_USDC = 2000.0
DEFAULT_STOP_LOSS_PCT = 0.05        # 5% onder entry
DEFAULT_TRAILING_DISTANCE_PCT = 0.05  # 5% onder de hoogste bereikte prijs


@dataclass
class HbarPositionPlan:
    direction: str                  # 'BUY' of 'SELL'
    entry_price: float              # USDC per HBAR op moment van entry
    initial_stop_loss: Optional[float]   # prijs waaronder direct exit (alleen BUY)
    trailing_distance_pct: Optional[float]  # afstand tot hoogste prijs (alleen BUY)
    quantity_hbar: float            # hoeveelheid HBAR in de trade
    usdc_amount: float              # hoeveelheid USDC in de trade
    risk_amount_usdc: float         # max verlies in USDC bij initial_stop_loss
    position_value_usdc: float      # totale waarde van de positie in USDC
    capped_by_max_capital: bool
    reason: str


def build_position_plan(
    signal: SignalResult,
    current_hbar_price_usdc: float,
    total_capital_usdc: float = DEFAULT_TOTAL_CAPITAL_USDC,
    stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
    trailing_distance_pct: float = DEFAULT_TRAILING_DISTANCE_PCT,
) -> Optional[HbarPositionPlan]:
    """
    signal: output van StrategyEngine.evaluate() (bevat direction + position_fraction)
    current_hbar_price_usdc: actuele HBAR-prijs in USDC (uit een quote-call)
    total_capital_usdc: totaal beschikbaar bot-kapitaal, default 2000
    """
    if signal.direction == Direction.HOLD:
        return None

    position_value = signal.position_fraction * total_capital_usdc
    capped = False
    if position_value > total_capital_usdc:
        position_value = total_capital_usdc
        capped = True

    quantity_hbar = position_value / current_hbar_price_usdc

    if signal.direction == Direction.BUY:
        initial_stop_loss = current_hbar_price_usdc * (1 - stop_loss_pct)
        risk_amount = (current_hbar_price_usdc - initial_stop_loss) * quantity_hbar

        return HbarPositionPlan(
            direction="BUY",
            entry_price=current_hbar_price_usdc,
            initial_stop_loss=initial_stop_loss,
            trailing_distance_pct=trailing_distance_pct,
            quantity_hbar=quantity_hbar,
            usdc_amount=position_value,
            risk_amount_usdc=risk_amount,
            position_value_usdc=position_value,
            capped_by_max_capital=capped,
            reason=signal.reasoning,
        )

    else:  # SELL -- positie sluiten, geen stop-loss/trailing nodig
        return HbarPositionPlan(
            direction="SELL",
            entry_price=current_hbar_price_usdc,
            initial_stop_loss=None,
            trailing_distance_pct=None,
            quantity_hbar=quantity_hbar,
            usdc_amount=position_value,
            risk_amount_usdc=0.0,
            position_value_usdc=position_value,
            capped_by_max_capital=capped,
            reason=signal.reasoning,
        )


class TrailingStopTracker:
    """
    Houdt de hoogste bereikte prijs sinds entry bij, en berekent de
    actuele trailing-stop-prijs. Moet elke prijs-poll worden bijgewerkt
    (bv. elke keer dat de main_orchestrator een nieuwe quote ophaalt).
    """

    def __init__(self, entry_price: float, trailing_distance_pct: float,
                 initial_stop_loss: float):
        self.entry_price = entry_price
        self.trailing_distance_pct = trailing_distance_pct
        self.initial_stop_loss = initial_stop_loss
        self.highest_price = entry_price

    def update(self, current_price: float) -> float:
        """Werkt de hoogste prijs bij en geeft de huidige stop-prijs terug."""
        if current_price > self.highest_price:
            self.highest_price = current_price

        trailing_stop = self.highest_price * (1 - self.trailing_distance_pct)
        # De trailing stop mag nooit onder de initiele stop-loss zakken
        return max(trailing_stop, self.initial_stop_loss)

    def should_exit(self, current_price: float) -> bool:
        stop_price = self.update(current_price)
        return current_price <= stop_price


if __name__ == "__main__":
    from strategy_engine import SignalResult, Direction

    # Voorbeeld: BUY-signaal met 8% confidence-geschaalde positie
    example_signal = SignalResult(
        direction=Direction.BUY,
        confidence=0.8,
        position_fraction=0.08,
        reasoning="Voorbeeld: sterk HBAR-specifiek nieuws",
        btc_score=0.1,
        hbar_score=0.8,
    )

    plan = build_position_plan(example_signal, current_hbar_price_usdc=0.065,
                                total_capital_usdc=2000.0)
    print(plan)
    print(f"\nPositiewaarde: ${plan.position_value_usdc:.2f} van $2000 kapitaal")
    print(f"Aantal HBAR: {plan.quantity_hbar:.2f}")
    print(f"Risico bij initial stop-loss: ${plan.risk_amount_usdc:.2f}")

    # Trailing stop simulatie: prijs stijgt eerst, daalt dan
    tracker = TrailingStopTracker(
        entry_price=plan.entry_price,
        trailing_distance_pct=plan.trailing_distance_pct,
        initial_stop_loss=plan.initial_stop_loss,
    )
    price_path = [0.065, 0.070, 0.075, 0.073, 0.069, 0.066]
    for price in price_path:
        exit_now = tracker.should_exit(price)
        print(f"Prijs: {price:.4f} | trailing stop: {tracker.update(price):.4f} | exit? {exit_now}")
        if exit_now:
            break
