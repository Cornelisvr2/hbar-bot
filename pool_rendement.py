"""
pool_rendement.py -- wat had €2.000 opgeleverd?

Vergelijkt over de HBAR-candles in candles_5m drie scenario's:
  1. HBAR vasthouden (hodl)  -- alles in HBAR, koersresultaat
  2. USDC vasthouden         -- vlak, referentie
  3. LP-positie in de pool   -- 50/50 HBAR/USDC, fees erbij, impermanent
                                loss eraf (vereenvoudigd full-range model)

Het LP-model is bewust simpel en eerder pessimistisch: full-range 50/50,
IL via de bekende formule, fees als APR * fractie-in-range. Voor de echte
geconcentreerde range ligt zowel de fee-opbrengst als de IL hoger; dit
geeft de ondergrens en de verhouding tussen koers en fees.

    docker compose run --rm -T hbar-bot python3 pool_rendement.py --inleg 2000 --dagen 365 --apr 22 --in-range 0.70
"""
import asyncio
import math
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def il_factor(prijsratio: float) -> float:
    """Waarde LP / waarde hodl bij een koersverandering (full-range 50/50)."""
    return 2 * math.sqrt(prijsratio) / (1 + prijsratio)


async def main():
    a = sys.argv
    inleg = float(a[a.index("--inleg") + 1]) if "--inleg" in a else 2000.0
    dagen = int(a[a.index("--dagen") + 1]) if "--dagen" in a else 365
    apr = float(a[a.index("--apr") + 1]) if "--apr" in a else 22.0
    in_range = float(a[a.index("--in-range") + 1]) if "--in-range" in a else 0.70

    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    grens = datetime.now(timezone.utc) - timedelta(days=dagen)
    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT ts, close FROM candles_5m WHERE symbol='HBAR' AND ts >= $1 ORDER BY ts", grens)
    if len(rows) < 2:
        print("Te weinig candles.")
        return
    p0, p1 = rows[0]["close"], rows[-1]["close"]
    d0, d1 = rows[0]["ts"].date(), rows[-1]["ts"].date()
    jaren = (rows[-1]["ts"] - rows[0]["ts"]).total_seconds() / (365.25 * 86400)
    ratio = p1 / p0

    hodl = inleg * ratio
    lp_waarde_ex_fees = inleg * il_factor(ratio)
    il_verlies = inleg * ratio * (il_factor(ratio) - 1)  # t.o.v. hodl, negatief
    fees = inleg * (apr / 100) * jaren * in_range
    lp_totaal = lp_waarde_ex_fees + fees

    def regel(naam, eind):
        pct = (eind / inleg - 1) * 100
        print(f"  {naam:28s} €{eind:8.2f}   ({pct:+.1f}%)")

    print(f"\nPeriode {d0} .. {d1} ({jaren*365:.0f} dagen)")
    print(f"HBAR-koers ${p0:.5f} -> ${p1:.5f}  ({(ratio-1)*100:+.1f}%)")
    print(f"Aannames: pool-APR {apr:.0f}%, {in_range*100:.0f}% van de tijd in-range\n")
    regel("HBAR vasthouden", hodl)
    regel("USDC vasthouden", inleg)
    regel("LP (pool)", lp_totaal)
    print(f"\n  waarvan fees:            +€{fees:8.2f}")
    print(f"  waarvan impermanent loss: €{il_verlies:8.2f}  (t.o.v. HBAR vasthouden)")
    print(f"\nLP vs HBAR-vasthouden: {(lp_totaal/hodl-1)*100:+.1f}%   LP vs USDC: {(lp_totaal/inleg-1)*100:+.1f}%")
    print("\nLes: fees zijn positief en stabiel; de uitkomst in euro's hangt vooral")
    print("aan de HBAR-koers. Dat is precies wat een bull/bear-faseregel zou afvangen.")


if __name__ == "__main__":
    asyncio.run(main())
