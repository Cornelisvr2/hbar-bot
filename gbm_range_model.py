"""
gbm_range_model.py

Vertaalt LLM-sentiment (mu) en LLM-volatiliteit (sigma) naar een
concrete, doorlopend berekende LP-range, via Geometric Brownian
Motion's bekende, analytische oplossing (28 aug 2026) -- in plaats van
de eerdere, discrete LOW/NORMAL/HIGH-breedte-indeling.

GBM: dS_t = mu * S_t * dt + sigma * S_t * dW_t
Analytische oplossing voor S_T (lognormaal verdeeld):
    S_T = S_0 * exp((mu - sigma^2/2)*T + sigma*sqrt(T)*Z),  Z ~ N(0,1)

We gebruiken dit om een BETROUWBAARHEIDSINTERVAL voor S_T te bepalen
(bv. 80%), en dat interval wordt de nieuwe LP-range -- breder bij hogere
sigma, scheefgetrokken bij niet-nul mu.

BELANGRIJKE KALIBRATIE-AANNAMES (expliciet, om later bij te kunnen
stellen op basis van echte resultaten):
- sentiment_mu (LLM, -1.0 tot 1.0) wordt geschaald naar een verwacht
  RENDEMENT over de horizon T via SENTIMENT_TO_DRIFT_SCALE -- dit is een
  aanname, geen empirisch geijkte waarde (in tegenstelling tot de
  hieronder gebruikte, wel-empirisch-gemeten historische volatiliteit).
- volatility_sigma (LLM, 0.0-1.0) wordt gebruikt als MULTIPLIER op de
  al-bestaande, ECHTE, gemeten historische uurvolatiliteit (Binance-
  data, 27 aug 2026: 0.6072%) -- dit is bewust NIET een absolute,
  LLM-verzonnen sigma, maar een aanpassing bovenop een reeds
  empirisch gegronde basiswaarde. sigma_llm=0 -> alleen de normale,
  historische volatiliteit. sigma_llm=1.0 -> verdubbelt die.
"""

import math
from dataclasses import dataclass

SENTIMENT_TO_DRIFT_SCALE = 0.02  # sentiment_mu=1.0 -> verwacht +2% rendement over de horizon T

# Extra drift-versterking bij een DUIDELIJK macro-regime (28 aug 2026, op
# verzoek) -- een bevestigd Bull/Bear-regime (niet Sideways) mag de range
# sterker scheeftrekken dan losse nieuws-sentiment alleen zou doen, want
# een aanhoudende, meetbare trend is een sterker signaal dan een los
# nieuwsbericht. AANNAME, geen empirisch geijkte waarde.
MACRO_REGIME_DRIFT_BOOST = 2.5  # vermenigvuldigt SENTIMENT_TO_DRIFT_SCALE bij Bull/Bear

# Fat-tail-buffer (30 aug 2026, op aangeleverde feedback) -- extra marge
# aan de ONDERKANT van de range, om GBM's structurele onderschatting
# van plotse crashes te compenseren. AANNAME, geen empirisch geijkte
# waarde -- 15%, zoals expliciet voorgesteld.
FAT_TAIL_BUFFER_FRACTION = 0.15

# Asymmetrische regime-bias (28 aug 2026, op verzoek, HERZIEN na een
# gevonden fout bij het testen) -- past de effectieve mu aan op basis
# van het macro-marktregime: in een bullmarkt wordt REGIME-BEVESTIGEND
# nieuws (positief) versterkt en REGIME-TEGENSPREKEND nieuws (negatief)
# afgezwakt ("buy the dip"); in een bearmarkt precies andersom. AANNAME,
# geen empirisch geijkte waarde.
#
# BELANGRIJKE CORRECTIE: de eerste versie gebruikte een simpele lineaire
# formule (mu + mu*beta), die bij NEGATIEVE mu-waarden het TEGENGESTELDE
# effect gaf van de bedoeling (versterkte i.p.v. verzwakte) -- gevonden
# bij het testen tegen de eigen voorbeelden uit het voorstel. Vereist
# tekenafhankelijke logica: bevestigend nieuws (zelfde richting als het
# regime) wordt versterkt, tegensprekend nieuws wordt afgezwakt.
REGIME_BIAS_FACTOR = 0.6  # hoeveel versterking/verzwakking, zelfde grootte voor beide


