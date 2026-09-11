"""
backtest_dca.py -- welke aanpak met MAANDELIJKS bijstorten was het beste?

Realistisch scenario: EUR_START nu, daarna EUR_MAAND elke maand erbij. Dat
is dollar-cost averaging (DCA) -- op zichzelf al robuust omdat het niet van
timing afhangt: je koopt automatisch meer als het laag staat. Vergelijkt
vier aanpakken over de HBAR-candles in candles_5m:

  1. DCA-HBAR        elke storting -> HBAR, alles vasthouden
  2. DCA-pool        elke storting -> LP-pool (fees APR * in-range, IL)
  3. DCA-fase        stortingen volgen de bull/bear/sideways-schakeling
                     (bull->HBAR, bear->USDC, sideways->pool)
  4. DCA-fase-cyclus als 3, maar de cyclus-positie dempt: diep onder de
                     365d-trend mag meer HBAR (accumuleren), ver boven +
                     aflopend dwingt defensiever.

EERLIJK: dit is EEN cyclus data. De 'winnaar' paste het best bij 2024-2026;
de komende 2 jaar zitten in een andere halving-fase. Lees de uitkomst als
"hoe pakt mijn echte gedrag uit", niet als garantie.

    docker compose run --rm -T hbar-bot python3 backtest_dca.py
    docker compose run --rm -T hbar-bot python3 backtest_dca.py --start 2000 --maand 100 --fee 0.8 --apr 22
"""
import asyncio
import math
import os
import sys
from datetime import timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def dagreeks(rows):
    per_dag = {}
    for r in rows:
        per_dag[r["ts"].date()] = r["close"]
    dagen = sorted(per_dag)
    return dagen, [per_dag[d] for d in dagen]


def sma_op(prijs, i, n):
    lo = max(0, i - n)
    return sum(prijs[lo:i + 1]) / (i - lo + 1)


def run(dagen, prijs, start, maand, fee, apr, modus, band=0.05, bevestiging=3):
    """Simuleer een aanpak met maandelijkse stortingen. Geeft eindwaarde + totaal gestort."""
    n = len(prijs)
    dag_apr = apr / 100 / 365
    hbar = 0.0          # HBAR-eenheden
    usdc = 0.0          # stabiel (EUR-equiv)
    pool = 0.0          # waarde in de pool
    in_pool_stand = False
    stand = "SIDEWAYS"
    wachtrij = []
    gestort = 0.0
    vorige_maand = None

    def totale_waarde(i):
        return hbar * prijs[i] + usdc + pool

    for i in range(n):
        # maandelijkse storting (eerste dag van een nieuwe maand, of dag 0)
        mnd = (dagen[i].year, dagen[i].month)
        if i == 0:
            bedrag = start
        elif mnd != vorige_maand:
            bedrag = maand
        else:
            bedrag = 0.0
        vorige_maand = mnd

        # pool groeit/krimpt dagelijks (fees + IL) als er iets in zit
        if pool > 0 and i > 0:
            ret = prijs[i] / prijs[i - 1]
            il = 2 * math.sqrt(ret) / (1 + ret)
            pool = pool * il * (1 + dag_apr * 0.70)

        # bepaal doelstand
        if modus == "hbar":
            doel = "HBAR"
        elif modus == "pool":
            doel = "POOL"
        else:
            ma = sma_op(prijs, i, 200)
            p = prijs[i]
            sig = "HBAR" if p > ma * (1 + band) else "USDC" if p < ma * (1 - band) else "POOL"
            wachtrij.append(sig)
            if len(wachtrij) > bevestiging:
                wachtrij.pop(0)
            doel = sig if (len(wachtrij) == bevestiging and len(set(wachtrij)) == 1) else stand
            if modus == "fase-cyclus":
                # cyclus-demping: onder 365d-trend -> bull toestaan/versterken;
                # ver boven trend -> bull blokkeren (naar pool i.p.v. HBAR)
                logp = [math.log(x) for x in prijs[max(0, i - 365):i + 1]]
                trend = sum(logp) / len(logp)
                cyc = math.log(p) - trend
                if doel == "HBAR" and cyc > 0.5:
                    doel = "POOL"          # te hoog in de cyclus: niet vol HBAR
                if doel == "USDC" and cyc < -0.4:
                    doel = "POOL"          # diep onder trend: niet vol cash, accumuleer via pool

        # schakel indien nodig (verplaats de HELE waarde naar de doelstand)
        if doel != stand:
            w = totale_waarde(i) * (1 - fee)
            hbar = usdc = pool = 0.0
            if doel == "HBAR":
                hbar = w / prijs[i]
            elif doel == "USDC":
                usdc = w
            else:
                pool = w
            stand = doel

        # storting toevoegen aan de HUIDIGE stand (nieuwe inleg, geen swap-fee bij pool/usdc;
        # bij HBAR wel een koop-fee)
        if bedrag > 0:
            gestort += bedrag
            if stand == "HBAR":
                hbar += (bedrag * (1 - fee)) / prijs[i]
            elif stand == "USDC":
                usdc += bedrag
            else:
                pool += bedrag

    return totale_waarde(n - 1), gestort


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
    mnd = len(set((d.year, d.month) for d in dagen))
    print(f"\nDCA-vergelijking op HBAR, {dagen[0]} .. {dagen[-1]} ({mnd} maanden)")
    print(f"Start €{start:.0f} + €{maand:.0f}/maand | fee {fee*100:.1f}% | pool-APR {apr:.0f}%")
    print(f"HBAR-koers ${prijs[0]:.5f} -> ${prijs[-1]:.5f} ({(prijs[-1]/prijs[0]-1)*100:+.0f}%)\n")

    resultaten = []
    for modus, naam in [("hbar", "DCA-HBAR (vasthouden)"), ("pool", "DCA-pool"),
                        ("fase", "DCA-fase"), ("fase-cyclus", "DCA-fase+cyclus")]:
        eind, gestort = run(dagen, prijs, start, maand, fee, apr, modus)
        rendement = (eind / gestort - 1) * 100
        resultaten.append((naam, eind, gestort, rendement))

    gestort = resultaten[0][2]
    print(f"  Totaal gestort: €{gestort:.0f}\n")
    print(f"  {'aanpak':26s} {'eindwaarde':>11s} {'rendement':>10s}")
    for naam, eind, _g, r in sorted(resultaten, key=lambda x: -x[1]):
        print(f"  {naam:26s} €{eind:9.0f} {r:+9.0f}%")
    print("\nLees: rendement = t.o.v. het totaal ingelegde geld (€2000 + maandinleg).")
    print("EEN cyclus data -- de winnaar paste het best bij DEZE periode. DCA zelf")
    print("(maandelijks bijstorten) is de robuuste basis; de aanpak eromheen doet er")
    print("minder toe dan het volhouden van de stortingen.")


if __name__ == "__main__":
    asyncio.run(main())
