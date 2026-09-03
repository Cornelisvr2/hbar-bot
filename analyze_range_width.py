"""
analyze_range_width.py

Backtest: bij verschillende range-breedtes, hoe vaak zou de prijs eruit
lopen (op basis van echte historische HBAR-koersdata), en weegt de
extra fee-opbrengst van een smallere (dus geconcentreerdere) positie op
tegen de extra herbalancerings-kosten?

BELANGRIJKE KANTTEKENING: gebruikt HBAR/USD-historie als benadering.
De daadwerkelijk relevante schommeling is HBAR/SAUCE (SAUCE beweegt zelf
ook, onafhankelijk van USD) -- geen betrouwbare, diepe historische
HBAR/SAUCE-databron beschikbaar. Resultaten zijn dus een indicatie, geen
exacte voorspelling.
"""

from binance_klines_client import BinanceKlinesClient

# Empirisch gemeten fee-APR bij NORMAL/15%-breedte (GeckoTerminal,
# mainnet SAUCE/WHBAR 0.3%-pool, eerder deze week vastgesteld).
KNOWN_FEE_APR_AT_WIDTH = 0.0161
KNOWN_WIDTH = 0.15

# Empirisch vastgestelde kosten van een volledige close+open-cyclus
# (~2 HBAR, gemeten 24-26 aug 2026 op testnet) -- zelfde aanname als
# compute_economic_cooldown() elders in dit project.
REBALANCE_COST_HBAR = 2.0


def estimate_fee_apr_for_width(width: float) -> float:
    """
    Schaalt de bekende fee-APR naar een andere breedte, met de
    standaard Uniswap-V3-vuistregel: concentratie (en dus fee-opbrengst
    per eenheid kapitaal) is ruwweg omgekeerd evenredig met de breedte.
    Gekalibreerd op het enige echte, gemeten datapunt dat we hebben.
    """
    return KNOWN_FEE_APR_AT_WIDTH * (KNOWN_WIDTH / width)


def simulate_rebalance_frequency(prices: list[float], width: float) -> tuple[int, float]:
    """
    Simuleert: begin een range gecentreerd op de eerste prijs, loop door
    de historische prijzen, en tel hoe vaak de prijs de range verlaat
    (= een herbalancering, waarna een NIEUWE range wordt gestart
    gecentreerd op de prijs op dat moment).

    Geeft (aantal_herbalanceringen, gemiddelde_cyclusduur_in_uren) terug.
    """
    if not prices:
        return 0, 0.0

    rebalance_count = 0
    cycle_lengths = []
    cycle_start_idx = 0
    center_price = prices[0]
    lower_bound = center_price * (1 - width)
    upper_bound = center_price * (1 + width)

    for i, price in enumerate(prices):
        if price < lower_bound or price > upper_bound:
            rebalance_count += 1
            cycle_lengths.append(i - cycle_start_idx)
            cycle_start_idx = i
            center_price = price
            lower_bound = center_price * (1 - width)
            upper_bound = center_price * (1 + width)

    avg_cycle_hours = (sum(cycle_lengths) / len(cycle_lengths)) if cycle_lengths else len(prices)
    return rebalance_count, avg_cycle_hours


def main():
    client = BinanceKlinesClient()

    # Zoveel mogelijk historie ophalen voor een betekenisvolle steekproef
    # (Binance's limiet is 1000 candles per aanroep -- ~41 dagen aan
    # uurcandles in een keer).
    klines = client.get_klines("HBAR", interval="1h", limit=1000)
    prices = [k.close for k in klines]
    total_hours = len(prices)
    total_days = total_hours / 24

    print(f"Historische periode: {total_days:.1f} dagen ({total_hours} uurcandles)")
    print(f"Prijsrange in deze periode: {min(prices):.5f} -- {max(prices):.5f}")
    print()
    print(f"{'Breedte':>8} | {'Herbalanceringen':>17} | {'Gem. cyclus (u)':>16} | "
          f"{'Fee-APR':>8} | {'Fee-inkomst':>12} | {'Herbal.kosten':>14} | {'Netto':>10}")
    print("-" * 105)

    # Aanname voor de vergelijking: EUR 1000 aan kapitaal, omgerekend naar
    # HBAR tegen de koers van 27 aug 2026 ($0.07827/HBAR, EUR/USD ~1.08 --
    # dit is een benadering, geen exacte, actuele wisselkoers).
    CAPITAL_HBAR = 13798.0  # ~EUR 1000

    results = []
    for width_pct in [1, 3, 5, 7, 10, 15, 20, 30]:
        width = width_pct / 100
        rebalance_count, avg_cycle_hours = simulate_rebalance_frequency(prices, width)

        fee_apr = estimate_fee_apr_for_width(width)
        fee_income_hbar = CAPITAL_HBAR * fee_apr * (total_days / 365)
        rebalance_cost_total = rebalance_count * REBALANCE_COST_HBAR
        net_profit = fee_income_hbar - rebalance_cost_total

        results.append((width_pct, rebalance_count, avg_cycle_hours, fee_apr,
                         fee_income_hbar, rebalance_cost_total, net_profit))

        print(f"{width_pct:>6}% | {rebalance_count:>17} | {avg_cycle_hours:>16.1f} | "
              f"{fee_apr*100:>6.2f}% | {fee_income_hbar:>10.2f} H | "
              f"{rebalance_cost_total:>12.2f} H | {net_profit:>8.2f} H")

    best = max(results, key=lambda r: r[6])
    print()
    print(f"Beste breedte in deze simulatie: {best[0]}% "
          f"(netto {best[6]:.2f} HBAR over {total_days:.1f} dagen, "
          f"{CAPITAL_HBAR:.0f} HBAR kapitaal)")
    print()
    print("LET OP: gebaseerd op HBAR/USD-historie als benadering voor HBAR/SAUCE.")
    print("Fee-APR-schaling is een vuistregel, geen exacte, pool-specifieke meting.")


if __name__ == "__main__":
    main()
