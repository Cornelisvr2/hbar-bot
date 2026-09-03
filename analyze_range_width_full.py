"""
analyze_range_width_full.py

Uitgebreide versie van analyze_range_width.py -- rekent nu ALLE eerder
genoemde voorbehouden mee:
1. Impermanent loss (IL) per herbalancerings-cyclus.
2. Meerdere historische periodes.
3. Instelbare, apart aangeduide mainnet-vs-testnet-gaskosten-aanname.

BLIJFT EEN BENADERING, geen exacte voorspelling.
"""

import math
from binance_klines_client import BinanceKlinesClient

KNOWN_FEE_APR_AT_WIDTH = 0.0161
KNOWN_WIDTH = 0.15

# Bijgewerkt (27 aug 2026), op basis van een ECHTE, actieve HBAR/USDC-pool
# (0.15%-tier, mainnet, LARI+AUTO): APR schommelt in de praktijk tussen
# ~20% en ~220%, met een waarneming van 73.40% op het moment van meten.
# Dit is een heel andere, veel actievere pool dan onze eerdere,
# eenmalige SAUCE/WHBAR-0.3%-testnet-meting (1.61%) -- KNOWN_FEE_APR_AT_WIDTH
# hierboven blijft staan als losse referentie voor de EERDERE, smallere
# testnet-pool-analyses, maar voor het bullrun-scenario hieronder gebruiken
# we deze realistischere, bredere range.
BASE_APR_QUIET_MARKET = 0.20   # ondergrens van het waargenomen bereik
MAX_APR_STRONG_MOMENTUM = 2.20  # bovengrens van het waargenomen bereik
MOMENTUM_WINDOW_HOURS = 168  # 1 week, voor het meten van recent koersmomentum

REBALANCE_COST_HBAR_TESTNET = 2.0
# Bijgewerkt (27 aug 2026): "fees on main and testnet are believed to be
# the same" -- de eerdere, optimistischere mainnet-aanname (0.05 HBAR)
# was ongefundeerd. Gebruik overal de enige waarde die we daadwerkelijk
# empirisch hebben gemeten.
REBALANCE_COST_HBAR_MAINNET = REBALANCE_COST_HBAR_TESTNET


def estimate_fee_apr_for_width(width: float) -> float:
    return KNOWN_FEE_APR_AT_WIDTH * (KNOWN_WIDTH / width)


def estimate_dynamic_fee_apr(recent_momentum_pct: float, width: float) -> float:
    """
    Schat een APR die MEEBEWEEGT met recent koersmomentum (27 aug 2026,
    op observatie van de gebruiker: "als de crypto prijs omhoog gaat gaat
    de apr ook omhoog" -- bevestigd met echte, waargenomen data op een
    actieve HBAR/USDC-pool: APR schommelt tussen ~20% en ~220%,
    gecorreleerd met handelsactiviteit/volatiliteit).

    BELANGRIJKE CORRECTIE (27 aug 2026): de eerste versie van deze
    functie schaalde het waargenomen 20-220%-bereik ADDITIONEEL met de
    (KNOWN_WIDTH/breedte)-concentratiefactor -- maar die 20-220% komt van
    een "AUTO"-pool, die ZELF al een (onbekende, waarschijnlijk al vrij
    smalle) range beheert. Dat leidde tot een DUBBELE concentratie-
    toepassing en volstrekt onrealistische uitkomsten (>3000% APR bij
    1%-breedte). Zonder te weten welke breedte de AUTO-pool daadwerkelijk
    gebruikt, is verdere schaling niet te onderbouwen -- deze functie
    gebruikt het waargenomen bereik nu DIRECT, ongeacht de geteste
    breedte. Dit is zelf ook een vereenvoudiging (een striktere breedte
    zou in werkelijkheid waarschijnlijk wel een hogere APR geven dan een
    bredere), maar voorkomt de eerdere, aantoonbaar absurde uitkomst.

    recent_momentum_pct: prijsverandering over de laatste
    MOMENTUM_WINDOW_HOURS, als fractie (bv. 0.10 voor +10%).
    """
    momentum_abs = abs(recent_momentum_pct)
    scale = min(momentum_abs / 0.20, 1.0)
    return BASE_APR_QUIET_MARKET + scale * (MAX_APR_STRONG_MOMENTUM - BASE_APR_QUIET_MARKET)


