"""
apr_historie.py -- gemiddelde/lage/hoge fee-APR uit de POOL-historie.

De bot bewaart de fee-APR niet historisch. Maar GeckoTerminal heeft het
dagelijkse pool-VOLUME (get_historical_ohlcv), en met de TVL en SaucerSwap's
eigen formule (compute_fees_apr) reconstrueren we de fee-APR per dag vanaf
het begin van de pool. Daaruit: laag (25e percentiel), gemiddeld (mediaan),
hoog (75e percentiel) -> een eerlijke lage/midden/hoge muntjes-prognose i.p.v.
één APR-getal.

    docker compose run --rm -T hbar-bot python3 apr_historie.py
    docker compose run --rm -T hbar-bot python3 apr_historie.py --dagen 180 --json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def pct(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, int(p / 100 * len(sorted_vals)))
    return sorted_vals[i]


def main():
    a = sys.argv
    dagen = int(a[a.index("--dagen") + 1]) if "--dagen" in a else 365
    json_uit = "--json" in sys.argv
    from geckoterminal_client import GeckoTerminalClient
    from lp_manager import compute_fees_apr
    import config
    fee_tier = int(os.environ.get("LP_FEE_TIER", "3000"))

    gecko = GeckoTerminalClient()
    # dagelijkse candles ophalen (volume per dag)
    candles = gecko.fetch_full_history(timeframe="day", total_candles_needed=dagen, pause_seconds=1.0)
    if not candles:
        print("Geen pool-historie van GeckoTerminal."); return
    # actuele TVL als benadering voor L_bal (de pool-liquiditeit); wisselt over
    # tijd, maar als benadering voor de spreiding volstaat het.
    snap = gecko.get_pool_snapshot()
    tvl = getattr(snap, "liquidity_usd", None) or getattr(snap, "reserve_usd", None) or 3_000_000.0

    apr_per_dag = []
    for c in candles:
        if c.volume and c.volume > 0:
            apr = compute_fees_apr(c.volume, fee_tier, tvl)
            apr_per_dag.append(apr)
    apr_per_dag.sort()
    n = len(apr_per_dag)
    if n < 10:
        print(f"Te weinig dagen met volume ({n})."); return

    laag = pct(apr_per_dag, 25)
    mid = pct(apr_per_dag, 50)
    hoog = pct(apr_per_dag, 75)
    gem = sum(apr_per_dag) / n

    res = {"dagen": n, "tvl_gebruikt": round(tvl), "fee_tier": fee_tier,
           "apr_laag_p25": round(laag * 100, 1), "apr_mediaan": round(mid * 100, 1),
           "apr_hoog_p75": round(hoog * 100, 1), "apr_gemiddeld": round(gem * 100, 1)}
    if json_uit:
        print(json.dumps(res)); return
    print(f"\nFee-APR-historie uit pool-volume (GeckoTerminal), {n} dagen")
    print(f"TVL-benadering: ${tvl:,.0f} | fee-tier {fee_tier/10000:.2f}%\n")
    print(f"  Laag (p25):     {laag*100:5.1f}%")
    print(f"  Mediaan:        {mid*100:5.1f}%")
    print(f"  Gemiddeld:      {gem*100:5.1f}%")
    print(f"  Hoog (p75):     {hoog*100:5.1f}%")
    print("\nGebruik voor de muntjes-prognose: laag/mediaan/hoog -> drie scenario's")
    print("i.p.v. één APR. LET OP: TVL is de HUIDIGE waarde als benadering; de")
    print("echte TVL wisselde over tijd, dus de absolute % zijn indicatief. De")
    print("spreiding (hoe wisselvallig de APR is) is wel betrouwbaar.")


if __name__ == "__main__":
    main()