def apply_regime_bias(sentiment_mu: float, macro_regime: str) -> float:
    """
    Past sentiment_mu aan op basis van het macro-regime: nieuws dat het
    regime BEVESTIGT wordt versterkt, nieuws dat het TEGENSPREEKT wordt
    afgezwakt. Bij sideways: geen aanpassing.
    """
    if macro_regime == "bull":
        if sentiment_mu >= 0:
            return sentiment_mu * (1 + REGIME_BIAS_FACTOR)  # bevestigend -> versterkt
        else:
            return sentiment_mu * (1 - REGIME_BIAS_FACTOR)  # tegensprekend -> afgezwakt
    elif macro_regime == "bear":
        if sentiment_mu <= 0:
            return sentiment_mu * (1 + REGIME_BIAS_FACTOR)  # bevestigend -> versterkt
        else:
            return sentiment_mu * (1 - REGIME_BIAS_FACTOR)  # tegensprekend -> afgezwakt
    else:
        return sentiment_mu


@dataclass
class GbmRangeResult:
    lower_price: float
    upper_price: float
    expected_price: float
    effective_mu: float
    effective_sigma: float


def compute_gbm_confidence_interval(
    current_price: float,
    sentiment_mu: float,
    volatility_sigma: float,
    historical_hourly_volatility: float,
    horizon_hours: float,
    confidence_level: float = 0.80,
    macro_regime: str = "sideways",
) -> GbmRangeResult:
    """
    Berekent een betrouwbaarheidsinterval voor de prijs op tijdstip T
    (horizon_hours vanaf nu), via GBM's analytische, lognormale
    oplossing.

    macro_regime (28 aug 2026): "bull"/"bear"/"sideways" -- bij een
    bevestigd Bull- of Bear-regime wordt de effectieve drift extra
    versterkt (MACRO_REGIME_DRIFT_BOOST), zodat de range sterker
    scheeftrekt bij een aanhoudende, meetbare trend dan bij losse
    nieuws-sentiment alleen. Verwacht dat sentiment_mu AL door
    apply_regime_bias() is gehaald door de aanroeper, voor de
    nieuws-niveau-asymmetrie -- dit is een AANVULLENDE, macro-niveau
    versterking daarbovenop.
    """
    if current_price <= 0 or horizon_hours <= 0:
        raise ValueError("current_price en horizon_hours moeten positief zijn.")

    T = horizon_hours

    drift_scale = SENTIMENT_TO_DRIFT_SCALE
    if macro_regime in ("bull", "bear"):
        drift_scale *= MACRO_REGIME_DRIFT_BOOST

    effective_mu = sentiment_mu * drift_scale

    sigma_multiplier = 1.0 + volatility_sigma
    effective_sigma = historical_hourly_volatility * sigma_multiplier * math.sqrt(T)

    z = _normal_quantile(0.5 + confidence_level / 2)

    drift_term = effective_mu - (effective_sigma ** 2) / 2

    expected_price = current_price * math.exp(drift_term)
    lower_price = current_price * math.exp(drift_term - z * effective_sigma)
    upper_price = current_price * math.exp(drift_term + z * effective_sigma)

    # Fat-tail-buffer (30 aug 2026, op aangeleverde feedback) -- GBM gaat
    # uit van een log-normale verdeling, die de kans op extreme, plotse
    # crashes structureel onderschat t.o.v. hoe crypto zich in de
    # praktijk gedraagt ("fat tails"). Een vaste, extra marge aan de
    # ONDERKANT (crashes zijn doorgaans abrupter/extremer dan pumps)
    # compenseert hiervoor, zonder de hele GBM-aanpak te vervangen.
    # AANNAME, geen empirisch geijkte waarde.
    lower_price *= (1 - FAT_TAIL_BUFFER_FRACTION)

    return GbmRangeResult(
        lower_price=lower_price,
        upper_price=upper_price,
        expected_price=expected_price,
        effective_mu=effective_mu,
        effective_sigma=effective_sigma,
    )


@dataclass
class ReflexEconomicsResult:
    should_proceed: bool
    expected_il_avoided_hbar: float
    expected_fee_income_foregone_hbar: float
    round_trip_cost_hbar: float
    net_benefit_hbar: float