def compute_il_v2(price_ratio: float) -> float:
    if price_ratio <= 0:
        return 0.0
    return (2 * math.sqrt(price_ratio)) / (1 + price_ratio) - 1


def simulate_full(prices, width, capital_hbar, rebalance_cost_hbar,
                    time_in_lp_mode_fraction=1.0):
    """
    time_in_lp_mode_fraction: welk deel van de tijd de bot daadwerkelijk
    in LP_MODE zit (i.p.v. BULLISH_REFLEX/BEARISH_REFLEX, die door
    SENTIMENT worden getriggerd, niet door prijsbeweging -- we hebben
    geen historische sentiment-data om dit exact terug te testen, dus
    dit is een INSTELBARE aanname, geen gemeten waarde. Tijd buiten
    LP_MODE verdient geen fees (wel mogelijk koerswinst, die HIER niet
    wordt meegerekend -- dat is een apart soort rendement).
    """
    if len(prices) < 2:
        return {"rebalances": 0, "fee_income": 0.0, "il_loss": 0.0,
                "rebalance_cost": 0.0, "net": 0.0}

    rebalance_count = 0
    total_il_loss = 0.0
    center_price = prices[0]
    lower_bound = center_price * (1 - width)
    upper_bound = center_price * (1 + width)

    concentration_factor = 1 / width
    fee_apr = estimate_fee_apr_for_width(width)

    for price in prices:
        if price < lower_bound or price > upper_bound:
            price_ratio = price / center_price
            il_v2 = compute_il_v2(price_ratio)
            il_cycle_hbar = capital_hbar * il_v2 * concentration_factor
            total_il_loss += il_cycle_hbar

            rebalance_count += 1
            center_price = price
            lower_bound = center_price * (1 - width)
            upper_bound = center_price * (1 + width)

    total_days = len(prices) / 24
    fee_income = capital_hbar * fee_apr * (total_days / 365) * time_in_lp_mode_fraction
    # IL treedt alleen op TERWIJL de positie open staat (dus ook geschaald).
    total_il_loss *= time_in_lp_mode_fraction
    rebalance_cost_total = rebalance_count * rebalance_cost_hbar
    net = fee_income + total_il_loss - rebalance_cost_total

    return {
        "rebalances": rebalance_count,
        "fee_income": fee_income,
        "il_loss": total_il_loss,
        "rebalance_cost": rebalance_cost_total,
        "net": net,
    }


def generate_trending_prices(start_price: float, total_move_pct: float,
                               hours: int, noise_pct: float = 0.0005) -> list:
    """
    Genereert een HYPOTHETISCHE, aanhoudend trendende prijsreeks -- GEEN
    voorspelling, puur een gevoeligheidsscenario om te zien hoe de
    LP-strategie zich zou gedragen bij een aanhoudende richting (i.p.v.
    de historische, gemengde op-en-neer-bewegingen die de eerdere
    backtest gebruikte).

    total_move_pct: totale koersbeweging over de hele periode (bv. 0.50
    voor +50%).
    noise_pct: kleine, willekeurige ruis per uur bovenop de trend, om een
    volledig kunstmatige, perfect gladde lijn te vermijden.

    LET OP (27 aug 2026): deze functie gebruikt bewust WEINIG ruis (een
    bijna gladde lijn), wat een echte bullrun niet goed weergeeft (die
    kent doorgaans stevige tussentijdse terugvallen). Voor een
    realistischer scenario, zie generate_realistic_bullrun() hieronder.
    """
    import random
    random.seed(27)
    hourly_drift = (1 + total_move_pct) ** (1 / hours) - 1
    prices = [start_price]
    for _ in range(hours - 1):
        noise = random.uniform(-noise_pct, noise_pct)
        prices.append(prices[-1] * (1 + hourly_drift + noise))
    return prices


