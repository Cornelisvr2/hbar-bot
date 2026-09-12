"""
backtest_muntjes.py -- hoeveel HBAR verzamel je? (niet euro's, muntjes)

Doel van de eigenaar: MAXIMALE hoeveelheid HBAR tegen de tijd dat de bull
losbarst -- niet de eurowaarde. Nooit naar USDC (elke dip = koopkans).
Twee standen: POOL (fees oogsten in de bodem) en HBAR (100%, bull meepakken).

Vergelijkt over de HBAR-candles in candles_5m, ALLES uitgedrukt in HBAR-
eenheden (muntjes):
  1. HBAR-hold        koop nu HBAR, doe niets -> vaste hoeveelheid muntjes
  2. Pool-altijd      altijd in de pool; fees IN muntjes, IL kost muntjes
  3. Pool<->HBAR      pool als grondstand, 100% HBAR zodra trend bevestigd
                      bull (koers > MA200*(1+band)); terug naar pool als de
                      trend wegvalt. NOOIT USDC.
Met maandelijkse storting (in EUR, omgezet naar muntjes tegen de dagkoers)
zodat het je echte gedrag weerspiegelt.

De vraag die dit beantwoordt: levert de pool (fees) je nettо MEER muntjes op
dan gewoon HBAR vasthouden, ondanks impermanent loss? En voegt het schakelen
naar 100% HBAR in de bull muntjes toe of juist niet?

    docker compose run --rm -T hbar-bot python3 backtest_muntjes.py --start 2000 --maand 100 --apr 22
"""
import asyncio
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def dagreeks(rows):
    per_dag = {}
    for r in rows:
        per_dag[r["ts"].date()] = r["close"]
    dagen = sorted(per_dag)
    return dagen, [per_dag[d] for d in dagen]


def run(dagen, prijs, start, maand, fee, apr, modus, band=0.08, bevestiging=2, ma_dagen=200):
    """Geeft eind-HBAR (muntjes) en totaal gestorte muntjes terug."""
    n = len(prijs)
    dag_apr = apr / 100 / 365
    # posities in muntjes-equivalent:
    hbar = 0.0            # losse HBAR-muntjes
    pool_hbar = 0.0       # muntjes-waarde van de poolpositie (in HBAR uitgedrukt)
    in_pool = (modus != "hold")
    stand = "POOL" if in_pool else "HBAR"
    wachtrij = []
    vorige_maand = None
    gestort_munt = 0.0

    def totaal_munt(i):
        return hbar + pool_hbar

    # start
    hbar_start = start / prijs[0]
    if modus == "hold":
        hbar = hbar_start
    else:
        pool_hbar = hbar_start
    gestort_munt += hbar_start

    for i in range(n):
        # maandelijkse storting -> muntjes tegen dagkoers, in de huidige stand
        mnd = (dagen[i].year, dagen[i].month)
        if i > 0 and mnd != vorige_maand:
            munt = maand / prijs[i]
            gestort_munt += munt
            if stand == "HBAR":
                hbar += munt * (1 - fee)
            else:
                pool_hbar += munt
        vorige_maand = mnd

        # pool: fees (in muntjes) + IL (in muntjes) per dag
        if in_pool and i > 0:
            ret = prijs[i] / prijs[i - 1]
            il = 2 * math.sqrt(ret) / (1 + ret)   # < 1, kost muntjes bij beweging
            # fee-APR is in USD; omgerekend naar muntjes bij benadering /prijs-neutraal:
            # we tellen de fee als extra muntjes-groei (pool-fees worden deels in HBAR uitgekeerd)
            pool_hbar = pool_hbar * il * (1 + dag_apr * 0.70)

        if modus == "poolhbar":
            ma_lo = max(0, i - ma_dagen)
            ma = sum(prijs[ma_lo:i + 1]) / (i - ma_lo + 1)
            sig = "HBAR" if prijs[i] > ma * (1 + band) else "POOL"
            wachtrij.append(sig)
            if len(wachtrij) > bevestiging:
                wachtrij.pop(0)
            doel = sig if (len(wachtrij) == bevestiging and len(set(wachtrij)) == 1) else stand
            if doel != stand:
                # schakel: alle muntjes van de ene naar de andere stand (fee kost muntjes)
                if doel == "HBAR":
                    hbar = pool_hbar * (1 - fee); pool_hbar = 0.0; in_pool = False
                else:
                    pool_hbar = hbar * (1 - fee); hbar = 0.0; in_pool = True
                stand = doel

    return totaal_munt(n - 1), gestort_munt


async def main():
    a = sys.argv
    start = float(a[a.index("--start") + 1]) if "--start" in a else 2000.0
    maand = float(a[a.index("--maand") + 1]) if "--maand" in a else 100.0
    fee = float(a[a.index("--fee") + 1]) / 100 if "--fee" in a else 0.008
    apr = float(a[a.index("--apr") + 1]) if "--apr" in a else 22.0

    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    async with db._pool.acquire() as conn:
        rows = await conn.fetch("SELECT ts, close FROM candles_5m WHERE symbol='HBAR' ORDER BY ts")
    dagen, prijs = dagreeks(rows)
    print(f"\nMuntjes-backtest HBAR, {dagen[0]} .. {dagen[-1]}")
    print(f"Koers ${prijs[0]:.5f} -> ${prijs[-1]:.5f} | start €{start:.0f} + €{maand:.0f}/maand\n")

    res = {}
    for modus, naam in [("hold", "HBAR vasthouden"), ("pool", "altijd pool"), ("poolhbar", "pool <-> HBAR (bull)")]:
        munt, gestort = run(dagen, prijs, start, maand, fee, apr, modus)
        res[naam] = (munt, gestort)

    gestort = res["HBAR vasthouden"][1]
    print(f"  Totaal gestort: {gestort:.0f} HBAR-muntjes (= €{start + maand*(len(set((d.year,d.month) for d in dagen))-1):.0f})\n")
    print(f"  {'aanpak':24s} {'eind-muntjes':>14s} {'vs hold':>9s} {'waarde nu':>11s}")
    hold_munt = res["HBAR vasthouden"][0]
    for naam, (munt, _g) in sorted(res.items(), key=lambda x: -x[1][0]):
        vs = (munt / hold_munt - 1) * 100
        print(f"  {naam:24s} {munt:>12.0f}   {vs:+7.1f}%  €{munt*prijs[-1]:>9.0f}")
    print("\nLees: dit is in HBAR-MUNTJES, niet euro's. 'vs hold' = hoeveel meer/minder")
    print("muntjes dan gewoon kopen-en-vasthouden. Positief = de pool/strategie leverde")
    print("netto muntjes op ondanks impermanent loss. EEN cyclus data -- indicatief.")


if __name__ == "__main__":
    asyncio.run(main())
