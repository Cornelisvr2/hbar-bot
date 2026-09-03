"""
safety_override.py

Extra veiligheidscheck bovenop strategy_engine.py, gebaseerd op het
eenvoudigere vaste-weging-model dat in het Gemini-gesprek werd voorgesteld
(btc_sentiment * 0.4 + hbar_sentiment * 0.6).

BELANGRIJK: dit vervangt de genuanceerde combinatielogica in
strategy_engine.py NIET. Die blijft de primaire beslisser (BTC leidend,
HBAR-specifiek als modifier/losstaande trigger, confidence-scaling).

Deze module fungeert puur als CIRCUIT BREAKER: een simpel, robuust
vangnet dat een geforceerde volledige exit afdwingt als de gecombineerde
score een extreme paniek-drempel doorbreekt -- ook als de primaire
strategie (om welke reden dan ook) geen sell-signaal zou geven.

Bewuste asymmetrie: dit vangnet forceert ALLEEN verkopen (kapitaal
beschermen), nooit kopen. Een veiligheidsmechanisme hoort risico te
verkleinen, niet om agressief nieuwe posities af te dwingen op basis
van een simpeler model dan onze primaire strategie.
"""

from dataclasses import replace

from strategy_engine import SignalResult, Direction, StrategyConfig


DEFAULT_BTC_WEIGHT = 0.4
DEFAULT_HBAR_WEIGHT = 0.6
DEFAULT_PANIC_THRESHOLD = -0.4  # Gemini's voorgestelde drempel


def compute_fixed_combined_score(
    btc_score: float,
    hbar_score: float,
    btc_weight: float = DEFAULT_BTC_WEIGHT,
    hbar_weight: float = DEFAULT_HBAR_WEIGHT,
) -> float:
    """Simpele, vaste gewogen som -- het Gemini-model, puur als monitor-signaal."""
    return round(btc_score * btc_weight + hbar_score * hbar_weight, 3)


def compute_combined_volatility_sigma(
    btc_volatility_sigma: float,
    hbar_volatility_sigma: float,
    btc_weight: float = DEFAULT_BTC_WEIGHT,
    hbar_weight: float = DEFAULT_HBAR_WEIGHT,
) -> float:
    """
    Zelfde gewogen-som-aanpak als compute_fixed_combined_score(), maar
    voor volatility_sigma i.p.v. sentiment_score (28 aug 2026, voor het
    GBM-range-model).
    """
    return round(btc_volatility_sigma * btc_weight + hbar_volatility_sigma * hbar_weight, 3)


def apply_panic_safety_check(
    signal: SignalResult,
    btc_score: float,
    hbar_score: float,
    panic_threshold: float = DEFAULT_PANIC_THRESHOLD,
    btc_weight: float = DEFAULT_BTC_WEIGHT,
    hbar_weight: float = DEFAULT_HBAR_WEIGHT,
) -> SignalResult:
    """
    Neemt het SignalResult van StrategyEngine.evaluate() en overschrijft het
    ALLEEN als de vaste-weging-score een extreme paniek-drempel doorbreekt
    en de primaire strategie nog geen SELL aangeeft.

    Als de primaire strategie al SELL zegt, wordt er niets overschreven --
    de circuit breaker is puur een vangnet, geen vervanging.
    """
    combined_score = compute_fixed_combined_score(btc_score, hbar_score, btc_weight, hbar_weight)

    if combined_score > panic_threshold:
        return signal  # geen paniek, primaire strategie blijft leidend

    if signal.direction == Direction.SELL:
        return signal  # primaire strategie doet al wat nodig is

    return replace(
        signal,
        direction=Direction.SELL,
        confidence=1.0,
        position_fraction=1.0,  # volledige exit -- kapitaal beschermen heeft prioriteit
        reasoning=(
            f"PANIEK-OVERRIDE: vaste-weging score ({combined_score:.3f}) doorbreekt "
            f"drempel ({panic_threshold}) [btc={btc_score:.2f}*{btc_weight} + "
            f"hbar={hbar_score:.2f}*{hbar_weight}]. Primaire strategie gaf "
            f"'{signal.direction.value}' (confidence={signal.confidence:.2f}), maar "
            f"circuit breaker forceert volledige exit ter bescherming van kapitaal."
        ),
    )


if __name__ == "__main__":
    from strategy_engine import StrategyEngine

    engine = StrategyEngine()

    scenarios = [
        ("Normale HOLD, geen paniek", 0.1, 0.05),
        ("Primaire strategie zegt BUY, maar BTC crasht hard", 0.6, -0.9),
        ("Primaire strategie zegt al SELL bij crash (geen override nodig)", -0.8, -0.7),
        ("Mild negatief, geen paniek-drempel doorbroken", -0.2, -0.1),
    ]

    for label, btc, hbar in scenarios:
        primary = engine.evaluate(btc, hbar)
        final = apply_panic_safety_check(primary, btc, hbar)

        print(f"\n{label}")
        print(f"  Primair:  {primary.direction.value.upper()} (confidence={primary.confidence:.2f})")
        print(f"  Na check: {final.direction.value.upper()} (confidence={final.confidence:.2f})")
        if final.reasoning != primary.reasoning:
            print(f"  -> OVERRIDE TRIGGERED: {final.reasoning}")
