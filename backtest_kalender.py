"""
backtest_kalender.py -- levert de kalender-anticipatie iets op?

De enige nieuws-gedreven strategie die de data steunt (zie
CONCLUSIE_NIEUWS_11sep2026.md): rond GEPLANDE high-impact macro-events
(CPI, FOMC, NFP, PPI, PCE) reageert de markt ná het cijfer -- daar kun je
op handelen, anders dan op crypto-nieuws dat achter de koers aanloopt.

Getest op event_calendar + candles_5m (BTC en HBAR). Drie varianten,
allemaal t.o.v. "altijd in HBAR" en "altijd in de pool":

  vlak      -> VOOR_MIN vóór het event naar USDC, NA_MIN erna terug naar
               HBAR. Puur de klap ontwijken (defensief, geen richting).
  surprise  -> idem uit vóór het event; NA het event schakelen op de
               VERRASSING (actual vs estimate, genormaliseerd op de
               historische spreiding van dat eventtype): mee-verrassing
               positief -> HBAR, negatief -> in USDC blijven tot NA_MIN.
  hold      -> niets doen (referentie).

Meet op de HBAR-koers (dat is wat je portefeuille voelt), met swapkosten.
Alleen events met impact 'high' of een naam in KERN_EVENTS.

    docker compose run --rm -T hbar-bot python3 backtest_kalender.py
    docker compose run --rm -T hbar-bot python3 backtest_kalender.py --voor 120 --na 120 --fee 0.8
"""
import asyncio
import math
import os
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

INLEG = 2000.0
KERN_EVENTS = ("cpi", "fomc", "federal funds", "nonfarm", "non-farm", "nfp", "ppi",
               "pce", "unemployment", "gdp", "interest rate", "jobs")


class Prijs:
    def __init__(self, rows):
        self.t = [r["ts"].timestamp() for r in rows]
        self.c = [r["close"] for r in rows]

    def at(self, ts):
        i = bisect_right(self.t, ts) - 1
        return self.c[i] if 0 <= i < len(self.c) else None


def is_kern(naam, impact):
    n = (naam or "").lower()
    return impact == "high" or any(k in n for k in KERN_EVENTS)


async def main():
    a = sys.argv
    voor = int(a[a.index("--voor") + 1]) if "--voor" in a else 120
    na = int(a[a.index("--na") + 1]) if "--na" in a else 120
    fee = float(a[a.index("--fee") + 1]) / 100 if "--fee" in a else 0.008

    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    async with db._pool.acquire() as conn:
        prijs = Prijs(await conn.fetch("SELECT ts, close FROM candles_5m WHERE symbol='HBAR' ORDER BY ts"))
        events = await conn.fetch(
            "SELECT name, ts, impact, estimate, previous, actual FROM event_calendar ORDER BY ts")
    if not prijs.t:
        print("Geen candles."); return

    kern = [e for e in events if is_kern(e["name"], e["impact"])]
    # verrassing normaliseren per eventtype (grofweg op de eerste twee woorden van de naam)
    def sleutel(naam):
        return " ".join((naam or "").lower().split()[:2])
    spreiding = defaultdict(list)
    for e in kern:
        if e["actual"] is not None and e["estimate"] is not None:
            spreiding[sleutel(e["name"])].append(abs(e["actual"] - e["estimate"]))
    sd = {k: (sum(v) / len(v) or 1.0) for k, v in spreiding.items() if v}

    binnen = [e for e in kern if prijs.t[0] <= e["ts"].timestamp() <= prijs.t[-1]]
    print(f"\nKalender-anticipatie op HBAR-koers")
    print(f"{len(kern)} kern-events, {len(binnen)} binnen de candle-periode | venster -{voor}m..+{na}m | fee {fee*100:.1f}%\n")

    # bouw voor elke strategie een lijst (ts_uit, ts_in, wil_hbar_in_venster)
    # Overlappende event-vensters samenvoegen (CPI+Core CPI+PPI vallen vaak
    # samen): anders swapt de bot binnen elkaar overlappende vensters heen en
    # weer -> een swap-storm die het kapitaal aan fees opeet. Eén venster =
    # hooguit 2 swaps (uit vóór, terug ná).
    ruwe = sorted(((e["ts"].timestamp() - voor * 60, e["ts"].timestamp() + na * 60, e) for e in binnen),
                  key=lambda x: x[0])
    vensters = []
    for s0, s1, e in ruwe:
        if vensters and s0 <= vensters[-1][1]:
            vensters[-1] = (vensters[-1][0], max(vensters[-1][1], s1), vensters[-1][2] + [e])
        else:
            vensters.append((s0, s1, [e]))

    def simuleer(modus):
        eenheden = INLEG / prijs.c[0]
        usdc = 0.0
        swaps = 0
        bijdragen = []
        for s0, s1, evs in vensters:
            p_uit = prijs.at(s0)
            p_in = prijs.at(s1)
            if p_uit is None or p_in is None:
                continue
            # uit vóór het venster
            usdc = eenheden * p_uit * (1 - fee); eenheden = 0.0; swaps += 1
            # terug ná het venster? (vlak = altijd; surprise = alleen bij niet-slechte verrassing)
            if modus == "surprise":
                slecht = False
                for e in evs:
                    naam = (e["name"] or "").lower()
                    if e["actual"] is not None and e["previous"] is not None:
                        richting = e["actual"] - e["previous"]
                        slecht_als_hoog = any(k in naam for k in ("cpi", "ppi", "pce", "inflation", "rate", "funds"))
                        if (richting > 0) == slecht_als_hoog and abs(richting) > 0:
                            slecht = True
                terug = not slecht
            else:
                terug = True
            if terug:
                eenheden = (usdc / p_in) * (1 - fee); usdc = 0.0; swaps += 1
            bijdragen.append((evs[0]["name"][:32], (p_in / p_uit - 1) * 100, terug))
        eind = usdc + eenheden * prijs.c[-1]
        return eind, swaps, bijdragen

    hold = INLEG * (prijs.c[-1] / prijs.c[0])
    print(f"  {'hold (altijd HBAR)':28s} €{hold:8.2f}  ({(hold/INLEG-1)*100:+.1f}%)")
    for modus in ("vlak", "surprise"):
        eind, swaps, bij = simuleer(modus)
        print(f"  {modus:28s} €{eind:8.2f}  ({(eind/INLEG-1)*100:+.1f}%)  {swaps} swaps")
    print(f"  (kale pool ~ €2577 uit pool_rendement.py)")

    # grootste bewegingen rond events
    _, _, bij = simuleer("vlak")
    print(f"\nGrootste koersbewegingen in het venster rond een event:")
    for naam, beweging, _ in sorted(bij, key=lambda x: -abs(x[1]))[:12]:
        print(f"  {beweging:+6.1f}%  {naam}")


if __name__ == "__main__":
    asyncio.run(main())
