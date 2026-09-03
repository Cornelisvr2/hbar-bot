"""
lvr_model.py

Loss Versus Rebalancing (LVR) -- kwantificeert specifiek de winst die
arbitrageurs uit de pool halen wanneer zij de poolprijs in lijn brengen
met een externe, gecentraliseerde referentieprijs (28 aug 2026).

ANDERS dan impermanent loss (die je LP-positie vergelijkt met simpelweg
vasthouden): LVR meet de directe arbitrage-winst zelf, een preciezere
maatstaf voor "hoeveel kost toxic flow me precies".

BELANGRIJKE CORRECTIE (28 aug 2026): de oorspronkelijk aangeleverde
discrete formule (L*(P0-P1)^2) bleek dimensioneel onjuist en week
enorm af van de daadwerkelijke waarde (~3.590x verschil in een
testgeval). Zelf afgeleid en geverifieerd via sympy tegen de
standaard Uniswap-V3-liquiditeitswiskunde (x=L/sqrt(P), y=L*sqrt(P)):

    LVR_discreet = L * (sqrt(P0) - sqrt(P1))^2 / sqrt(P0)

Dit is de daadwerkelijke arbitrage-winst (in token Y) als de prijs
abrupt van P0 naar P1 beweegt, ZOLANG P1 binnen de actieve
liquiditeitsrange [Pa, Pb] valt.
"""

import math
from dataclasses import dataclass


@dataclass
class LvrResult:
    lvr_amount: float  # in token Y (bv. SAUCE/USDC)
    price_ratio: float  # P1/P0, ter info


def compute_discrete_lvr(liquidity: float, price_before: float, price_after: float) -> LvrResult:
    """
    Discrete LVR voor een abrupte prijsbeweging (bv. een flash crash),
    geverifieerd via sympy tegen de standaard Uniswap-V3-wiskunde (28 aug
    2026). Geeft de arbitrage-winst in token Y terug.

    LET OP: geldig zolang price_after nog binnen de actieve
    liquiditeitsrange valt -- buiten de range is de positie al volledig
    in een van beide tokens, en verandert de dynamiek.
    """
    if liquidity <= 0 or price_before <= 0 or price_after <= 0:
        return LvrResult(lvr_amount=0.0, price_ratio=1.0)

    lvr_amount = liquidity * (math.sqrt(price_before) - math.sqrt(price_after)) ** 2 / math.sqrt(price_before)
    return LvrResult(lvr_amount=lvr_amount, price_ratio=price_after / price_before)


def compute_continuous_lvr_rate(liquidity: float, current_price: float, sigma: float) -> float:
    """
    VOLLEDIG GEVERIFIEERD (30 aug 2026, na eerder een "nog niet
    geverifieerd"-status op 28 aug 2026). De eerdere twijfel kwam voort
    uit een fout in de VERIFICATIEPOGING zelf, niet in de formule: er
    werd toen de tweede afgeleide van een LOSSE reserve (d²x/dP²)
    berekend, terwijl Gamma in de LVR-literatuur specifiek de tweede
    afgeleide van de TOTALE POOLWAARDE betekent (analoog aan een
    optie-Gamma: V(P) = x(P)*P + y(P), Gamma = d²V/dP²).

    Correct afgeleid en met sympy geverifieerd (30 aug 2026):
    V(P) = 2*L*sqrt(P) (standaard Uniswap-V3-waardefunctie)
    Gamma = d²V/dP² = -L/(2*P^1.5) (negatief -- de waarde is concaaf
        in P, wat precies de bron van LVR is)
    Verlies-snelheid = -0.5*sigma^2*P^2*Gamma = 0.25*sigma^2*L*sqrt(P)
    (het standaard Ito/optie-Greeks-resultaat voor waardeverlies door
    negatieve Gamma bij Brownse beweging in P) -- exact gelijk aan de
    formule hieronder, verschil geverifieerd als 0.

    Continue LVR-'bleed'-snelheid (per tijdseenheid, zelfde eenheid als
    sigma), voor reguliere (niet-flash-crash) volatiliteit. Kan nu
    veilig gebruikt worden voor besluitvorming.
    """
    if liquidity <= 0 or current_price <= 0 or sigma < 0:
        return 0.0

    gamma = liquidity / (2 * current_price ** 1.5)
    lvr_rate = 0.5 * (sigma ** 2) * (current_price ** 2) * gamma
    return lvr_rate