def generate_realistic_bullrun(start_price: float, total_move_pct: float, hours: int,
                                 hourly_volatility: float, seed: int) -> list:
    """
    Genereert een REALISTISCHERE bullrun dan generate_trending_prices():
    gebruikt de daadwerkelijk GEMETEN uurvolatiliteit (via de aanroeper
    aangeleverd, typisch ~0.6% voor HBAR) i.p.v. een arbitraire, te lage
    ruis-aanname -- dit geeft realistische tussentijdse terugvallen
    (drawdowns), zoals een echte bullrun kent, i.p.v. een kunstmatig
    gladde lijn.

    Corrigeert voor "volatiliteits-sleep" (een bekend effect uit de
    financiele wiskunde: bij willekeurige, samengestelde stappen ligt het
    gemiddelde eindresultaat structureel lager dan de naieve som van de
    drift, tenzij je +sigma^2/2 per stap compenseert).

    GEEN enkel pad is representatief op zich -- gebruik meerdere seeds
    (Monte-Carlo) voor een betrouwbaarder beeld van gemiddelde en
    spreiding.
    """
    import random as _random
    rng = _random.Random(seed)
    target_log_return = math.log(1 + total_move_pct)
    hourly_drift = target_log_return / hours + (hourly_volatility ** 2) / 2
    prices = [start_price]
    for _ in range(hours - 1):
        noise = rng.gauss(0, hourly_volatility)
        prices.append(prices[-1] * (1 + hourly_drift + noise))
    return prices



def compute_lp_value_eur(prices: list, width: float, capital_eur: float,
                           hold_value_eur: float, rebalance_cost_eur: float) -> tuple:
    """
    Berekent de LP-eindwaarde in euro's, CORRECT en consistent (27 aug
    2026 -- vervangt een eerdere, foutieve versie die HBAR-hoeveelheid
    en waarde-index door elkaar haalde, wat tot een dubbeltelling van de
    koersstijging leidde).
    """
    fee_apr = estimate_fee_apr_for_width(width)
    concentration = 1 / width

    value_index = 1.0
    center_price = prices[0]
    lower_bound = center_price * (1 - width)
    upper_bound = center_price * (1 + width)
    rebalance_count = 0

    for price in prices:
        if price < lower_bound or price > upper_bound:
            price_ratio = price / center_price
            il_v2 = compute_il_v2(price_ratio)
            value_index *= (1 + il_v2 * concentration)
            value_index = max(value_index, 0.0)

            rebalance_count += 1
            center_price = price
            lower_bound = center_price * (1 - width)
            upper_bound = center_price * (1 + width)

    total_days = len(prices) / 24
    fee_fraction = fee_apr * (total_days / 365)

    lp_value_eur = (value_index * hold_value_eur) + (fee_fraction * capital_eur)
    lp_value_eur -= rebalance_count * rebalance_cost_eur

    return lp_value_eur, rebalance_count


def compute_lp_value_eur_dynamic_apr(prices: list, width: float, capital_eur: float,
                                       hold_value_eur: float, rebalance_cost_eur: float) -> tuple:
    """
    Zelfde als compute_lp_value_eur(), maar met een APR die UUR-VOOR-UUR
    meebeweegt met recent koersmomentum (27 aug 2026), i.p.v. een vaste
    waarde -- op observatie van de gebruiker, bevestigd met echte
    pool-data: fee-APR stijgt merkbaar tijdens sterkere koersbewegingen
    (meer handelsvolume/activiteit).
    """
    concentration = 1 / width

    value_index = 1.0
    center_price = prices[0]
    lower_bound = center_price * (1 - width)
    upper_bound = center_price * (1 + width)
    rebalance_count = 0
    accumulated_fee_fraction = 0.0

    for i, price in enumerate(prices):
        # Momentum over het afgelopen MOMENTUM_WINDOW_HOURS-venster.
        window_start_idx = max(0, i - MOMENTUM_WINDOW_HOURS)
        momentum = (price - prices[window_start_idx]) / prices[window_start_idx] \
            if prices[window_start_idx] != 0 else 0.0

        hourly_apr = estimate_dynamic_fee_apr(momentum, width)
        accumulated_fee_fraction += hourly_apr / (365 * 24)  # APR omgerekend naar dit ene uur

        if price < lower_bound or price > upper_bound:
            price_ratio = price / center_price
            il_v2 = compute_il_v2(price_ratio)
            value_index *= (1 + il_v2 * concentration)
            value_index = max(value_index, 0.0)

            rebalance_count += 1
            center_price = price
            lower_bound = center_price * (1 - width)
            upper_bound = center_price * (1 + width)

    lp_value_eur = (value_index * hold_value_eur) + (accumulated_fee_fraction * capital_eur)
    lp_value_eur -= rebalance_count * rebalance_cost_eur

    return lp_value_eur, rebalance_count


