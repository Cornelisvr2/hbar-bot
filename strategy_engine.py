"""
strategy_engine.py

Combineert BTC-sentiment (leidend, hoog nieuwsvolume) met HBAR-specifiek
sentiment (aanvullend, kan de BTC-driven trade versterken, verzwakken,
of als losstaande trigger dienen wanneer BTC geen duidelijke beweging laat zien).

Logica-samenvatting:
- BTC-score is de DEFAULT trigger. Bij een duidelijke BTC-beweging volgt de bot
  die beweging in HBAR, geschaald met een beta-factor.
- HBAR-specifiek nieuws werkt als modifier op die basis-trade:
    * zelfde richting  -> confidence/positiegrootte omhoog
    * tegengestelde richting -> confidence/positiegrootte omlaag (kan zelfs
      de trade omdraaien als het HBAR-specifieke signaal sterk genoeg is)
- Als BTC neutraal is maar er is een sterk HBAR-specifiek signaal, dan is dat
  op zichzelf een geldige trigger (bv. nieuwe Council-member), want dit raakt
  BTC niet maar HBAR wel.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Direction(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class StrategyConfig:
    # Drempel waarboven een BTC-beweging als "duidelijk" geldt (schaal -1..1)
    btc_move_threshold: float = 0.35
    # Drempel waarboven HBAR-specifiek nieuws als "significant" geldt
    hbar_specific_threshold: float = 0.35
    # Zone rond 0 waarin scores als neutraal/ruis worden behandeld
    neutral_zone: float = 0.15
    # Hoe sterk HBAR doorgaans meebeweegt met een BTC-marktbeweging.
    # >1.0 betekent dat HBAR historisch heftiger reageert dan BTC zelf.
    hbar_btc_beta: float = 1.0
    # Basispositiegrootte als fractie van beschikbare balans (bv. 0.10 = 10%)
    base_position_fraction: float = 0.10
    # Maximale positiegrootte als fractie, ongeacht confidence
    max_position_fraction: float = 0.20


@dataclass
class SignalResult:
    direction: Direction
    confidence: float           # 0.0 - 1.0
    position_fraction: float    # aanbevolen fractie van balans voor deze trade
    reasoning: str
    btc_score: float
    hbar_score: float


class StrategyEngine:
    def __init__(self, config: Optional[StrategyConfig] = None, beta_calculator=None):
        """
        beta_calculator: optionele BetaCalculator (uit coingecko_client.py).
        Indien meegegeven, wordt config.hbar_btc_beta bij elke evaluatie
        overschreven door de actuele, dynamisch berekende beta i.p.v. de
        statische waarde uit StrategyConfig.
        """
        self.config = config or StrategyConfig()
        self.beta_calculator = beta_calculator

    def evaluate(self, btc_score: float, hbar_score: float) -> SignalResult:
        cfg = self.config

        if self.beta_calculator is not None:
            beta_result = self.beta_calculator.get_beta()
            cfg.hbar_btc_beta = beta_result.beta

        btc_is_moving = abs(btc_score) >= cfg.btc_move_threshold
        hbar_has_specific_signal = abs(hbar_score) >= cfg.hbar_specific_threshold

        # --- Geval 1: geen van beide signalen is significant ---
        if not btc_is_moving and not hbar_has_specific_signal:
            return SignalResult(
                direction=Direction.HOLD,
                confidence=0.0,
                position_fraction=0.0,
                reasoning="Geen significant BTC- of HBAR-specifiek signaal.",
                btc_score=btc_score,
                hbar_score=hbar_score,
            )

        # --- Geval 2: alleen HBAR-specifiek nieuws, BTC vlak ---
        if not btc_is_moving and hbar_has_specific_signal:
            direction = Direction.BUY if hbar_score > 0 else Direction.SELL
            confidence = min(1.0, abs(hbar_score))
            position_fraction = self._scale_position(confidence)
            return SignalResult(
                direction=direction,
                confidence=confidence,
                position_fraction=position_fraction,
                reasoning=(
                    f"Geen BTC-beweging, maar sterk HBAR-specifiek nieuws "
                    f"(score={hbar_score:.2f}) -> losstaande HBAR-catalyst-trade."
                ),
                btc_score=btc_score,
                hbar_score=hbar_score,
            )

        # --- Geval 3: BTC beweegt, geen (relevant) HBAR-specifiek nieuws ---
        base_direction_score = btc_score * cfg.hbar_btc_beta

        if not hbar_has_specific_signal:
            direction = Direction.BUY if base_direction_score > 0 else Direction.SELL
            confidence = min(1.0, abs(base_direction_score))
            position_fraction = self._scale_position(confidence)
            return SignalResult(
                direction=direction,
                confidence=confidence,
                position_fraction=position_fraction,
                reasoning=(
                    f"BTC-gedreven trade (score={btc_score:.2f}), geen HBAR-specifiek "
                    f"nieuws als modifier -> volg BTC met beta={cfg.hbar_btc_beta}."
                ),
                btc_score=btc_score,
                hbar_score=hbar_score,
            )

        # --- Geval 4: zowel BTC beweegt als HBAR-specifiek nieuws is significant ---
        same_direction = (btc_score > 0) == (hbar_score > 0)

        if same_direction:
            # Bevestiging: verhoog confidence t.o.v. BTC alleen
            combined_score = base_direction_score + hbar_score * 0.5
            direction = Direction.BUY if combined_score > 0 else Direction.SELL
            confidence = min(1.0, abs(combined_score))
            position_fraction = self._scale_position(confidence, boost=True)
            reasoning = (
                f"BTC (score={btc_score:.2f}) en HBAR-specifiek nieuws "
                f"(score={hbar_score:.2f}) bevestigen elkaar -> hogere confidence."
            )
        else:
            # Conflict: HBAR-specifiek nieuws werkt de BTC-trend tegen
            combined_score = base_direction_score + hbar_score * 0.7
            if abs(combined_score) < cfg.neutral_zone:
                return SignalResult(
                    direction=Direction.HOLD,
                    confidence=0.0,
                    position_fraction=0.0,
                    reasoning=(
                        f"BTC (score={btc_score:.2f}) en HBAR-specifiek nieuws "
                        f"(score={hbar_score:.2f}) heffen elkaar op -> geen trade."
                    ),
                    btc_score=btc_score,
                    hbar_score=hbar_score,
                )
            direction = Direction.BUY if combined_score > 0 else Direction.SELL
            confidence = min(1.0, abs(combined_score) * 0.6)  # extra korting bij conflict
            position_fraction = self._scale_position(confidence)
            reasoning = (
                f"BTC (score={btc_score:.2f}) en HBAR-specifiek nieuws "
                f"(score={hbar_score:.2f}) zijn tegengesteld -> verkleinde, "
                f"voorzichtige positie."
            )

        return SignalResult(
            direction=direction,
            confidence=confidence,
            position_fraction=position_fraction,
            reasoning=reasoning,
            btc_score=btc_score,
            hbar_score=hbar_score,
        )

    def _scale_position(self, confidence: float, boost: bool = False) -> float:
        cfg = self.config
        fraction = cfg.base_position_fraction * confidence
        if boost:
            fraction *= 1.5
        return round(min(fraction, cfg.max_position_fraction), 4)


if __name__ == "__main__":
    engine = StrategyEngine()

    scenarios = [
        ("Alleen BTC rally, geen HBAR-nieuws", 0.6, 0.05),
        ("Nieuwe Council-member (geen BTC-beweging)", 0.05, 0.8),
        ("BTC rally + goed HBAR-nieuws (bevestiging)", 0.6, 0.7),
        ("BTC rally + slecht HBAR-nieuws (conflict)", 0.6, -0.6),
        ("Geen signalen", 0.05, 0.05),
    ]

    for label, btc, hbar in scenarios:
        result = engine.evaluate(btc, hbar)
        print(f"\n{label}")
        print(f"  -> {result.direction.value.upper()} | confidence={result.confidence:.2f} "
              f"| positie={result.position_fraction:.2%}")
        print(f"  reden: {result.reasoning}")
