"""
backtest_fase.py -- de kernstrategie van V4, getoetst op 2 jaar.

Regel: bull -> 100% HBAR, bear -> 100% USDC, sideways -> in de pool (fees).
Geschakeld op de trend t.o.v. het 200-daags gemiddelde, met HYSTERESE zodat
één tik door het gemiddelde niet meteen schakelt. Draait dag voor dag op de
HBAR-candles (alleen data van vóór die dag -- geen look-ahead), met swap-
kosten. Vergelijkt met de kale referenties uit pool_rendement.py.

Fasebepaling (bewust simpel en robuust, af te stellen):
  - koers > MA200 * (1 + BAND)   -> BULL
  - koers < MA200 * (1 - BAND)   -> BEAR
  - daartussen                   -> SIDEWAYS
  BAND is de hysterese: buiten de band schakelen, binnen de band blijven in
  de HUIDIGE stand. Extra bevestiging: N dagen op rij aan dezelfde kant.

Pool-benadering in sideways: verdient fees (POOL_APR * fractie), met een
lichte impermanent-loss-correctie op de koersbeweging van die dag. Dit is
dezelfde vereenvoudiging als pool_rendement.py.

    docker compose run --rm -T hbar-bot python3 backtest_fase.py
    docker compose run --rm -T hbar-bot python3 backtest_fase.py --band 5 --bevestiging 3 --fee 0.8 --apr 22
    docker compose run --rm -T hbar-bot python3 backtest_fase.py --grid   # zoekt robuuste parameters
"""
import asyncio
import math
import os
import sys
from datetime import timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

INLEG = 2000.0


def dagreeks(rows):
    """5-min-candles -> dagelijkse (ts, close) op 00:00-samples."""
    per_dag = {}
    for r in rows:
        d = r["ts"].date()
        per_dag[d] = r["close"]  # laatste close van de dag blijft staan
    dagen = sorted(per_dag)
    return dagen, [per_dag[d] for d in dagen]


def simuleer(dagen, prijs, band, bevestiging, fee, apr, pool_frac=0.70):
    n = len(prijs)
    kapitaal = INLEG            # totale waarde in EUR-equivalent
    stand = "SIDEWAYS"          # HBAR | USDC | SIDEWAYS
    hbar_eenheden = 0.0
    usdc = 0.0
    pool_waarde = INLEG         # als we in de pool starten
    in_pool = True
    swaps = 0
    dag_apr = apr / 100 / 365
    wachtrij = []               # laatste fasesignalen voor bevestiging

    def waarde_nu(i):
        if stand == "HBAR":
            return hbar_eenheden * prijs[i]
        if stand == "USDC":
            return usdc
        return pool_waarde

    for i in range(n):
        # MA200 (of zoveel als beschikbaar)
        lo = max(0, i - 200)
        ma = sum(prijs[lo:i + 1]) / (i - lo + 1)
        p = prijs[i]
        # ruw signaal
        if p > ma * (1 + band):
            sig = "HBAR"
        elif p < ma * (1 - band):
            sig = "USDC"
        else:
            sig = "SIDEWAYS"
        wachtrij.append(sig)
        if len(wachtrij) > bevestiging:
            wachtrij.pop(0)
        # bevestigd doel: alle laatste `bevestiging` signalen gelijk
        doel = sig if (len(wachtrij) == bevestiging and len(set(wachtrij)) == 1) else stand

        # pool verdient fees / ondergaat IL, ook als we niet schakelen
        if in_pool and i > 0:
            ret = prijs[i] / prijs[i - 1]
            il = 2 * math.sqrt(ret) / (1 + ret)          # IL-factor per dag
            pool_waarde = pool_waarde * il * (1 + dag_apr * pool_frac)

        if doel != stand:
            # eerst huidige stand liquideren naar EUR-waarde
            huidig = waarde_nu(i)
            # overstap kost fee (behalve pool->pool, dat gebeurt niet)
            huidig *= (1 - fee)
            swaps += 1
            if doel == "HBAR":
                hbar_eenheden = huidig / p; usdc = 0.0; in_pool = False
            elif doel == "USDC":
                usdc = huidig; hbar_eenheden = 0.0; in_pool = False
            else:  # SIDEWAYS -> pool
                pool_waarde = huidig; in_pool = True
            stand = doel

    eind = waarde_nu(n - 1)
    return eind, swaps


async def main():
    a = sys.argv
    band = float(a[a.index("--band") + 1]) / 100 if "--band" in a else 0.05
    bevestiging = int(a[a.index("--bevestiging") + 1]) if "--bevestiging" in a else 3
    fee = float(a[a.index("--fee") + 1]) / 100 if "--fee" in a else 0.008
    apr = float(a[a.index("--apr") + 1]) if "--apr" in a else 22.0

    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    async with db._pool.acquire() as conn:
        rows = await conn.fetch("SELECT ts, close FROM candles_5m WHERE symbol='HBAR' ORDER BY ts")
    dagen, prijs = dagreeks(rows)
    hold = INLEG * (prijs[-1] / prijs[0])
    print(f"\nFase-strategie op HBAR, {dagen[0]} .. {dagen[-1]} ({len(dagen)} dagen)")
    print(f"HBAR-koers ${prijs[0]:.5f} -> ${prijs[-1]:.5f} ({(prijs[-1]/prijs[0]-1)*100:+.1f}%)\n")
    print(f"Referenties:  hold €{hold:.0f} ({(hold/INLEG-1)*100:+.0f}%) · USDC €{INLEG:.0f} · kale pool ~€2577\n")

    if "--grid" in a:
        print(f"  {'band':>5s} {'bev':>4s}   {'eind €':>8s}  {'%':>6s}  {'swaps':>5s}")
        beste = None
        for b in (0.03, 0.05, 0.08, 0.12):
            for bev in (2, 3, 5):
                eind, swaps = simuleer(dagen, prijs, b, bev, fee, apr)
                mark = ""
                if beste is None or eind > beste[0]:
                    beste = (eind, b, bev); mark = "  <-"
                print(f"  {b*100:4.0f}% {bev:>4d}   €{eind:7.0f}  {(eind/INLEG-1)*100:+5.0f}%  {swaps:>5d}{mark}")
        print(f"\nBeste: band {beste[1]*100:.0f}%, bevestiging {beste[2]} -> €{beste[0]:.0f}")
    else:
        eind, swaps = simuleer(dagen, prijs, band, bevestiging, fee, apr)
        print(f"  Fase-strategie   €{eind:.0f}  ({(eind/INLEG-1)*100:+.0f}%)  {swaps} swaps")
        print(f"  band {band*100:.0f}%, bevestiging {bevestiging} dagen, fee {fee*100:.1f}%, pool-APR {apr:.0f}%")
        verschil_pool = (eind / 2577 - 1) * 100
        verschil_hold = (eind / hold - 1) * 100
        print(f"\n  vs kale pool: {verschil_pool:+.0f}%   vs hold: {verschil_hold:+.0f}%")


if __name__ == "__main__":
    asyncio.run(main())