def simulate_adaptive_strategy_eur(prices: list, width: float, capital_eur: float,
                                     rebalance_cost_eur: float,
                                     bullish_momentum_threshold: float = 0.10,
                                     momentum_window_hours: int = MOMENTUM_WINDOW_HOURS) -> dict:
    """
    Simuleert de DAADWERKELIJKE, ontworpen strategie van de bot (27 aug
    2026): LP_MODE tijdens rustige periodes, volledig HBAR (vasthouden)
    zodra recent momentum de bullish-drempel overschrijdt -- net als
    BULLISH_REFLEX, maar hier gestuurd door PRIJSMOMENTUM i.p.v. het
    daadwerkelijke sentiment-systeem (waar we geen historische data van
    hebben om exact terug te testen). De drempel (10% over 1 week) is een
    REDELIJKE AANNAME, niet de exacte, echte drempel van het
    sentiment-systeem.
    """
    concentration = 1 / width
    value_index = 1.0
    accumulated_fee_fraction = 0.0
    state = "LP"
    center_price = prices[0]
    lower_bound = center_price * (1 - width)
    upper_bound = center_price * (1 + width)
    rebalance_count = 0
    mode_switch_count = 0
    hours_in_lp = 0
    hours_in_reflex = 0

    for i, price in enumerate(prices):
        window_start_idx = max(0, i - momentum_window_hours)
        momentum = (price - prices[window_start_idx]) / prices[window_start_idx] \
            if prices[window_start_idx] != 0 else 0.0

        desired_state = "REFLEX" if momentum > bullish_momentum_threshold else "LP"
        if desired_state != state:
            mode_switch_count += 1
            state = desired_state
            if state == "LP":
                center_price = price
                lower_bound = center_price * (1 - width)
                upper_bound = center_price * (1 + width)

        if state == "REFLEX":
            hours_in_reflex += 1
            if i > 0:
                value_index *= (price / prices[i - 1])
        else:
            hours_in_lp += 1
            hourly_apr = estimate_dynamic_fee_apr(momentum, width)
            accumulated_fee_fraction += hourly_apr / (365 * 24)

            if price < lower_bound or price > upper_bound:
                price_ratio = price / center_price
                il_v2 = compute_il_v2(price_ratio)
                value_index *= (1 + il_v2 * concentration)
                value_index = max(value_index, 0.0)

                rebalance_count += 1
                center_price = price
                lower_bound = center_price * (1 - width)
                upper_bound = center_price * (1 + width)

    final_value_eur = (value_index * capital_eur) + (accumulated_fee_fraction * capital_eur)
    final_value_eur -= rebalance_count * rebalance_cost_eur

    return {
        "final_value_eur": final_value_eur,
        "rebalance_count": rebalance_count,
        "mode_switch_count": mode_switch_count,
        "hours_in_lp": hours_in_lp,
        "hours_in_reflex": hours_in_reflex,
    }


