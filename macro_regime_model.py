"""
macro_regime_model.py

Macro-marktregimedetectie (Bull/Bear/Sideways), onafhankelijk van het
dagelijkse LLM-sentiment -- gebaseerd op prijsmomentum over een langere
periode (30-90 dagen) (28 aug 2026).

Dit is BEWUST een eenvoudig, momentum-gebaseerd model, geen volledig
Hidden Markov Model (HMM) -- dat laatste vereist aanzienlijk meer data
en een aparte trainings-/validatiecyclus om betrouwbaar te zijn.
"""

from enum import Enum
from dataclasses import dataclass


class MacroRegime(Enum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"


@dataclass
class MacroRegimeResult:
    regime: MacroRegime
    momentum_pct: float


BULL_THRESHOLD = 0.15
BEAR_THRESHOLD = -0.15


def detect_macro_regime(prices: list, lookback_days: int = 30) -> MacroRegimeResult:
    """
    Bepaalt het macro-marktregime op basis van de totale prijsverandering
    over de laatste lookback_days (bij uurlijkse prijzen: lookback_days*24
    candles).
    """
    if not prices or len(prices) < 2:
        return MacroRegimeResult(regime=MacroRegime.SIDEWAYS, momentum_pct=0.0)

    lookback_hours = lookback_days * 24
    relevant_prices = prices[-lookback_hours:] if len(prices) > lookback_hours else prices

    start_price = relevant_prices[0]
    end_price = relevant_prices[-1]
    if start_price <= 0:
        return MacroRegimeResult(regime=MacroRegime.SIDEWAYS, momentum_pct=0.0)

    momentum_pct = (end_price - start_price) / start_price

    if momentum_pct >= BULL_THRESHOLD:
        regime = MacroRegime.BULL
    elif momentum_pct <= BEAR_THRESHOLD:
        regime = MacroRegime.BEAR
    else:
        regime = MacroRegime.SIDEWAYS

    return MacroRegimeResult(regime=regime, momentum_pct=momentum_pct)
