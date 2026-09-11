"""
backtest_pool_muntjes.py -- welke pool-instelling verzamelt de meeste HBAR?

Optimaliseert de twee knoppen die de muntjes-opbrengst van de pool bepalen,
tegen elkaar afgewogen:
  - RANGE-BREEDTE: smal = meer fees per muntje (liquiditeit dichter bij de
    prijs), maar sneller uit range en vaker herbalanceren (swap-kosten).
    Breed = minder fees, zelden herbalanceren.
  - HERBALANCEER-DREMPEL: hoe ver de prijs uit het midden mag lopen voordat
    we de range opnieuw centreren. Vaker = meer in-range-tijd maar meer
    swap-kosten; minder vaak = goedkoper maar meer tijd buiten range (0 fees).

Netto muntjes = fees (in HBAR) - swap-kosten (in HBAR) - impermanent loss.

DATABEPERKING (eerlijk): candles_5m geeft de koers, niet het werkelijke
pool-volume per dag dat de fees bepaalt. We benaderen de fee-opbrengst met
een basis-fee-APR die schaalt met 1/breedte (smaller = evenredig hogere APR,
de bekende concentrated-liquidity-relatie) en ALLEEN meetelt als de prijs
IN range is. Dat geeft de VORM van het antwoord (welke breedte/drempel wint)
betrouwbaar; de absolute muntjes zijn een schatting, te kalibreren met de
live fee-APR die de bot logt (~22% bij de huidige ~10% breedte).

    docker compose run --rm -T hbar-bot python3 backtest_pool_muntjes.py
    docker compose run --rm -T hbar-bot python3 backtest_pool_muntjes.py --basis-apr 22 --basis-breedte 10
"""
import asyncio
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

INLEG_MUNT = 40000.0   # start-muntjes (schaal maakt niet uit, we kijken naar %)


def dagreeks(rows):
    per_dag = {}
    for r in rows:
        per_dag[r["ts"].date()] = r["close"]
    dagen = sorted(per_dag)
    return dagen, [per_dag[d] for d in dagen]


def simuleer(prijs, breedte, herbal_drempel, fee_swap, basis_apr, basis_breedte):
    """
    breedte: halve range-breedte als fractie (0.10 = +-10%).
    herbal_drempel: fractie van de breedte die de prijs uit het midden mag
                    lopen voor een herbalancering (0.8 = bij 80% van de rand).
    Geeft: eind-muntjes, aantal herbalanceringen, dagen-in-range%.
    """
    n = len(prijs)
    munt = INLEG_MUNT
    centrum = prijs[0]
    # fee-APR schaalt met basis_breedte/breedte (smaller = hoger)
    apr = basis_apr / 100 * (basis_breedte / 100) / breedte
    dag_apr = apr / 365
    herbal = 0
    dagen_in_range = 0
    for i in range(1, n):
        onder = centrum * (1 - breedte)
        boven = centrum * (1 + breedte)
        in_range = onder <= prijs[i] <= boven
        if in_range:
            dagen_in_range += 1
            # fees in muntjes (alleen in range)
            munt *= (1 + dag_apr)
            # impermanent loss t.o.v. het centrum (dagbeweging binnen range)
            ret = prijs[i] / prijs[i - 1]
            il = 2 * math.sqrt(ret) / (1 + ret)
            munt *= il
        # herbalanceren als de prijs voorbij de drempel binnen de range komt
        afstand = abs(prijs[i] - centrum) / (centrum * breedte)  # 0..1+
        if afstand >= herbal_drempel:
            munt *= (1 - fee_swap)   # swap-kosten in muntjes
            centrum = prijs[i]
            herbal += 1
    return munt, herbal, dagen_in_range / (n - 1) * 100


async def main():
    a = sys.argv
    fee = float(a[a.index("--fee") + 1]) / 100 if "--fee" in a else 0.008
    basis_apr = float(a[a.index("--basis-apr") + 1]) if "--basis-apr" in a else 22.0
    basis_breedte = float(a[a.index("--basis-breedte") + 1]) if "--basis-breedte" in a else 10.0

    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    van = a[a.index("--van") + 1] if "--van" in a else None
    tot = a[a.index("--tot") + 1] if "--tot" in a else None
    async with db._pool.acquire() as conn:
        rows = await conn.fetch("SELECT ts, close FROM candles_5m WHERE symbol='HBAR' ORDER BY ts")
    dagen, prijs = dagreeks(rows)
    if van or tot:
        from datetime import date as _d
        v = _d.fromisoformat(van) if van else dagen[0]
        t = _d.fromisoformat(tot) if tot else dagen[-1]
        paar = [(d, p_) for d, p_ in zip(dagen, prijs) if v <= d <= t]
        dagen = [d for d, _ in paar]; prijs = [p_ for _, p_ in paar]
    print(f"\nPool-instelling optimalisatie (muntjes), HBAR {dagen[0]} .. {dagen[-1]}")
    print(f"Koers ${prijs[0]:.5f} -> ${prijs[-1]:.5f} | fee/swap {fee*100:.1f}% | "
          f"ijk: {basis_apr:.0f}% APR bij ±{basis_breedte:.0f}% breedte\n")
    # referentie: gewoon HBAR vasthouden = de start-muntjes, onveranderd
    print(f"  Referentie: HBAR vasthouden = {INLEG_MUNT:.0f} muntjes (0%, per definitie)\n")
    print(f"  {'breedte':>8s} {'drempel':>8s}   {'eind-munt':>10s} {'vs hold':>9s} {'herbal':>7s} {'in-range':>9s}")
    beste = None
    for breedte in (0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30):
        for drempel in (0.5, 0.7, 0.9):
            munt, herbal, inrange = simuleer(prijs, breedte, drempel, fee, basis_apr, basis_breedte)
            vs = (munt / INLEG_MUNT - 1) * 100
            mark = ""
            if beste is None or munt > beste[0]:
                beste = (munt, breedte, drempel); mark = "  <-"
            print(f"  {breedte*100:6.0f}% {drempel*100:6.0f}%   {munt:>10.0f} {vs:+8.1f}% {herbal:>7d} {inrange:>7.0f}%{mark}")
    print(f"\nBeste: ±{beste[1]*100:.0f}% breedte, herbalanceren bij {beste[2]*100:.0f}% van de rand "
          f"-> {(beste[0]/INLEG_MUNT-1)*100:+.1f}% muntjes")
    print("\nLet op: fee-opbrengst is BENADERD (geen historisch pool-volume). De VORM")
    print("(welke breedte/drempel wint) is betrouwbaar; kalibreer de absolute muntjes")
    print("met de live fee-APR die de bot logt. Smaller lijkt meer fees maar kost")
    print("in-range-tijd + herbalanceer-swaps -- deze tabel weegt dat tegen elkaar af.")


if __name__ == "__main__":
    asyncio.run(main())