def simulate_fast_reactive_strategy_eur(prices: list, width: float, capital_eur: float,
                                          rebalance_cost_eur: float,
                                          entry_window_hours: int = 6,
                                          entry_threshold: float = 0.03,
                                          exit_window_hours: int = 6,
                                          exit_threshold: float = 0.01) -> dict:
    """
    Snelle-reactie-variant (27 aug 2026, op verzoek): reageert op een
    PLOTSELINGE, korte-termijn koersbeweging (bv. "Bitcoin schiet een
    paar % omhoog na FED-nieuws"), i.p.v. een langzaam opbouwend
    week-momentum. Sluit ook sneller weer aan bij LP_MODE zodra de
    beweging afkoelt -- APARTE, kortere vensters voor instappen en
    uitstappen, in plaats van een enkele symmetrische drempel.

    Dit is een betere proxy voor hoe de ECHTE BULLISH_REFLEX ontworpen
    is (sentiment ververst elke 5 minuten, reageert op nieuws), dan de
    eerdere, week-lange-momentum-versie -- maar blijft een BENADERING:
    we hebben geen historische sentiment-data om de exacte gevoeligheid
    van het echte systeem te bevestigen.

    entry_threshold/entry_window_hours: hoe snel/sterk een beweging moet
    zijn om IN te stappen (naar 100% HBAR).
    exit_threshold/exit_window_hours: hoe zwak de RECENTE beweging moet
    zijn geworden om er weer UIT te stappen (terug naar LP_MODE).
    """
    concentration = 1 / width
    value_index = 1.0
    accumulated_fee_fraction = 0.0
    state = "LP"
    center_price = prices[0]
    lower_bound = center_price * (1 - width)
    upper_bound = center_price * (1 + width)
    rebalance_count = 0
    mode_switch_count = 0
    hours_in_lp = 0
    hours_in_reflex = 0

    for i, price in enumerate(prices):
        entry_idx = max(0, i - entry_window_hours)
        entry_momentum = (price - prices[entry_idx]) / prices[entry_idx] \
            if prices[entry_idx] != 0 else 0.0

        exit_idx = max(0, i - exit_window_hours)
        exit_momentum = (price - prices[exit_idx]) / prices[exit_idx] \
            if prices[exit_idx] != 0 else 0.0

        if state == "LP":
            desired_state = "REFLEX" if entry_momentum > entry_threshold else "LP"
        else:
            desired_state = "LP" if exit_momentum < exit_threshold else "REFLEX"

        if desired_state != state:
            mode_switch_count += 1
            state = desired_state
            if state == "LP":
                center_price = price
                lower_bound = center_price * (1 - width)
                upper_bound = center_price * (1 + width)

        if state == "REFLEX":
            hours_in_reflex += 1
            if i > 0:
                value_index *= (price / prices[i - 1])
        else:
            hours_in_lp += 1
            hourly_apr = estimate_dynamic_fee_apr(entry_momentum, width)
            accumulated_fee_fraction += hourly_apr / (365 * 24)

            if price < lower_bound or price > upper_bound:
                price_ratio = price / center_price
                il_v2 = compute_il_v2(price_ratio)
                value_index *= (1 + il_v2 * concentration)
                value_index = max(value_index, 0.0)

                rebalance_count += 1
                center_price = price
                lower_bound = center_price * (1 - width)
                upper_bound = center_price * (1 + width)

    final_value_eur = (value_index * capital_eur) + (accumulated_fee_fraction * capital_eur)
    final_value_eur -= rebalance_count * rebalance_cost_eur

    return {
        "final_value_eur": final_value_eur,
        "rebalance_count": rebalance_count,
        "mode_switch_count": mode_switch_count,
        "hours_in_lp": hours_in_lp,
        "hours_in_reflex": hours_in_reflex,
    }








def run_analysis(prices, capital_hbar, rebalance_cost_hbar, period_label,
                   time_in_lp_mode_fraction=1.0):
    total_days = len(prices) / 24
    print(f"\n=== {period_label} ({total_days:.1f} dagen, "
          f"prijs {min(prices):.5f}--{max(prices):.5f}, "
          f"{time_in_lp_mode_fraction*100:.0f}% van de tijd in LP_MODE) ===")
    print(f"{'Breedte':>8} | {'Herbal.':>8} | {'Fee-ink.':>10} | {'IL-verlies':>11} | "
          f"{'Herbal.kst':>11} | {'Netto':>10}")
    print("-" * 75)

    results = []
    for width_pct in [1, 3, 5, 7, 10, 15, 20, 30]:
        width = width_pct / 100
        r = simulate_full(prices, width, capital_hbar, rebalance_cost_hbar,
                            time_in_lp_mode_fraction)
        results.append((width_pct, r))
        print(f"{width_pct:>6}% | {r['rebalances']:>8} | {r['fee_income']:>8.2f} H | "
              f"{r['il_loss']:>9.2f} H | {r['rebalance_cost']:>9.2f} H | {r['net']:>8.2f} H")

    best = max(results, key=lambda x: x[1]["net"])
    print(f"Beste breedte: {best[0]}% (netto {best[1]['net']:.2f} HBAR)")
    return best


