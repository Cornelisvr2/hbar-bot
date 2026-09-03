"""
analyze_dca_monthly.py

Rekent door wat er gebeurt als je naast de initiele EUR 1000 inleg, elke
maand nog eens EUR 100 bijstort -- voor alle vier eerder onderzochte
strategieen (vasthouden, altijd LP'en, adaptief, snel-reactief).

Elke storting heeft zijn EIGEN, kortere periode om te groeien (een
storting in maand 5 heeft nog maar 1 maand de tijd, de eerste EUR 1000
draait de volle 6 maanden mee) -- dit wordt gemodelleerd door voor elke
storting een APARTE simulatie te draaien op het resterende deel van
dezelfde koersreeks, en de eindresultaten op te tellen.
"""

from analyze_range_width_full import (
    generate_realistic_bullrun, compute_lp_value_eur_dynamic_apr,
    simulate_adaptive_strategy_eur, simulate_fast_reactive_strategy_eur,
)

HOURS_PER_MONTH = 30 * 24
INITIAL_DEPOSIT_EUR = 1000.0
MONTHLY_DEPOSIT_EUR = 100.0
N_MONTHS = 6
REBALANCE_COST_HBAR = 2.0  # empirisch gemeten, zelfde als elders vandaag
DEFAULT_WIDTH = 0.30  # HIGH/breed, de breedte die in de meeste 6-maands-scenario's het best presteerde


def compute_single_deposit_value(prices_subpath: list, strategy: str, amount_eur: float,
                                   rebalance_cost_eur: float, width: float = DEFAULT_WIDTH) -> float:
    """Berekent de eindwaarde van EEN storting, over het resterende prijspad vanaf zijn eigen instapmoment."""
    if len(prices_subpath) < 2:
        return amount_eur  # geen tijd meer om te groeien

    actual_move = prices_subpath[-1] / prices_subpath[0] - 1
    hold_value_eur = amount_eur * (1 + actual_move)

    if strategy == "hold":
        return hold_value_eur
    elif strategy == "lp":
        value, _ = compute_lp_value_eur_dynamic_apr(
            prices_subpath, width, amount_eur, hold_value_eur, rebalance_cost_eur
        )
        return value
    elif strategy == "adaptive":
        result = simulate_adaptive_strategy_eur(prices_subpath, width, amount_eur, rebalance_cost_eur)
        return result["final_value_eur"]
    elif strategy == "fast":
        result = simulate_fast_reactive_strategy_eur(prices_subpath, width, amount_eur, rebalance_cost_eur)
        return result["final_value_eur"]
    else:
        raise ValueError(f"Onbekende strategie: {strategy}")


def simulate_dca(prices: list, strategy: str, rebalance_cost_eur: float) -> tuple:
    """
    Simuleert de initiele storting + N_MONTHS-1 maandelijkse bijstortingen
    (de laatste storting gebeurt aan het begin van de laatste maand, zodat
    die nog minstens 1 maand de tijd heeft om te groeien).
    """
    total_invested = INITIAL_DEPOSIT_EUR
    total_final_value = compute_single_deposit_value(
        prices, strategy, INITIAL_DEPOSIT_EUR, rebalance_cost_eur
    )

    for month in range(1, N_MONTHS):
        start_hour = month * HOURS_PER_MONTH
        if start_hour >= len(prices):
            break
        subpath = prices[start_hour:]
        deposit_value = compute_single_deposit_value(
            subpath, strategy, MONTHLY_DEPOSIT_EUR, rebalance_cost_eur
        )
        total_final_value += deposit_value
        total_invested += MONTHLY_DEPOSIT_EUR

    return total_final_value, total_invested


def main():
    start_price = 0.078  # meest recente, actuele prijs als startpunt
    hourly_volatility = 0.006072  # daadwerkelijk gemeten, 27 aug 2026
    hours = N_MONTHS * HOURS_PER_MONTH
    rebalance_cost_eur = REBALANCE_COST_HBAR * start_price
    n_paths = 20

    print(f"Initiele inleg: EUR {INITIAL_DEPOSIT_EUR:.0f}, plus EUR {MONTHLY_DEPOSIT_EUR:.0f} "
          f"per maand (maand 1 t/m {N_MONTHS-1})")
    print(f"Totaal ingelegd na {N_MONTHS} maanden: EUR "
          f"{INITIAL_DEPOSIT_EUR + (N_MONTHS-1)*MONTHLY_DEPOSIT_EUR:.0f}")
    print()

    strategies = ["hold", "lp", "adaptive", "fast"]
    strategy_labels = {
        "hold": "Vasthouden",
        "lp": "Altijd LP'en",
        "adaptive": "Adaptief (traag)",
        "fast": "Snel-reactief",
    }

    for move_pct in [0.25, 0.50, 1.00, 2.00]:
        print(f"=== HBAR stijgt gemiddeld {move_pct*100:.0f}% over {N_MONTHS} maanden ===")

        results_by_strategy = {s: [] for s in strategies}
        for seed in range(n_paths):
            prices = generate_realistic_bullrun(start_price, move_pct, hours, hourly_volatility, seed=seed)
            for strategy in strategies:
                final_value, total_invested = simulate_dca(prices, strategy, rebalance_cost_eur)
                results_by_strategy[strategy].append((final_value, total_invested))

        for strategy in strategies:
            values = [r[0] for r in results_by_strategy[strategy]]
            avg_value = sum(values) / n_paths
            total_invested = results_by_strategy[strategy][0][1]  # zelfde voor elk pad
            profit_pct = (avg_value - total_invested) / total_invested * 100
            print(f"  {strategy_labels[strategy]:>18}: gemiddeld EUR {avg_value:.0f} "
                  f"(ingelegd: EUR {total_invested:.0f}, winst: {profit_pct:+.1f}%) "
                  f"(spreiding: {min(values):.0f}--{max(values):.0f})")
        print()


if __name__ == "__main__":
    main()
