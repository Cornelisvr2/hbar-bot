"""
backtest_crash_stop.py -- crash-bescherming: bij welke drempel werkt het?

Doel: bij een ECHTE crash automatisch uit de pool naar USDC, om de stapel
te beschermen -- maar NIET vals afgaan op gewone dips (dat zou muntjes
kosten door verkopen-laag/terugkopen-hoog). Deze backtest zoekt de drempel
die de grote klappen vangt met zo min mogelijk valse triggers.

Regel:
  - CRASH als het rendement over CRASH_UREN <= -DREMPEL% (bijv. -20% in 24u).
  - dan naar USDC; blijf daar tot de koers STABILISEERT (HERSTEL_UREN lang
    geen nieuwe daling / weer een hogere close) -> terug naar de pool.
Meet over de HBAR-candles, in muntjes, vs altijd-in-de-pool.

    docker compose run --rm -T hbar-bot python3 backtest_crash_stop.py
"""
import asyncio
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
INLEG = 40000.0  # muntjes; schaal maakt niet uit, we kijken naar %


async def laad_uur():
    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    async with db._pool.acquire() as conn:
        rows = await conn.fetch("SELECT ts, close FROM candles_5m WHERE symbol='HBAR' ORDER BY ts")
    uur = []
    blok = []
    for r in rows:
        blok.append(r["close"])
        if len(blok) == 12:
            uur.append(blok[-1]); blok = []
    return uur


def simuleer(c, crash_uren, drempel, herstel_uren, fee, apr):
    n = len(c)
    dag_apr = apr / 100 / (365 * 24)
    munt = INLEG
    in_pool = True
    laag_sinds = 0
    usdc_sinds = -1
    swaps = 0
    crashes = []
    for i in range(1, n):
        if in_pool:
            ret = c[i] / c[i - 1]
            il = 2 * math.sqrt(ret) / (1 + ret)
            munt = munt * il * (1 + dag_apr * 0.70)
        if i < crash_uren:
            continue
        rend = c[i] / c[i - crash_uren] - 1
        if in_pool and rend <= -drempel:
            munt *= (1 - fee); in_pool = False; usdc_sinds = i; swaps += 1
            crashes.append((i, rend * 100))
        elif not in_pool:
            # stabilisatie: herstel_uren lang niet lager dan het dieptepunt
            recent = c[max(0, i - herstel_uren):i + 1]
            if i - usdc_sinds >= herstel_uren and c[i] >= min(recent) * 1.0 and c[i] > c[i - 1]:
                munt *= (1 - fee); in_pool = True; swaps += 1
    return munt, swaps, crashes


async def main():
    a = sys.argv
    fee = float(a[a.index("--fee") + 1]) / 100 if "--fee" in a else 0.008
    apr = float(a[a.index("--apr") + 1]) if "--apr" in a else 22.0
    c = await laad_uur()
    # referentie: altijd pool
    pool_munt, _, _ = simuleer(c, 24, 9.99, 24, fee, apr)  # drempel 999% = nooit crash = altijd pool
    print(f"\nCrash-stop backtest, {len(c)} uur-candles")
    print(f"Referentie altijd-pool: {pool_munt:.0f} muntjes\n")
    print(f"  {'venster':>8s} {'drempel':>8s} {'herstel':>8s}   {'muntjes':>9s} {'vs pool':>8s} {'crashes':>8s} {'swaps':>6s}")
    for cu in (24, 48):
        for dr in (0.15, 0.20, 0.25, 0.30):
            munt, swaps, crashes = simuleer(c, cu, dr, 24, fee, apr)
            vs = (munt / pool_munt - 1) * 100
            print(f"  {cu:>6d}u {dr*100:>6.0f}% {'24u':>8s}   {munt:>9.0f} {vs:+7.1f}% {len(crashes):>8d} {swaps:>6d}")
    print("\nLees: 'vs pool' > 0 = de crash-stop beschermde meer muntjes dan hij")
    print("aan valse triggers kostte. 'crashes' = hoe vaak hij afging. Weinig")
    print("crashes + positief = goede drempel; veel crashes = te gevoelig.")


if __name__ == "__main__":
    asyncio.run(main())