def run_bullrun_monte_carlo(start_price: float, total_move_pct: float, hours: int,
                              hourly_volatility: float, capital_eur: float,
                              rebalance_cost_hbar_eur: float, n_paths: int = 20):
    """
    Draait n_paths onafhankelijke, willekeurige koerspaden voor hetzelfde
    bedoelde totale koerseffect, en rapporteert gemiddelde + spreiding --
    een enkel willekeurig pad is NIET representatief op zich.

    Vergelijkt DRIE strategieen: puur vasthouden, altijd LP'en (beste
    breedte), en de ADAPTIEVE strategie (LP tijdens rust, HBAR bij
    momentum -- de daadwerkelijk ontworpen botstrategie).
    """
    hold_results = []
    lp_results_by_width = {w: [] for w in [1, 3, 5, 7, 10, 15, 20, 30]}
    adaptive_results_by_width = {w: [] for w in [1, 3, 5, 7, 10, 15, 20, 30]}
    fast_reactive_results_by_width = {w: [] for w in [1, 3, 5, 7, 10, 15, 20, 30]}
    actual_moves = []
    max_drawdowns = []

    for seed in range(n_paths):
        prices = generate_realistic_bullrun(start_price, total_move_pct, hours,
                                              hourly_volatility, seed=seed)
        actual_move = prices[-1] / prices[0] - 1
        actual_moves.append(actual_move)

        peak = prices[0]
        max_dd = 0.0
        for p in prices:
            if p > peak:
                peak = p
            dd = (p - peak) / peak
            if dd < max_dd:
                max_dd = dd
        max_drawdowns.append(max_dd)

        hold_value_eur = capital_eur * (1 + actual_move)
        hold_results.append(hold_value_eur)

        for width_pct in lp_results_by_width:
            width = width_pct / 100
            lp_value, _ = compute_lp_value_eur_dynamic_apr(
                prices, width, capital_eur, hold_value_eur, rebalance_cost_hbar_eur
            )
            lp_results_by_width[width_pct].append(lp_value)

            adaptive_result = simulate_adaptive_strategy_eur(
                prices, width, capital_eur, rebalance_cost_hbar_eur
            )
            adaptive_results_by_width[width_pct].append(adaptive_result["final_value_eur"])

            fast_result = simulate_fast_reactive_strategy_eur(
                prices, width, capital_eur, rebalance_cost_hbar_eur
            )
            fast_reactive_results_by_width[width_pct].append(fast_result["final_value_eur"])

    avg_hold = sum(hold_results) / n_paths
    avg_actual_move = sum(actual_moves) / n_paths
    avg_max_dd = sum(max_drawdowns) / n_paths

    print(f"  Gemiddelde daadwerkelijke stijging over {n_paths} paden: "
          f"{avg_actual_move*100:.1f}% (bedoeld: {total_move_pct*100:.0f}%)")
    print(f"  Gemiddelde grootste tussentijdse terugval: {avg_max_dd*100:.1f}%")
    print(f"  Gewoon vasthouden: EUR {capital_eur:.0f} -> gemiddeld EUR {avg_hold:.0f} "
          f"(spreiding: {min(hold_results):.0f}--{max(hold_results):.0f})")

    best_width, best_avg = None, float("-inf")
    for width_pct, values in lp_results_by_width.items():
        avg_lp = sum(values) / n_paths
        if avg_lp > best_avg:
            best_avg = avg_lp
            best_width = width_pct

    values = lp_results_by_width[best_width]
    print(f"  Altijd LP'en op {best_width}% (beste gemiddelde): gemiddeld EUR {best_avg:.0f} "
          f"(spreiding: {min(values):.0f}--{max(values):.0f})")

    best_adaptive_width, best_adaptive_avg = None, float("-inf")
    for width_pct, values in adaptive_results_by_width.items():
        avg_adaptive = sum(values) / n_paths
        if avg_adaptive > best_adaptive_avg:
            best_adaptive_avg = avg_adaptive
            best_adaptive_width = width_pct

    adaptive_values = adaptive_results_by_width[best_adaptive_width]
    print(f"  ADAPTIEF (LP bij rust, HBAR bij momentum) op {best_adaptive_width}%: "
          f"gemiddeld EUR {best_adaptive_avg:.0f} "
          f"(spreiding: {min(adaptive_values):.0f}--{max(adaptive_values):.0f})")

    best_fast_width, best_fast_avg = None, float("-inf")
    for width_pct, values in fast_reactive_results_by_width.items():
        avg_fast = sum(values) / n_paths
        if avg_fast > best_fast_avg:
            best_fast_avg = avg_fast
            best_fast_width = width_pct

    fast_values = fast_reactive_results_by_width[best_fast_width]
    print(f"  SNEL-REACTIEF (korte in/uitstap-vensters) op {best_fast_width}%: "
          f"gemiddeld EUR {best_fast_avg:.0f} "
          f"(spreiding: {min(fast_values):.0f}--{max(fast_values):.0f})")

    return avg_hold, best_avg, best_adaptive_avg, best_fast_avg