def evaluate_reflex_transition_economics(
    current_price: float,
    sentiment_mu: float,
    volatility_sigma: float,
    historical_hourly_volatility: float,
    horizon_hours: float,
    capital_hbar: float,
    typical_width: float = 0.15,
    fee_apr_at_typical_width: float = 0.0161,
    round_trip_cost_hbar: float = 2.12,
) -> ReflexEconomicsResult:
    """
    Weegt af of een volledige reflex-overstap (LP-positie sluiten, alles
    omzetten naar een enkel token, en later weer terugkomen) daadwerkelijk
    meerwaarde heeft t.o.v. gewoon in de pool blijven (28 aug 2026, op
    verzoek).

    Vergelijking: verwacht vermeden impermanent loss (door NIET
    blootgesteld te zijn aan de verwachte prijsbeweging tijdens
    horizon_hours) MINUS de misgelopen fee-inkomsten tijdens diezelfde
    periode, tegen de geschatte kosten van de volledige heen-en-terug-
    cyclus (sluiten + swappen, en later weer openen + swappen).

    round_trip_cost_hbar: HERIJKT (3 sep 2026, empirisch, na een
        geconstateerde te-strenge weigering) op basis van daadwerkelijk
        vandaag gemeten kosten: 2x positie-open/sluiten (~0,86 HBAR elk,
        gasUsed=761655 bij een echte open-transactie, sluiten als
        vergelijkbare aanname) + 2x swap (~0,20 HBAR elk, gemiddelde
        over 22 recente, echte swaps) = ~2,12 HBAR. VOORHEEN 6,0 HBAR,
        een ruwe schatting van 28 augustus zonder deze onderbouwing --
        die bleek de poort structureel te streng te maken (een
        gematigd, maar geldig signaal van combined_score=0.59 werd
        geweigerd puur door deze te hoge vaste kostenpost, terwijl de
        daadwerkelijke kosten van de heen-en-terug-cyclus veel lager
        liggen). AANNAME blijft: sluiten kost ongeveer evenveel als
        openen (geen aparte, empirische meting van een sluit-transactie
        beschikbaar op het moment van deze herijking).
    typical_width/fee_apr_at_typical_width: gebruikt om de IL/fee-impact
        in te schatten alsof de bot met een gebruikelijke breedte in de
        pool zou zijn gebleven -- zelfde aanpak als elders vandaag
        (analyze_range_width_full.py).
    """
    concentration = 1 / typical_width

    result = compute_gbm_confidence_interval(
        current_price=current_price,
        sentiment_mu=sentiment_mu,
        volatility_sigma=volatility_sigma,
        historical_hourly_volatility=historical_hourly_volatility,
        horizon_hours=horizon_hours,
    )

    price_ratio = result.expected_price / current_price
    il_v2 = compute_il_v2(price_ratio)  # altijd <= 0
    expected_il_avoided_hbar = -1 * capital_hbar * il_v2 * concentration  # positief bedrag

    expected_fee_income_foregone_hbar = capital_hbar * fee_apr_at_typical_width * (horizon_hours / (24 * 365))

    net_benefit_hbar = expected_il_avoided_hbar - expected_fee_income_foregone_hbar - round_trip_cost_hbar

    return ReflexEconomicsResult(
        should_proceed=net_benefit_hbar > 0,
        expected_il_avoided_hbar=expected_il_avoided_hbar,
        expected_fee_income_foregone_hbar=expected_fee_income_foregone_hbar,
        round_trip_cost_hbar=round_trip_cost_hbar,
        net_benefit_hbar=net_benefit_hbar,
    )


def compute_il_v2(price_ratio: float) -> float:
    """
    Standaard impermanent-loss-formule (V2-stijl), zelfde als elders
    vandaag (analyze_range_width_full.py) -- hier lokaal gedupliceerd om
    gbm_range_model.py als op-zichzelf-staande module te houden, zonder
    kruisverwijzing naar het analysescript.
    """
    if price_ratio <= 0:
        return 0.0
    return (2 * math.sqrt(price_ratio)) / (1 + price_ratio) - 1


def _normal_quantile(p: float) -> float:
    """
    Standaard-normaalverdelings-kwantielfunctie (inverse CDF), via de
    Acklam-benadering -- geen scipy-afhankelijkheid nodig. Nauwkeurig
    genoeg voor dit doel (foutmarge < 1.15e-9).
    """
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]

    p_low = 0.02425
    p_high = 1 - p_low

    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