def main():
    client = BinanceKlinesClient()
    CAPITAL_HBAR = 13798.0

    klines_recent = client.get_klines("HBAR", interval="1h", limit=1000)
    prices_recent = [k.close for k in klines_recent]

    print(f"Kapitaal: {CAPITAL_HBAR:.0f} HBAR (~EUR 1000)")

    print("\n" + "=" * 75)
    print(f"GASKOSTEN-AANNAME ({REBALANCE_COST_HBAR_TESTNET:.2f} HBAR per herbalancering, "
          f"empirisch gemeten op testnet -- 'fees on main and testnet are believed to be the same')")
    print("=" * 75)
    run_analysis(prices_recent, CAPITAL_HBAR, REBALANCE_COST_HBAR_TESTNET, "Meest recente periode")

    print("\n" + "=" * 75)
    print("SCENARIO'S: tijd buiten LP_MODE (BULLISH_REFLEX/BEARISH_REFLEX)")
    print("GEEN gemeten waarde -- we hebben geen historische sentiment-data")
    print("om dit terug te testen. Puur indicatieve scenario's.")
    print("=" * 75)
    for fraction in [1.0, 0.9, 0.75, 0.5]:
        run_analysis(prices_recent, CAPITAL_HBAR, REBALANCE_COST_HBAR_MAINNET,
                      "Meest recente periode", time_in_lp_mode_fraction=fraction)

    older_end_time = klines_recent[0].open_time
    klines_older = client.get_klines(
        "HBAR", interval="1h", limit=1000, end_time=older_end_time
    )
    prices_older = [k.close for k in klines_older]
    if len(prices_older) > 10:
        print("\n" + "=" * 75)
        print("TWEEDE, OUDERE PERIODE (ter controle van stabiliteit) -- mainnet-aanname")
        print("=" * 75)
        run_analysis(prices_older, CAPITAL_HBAR, REBALANCE_COST_HBAR_MAINNET, "Oudere periode")

    print("\n" + "=" * 75)
    print("REALISTISCH BULLRUN-SCENARIO (Monte-Carlo, 20 willekeurige paden per")
    print("scenario, met de DAADWERKELIJK GEMETEN uurvolatiliteit van HBAR --")
    print("GEEN voorspelling, puur illustratief. Kapitaal in EUR, correct")
    print("consistent doorgerekend, geen dubbeltelling van koerseffect.)")
    print("=" * 75)
    start_price = prices_recent[-1]  # meest recente, actuele prijs als startpunt
    CAPITAL_EUR = 1000.0
    HOURLY_VOL = 0.006072  # daadwerkelijk gemeten, 27 aug 2026
    REBALANCE_COST_EUR = REBALANCE_COST_HBAR_MAINNET * start_price  # nu gelijk aan de gemeten testnet-waarde
    HOURS_6_MONTHS = 6 * 30 * 24

    for move_pct in [0.25, 0.50, 1.00, 2.00]:
        print(f"\n--- HBAR stijgt gemiddeld {move_pct*100:.0f}% over 6 maanden ---")
        run_bullrun_monte_carlo(
            start_price, move_pct, HOURS_6_MONTHS, HOURLY_VOL,
            CAPITAL_EUR, REBALANCE_COST_EUR, n_paths=20
        )


if __name__ == "__main__":
    main()
