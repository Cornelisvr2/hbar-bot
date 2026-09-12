"""
backtest_sp_lead.py -- loopt de S&P 500 HBAR vooruit? (lead-lag)

These: algemeen nieuws beweegt eerst de aandelenmarkt (overdag, snel), en
crypto sjokt erachteraan. Dan zou een S&P-signaal van GISTEREN HBAR van
VANDAAG kunnen vóórlopen -> koop HBAR nadat de S&P sterk steeg, vóór HBAR is
bijgetrokken. Anders dan de eerdere triggers (die op HBAR's eigen koers
zaten en te laat kwamen).

Databeperking: alleen DAGELIJKSE S&P (FRED), geen intraday. En de S&P
handelt niet 's nachts/weekend. We testen dus de dag-versie:
  als S&P-dagrendement >= DREMPEL -> ga (of blijf) 100% HBAR de volgende
  handelsdag; anders terug naar de pool.
Vergelijkt met altijd-pool en altijd-HBAR, in muntjes én in USDC-waarde.

Eerlijk vooraf: S&P<->HBAR dag-correlatie was maar 0,27 (keten_analyse),
dus de verwachting is zwak. Deze test bevestigt of weerlegt dat met een
concreet handelsresultaat.

    docker compose run --rm -T hbar-bot python3 backtest_sp_lead.py
    docker compose run --rm -T hbar-bot python3 backtest_sp_lead.py --drempel 1.0 --lag 1
"""
import asyncio
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

INLEG = 2000.0


async def main():
    a = sys.argv
    drempel = float(a[a.index("--drempel") + 1]) / 100 if "--drempel" in a else 0.005
    lag = int(a[a.index("--lag") + 1]) if "--lag" in a else 1   # dagen vertraging S&P->HBAR
    fee = float(a[a.index("--fee") + 1]) / 100 if "--fee" in a else 0.008
    apr = float(a[a.index("--apr") + 1]) if "--apr" in a else 22.0

    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    async with db._pool.acquire() as conn:
        sp = await conn.fetch("SELECT ts, value FROM macro_inputs WHERE source='fred' AND series='SP500' ORDER BY ts")
        hbar_rows = await conn.fetch("SELECT ts, close FROM candles_5m WHERE symbol='HBAR' ORDER BY ts")
    sp_dag = {r["ts"].date(): r["value"] for r in sp}
    hbar_dag = {}
    for r in hbar_rows:
        hbar_dag[r["ts"].date()] = r["close"]

    sp_dagen = sorted(sp_dag)
    # S&P-dagrendement per datum
    sp_rend = {}
    for i in range(1, len(sp_dagen)):
        d, pv = sp_dagen[i], sp_dag[sp_dagen[i - 1]]
        if pv > 0:
            sp_rend[d] = sp_dag[d] / pv - 1

    hbar_dagen = sorted(hbar_dag)
    if len(hbar_dagen) < 30 or len(sp_rend) < 20:
        print("Te weinig data (S&P vult zich naarmate de loader draait).")
        return

    dag_apr = apr / 100 / 365
    munt = INLEG / hbar_dag[hbar_dagen[0]]
    stand = "POOL"          # POOL of HBAR
    pool_munt = munt
    hbar_munt = 0.0
    swaps = 0

    def totaal(prijs):
        return pool_munt + hbar_munt

    from datetime import timedelta
    for i in range(1, len(hbar_dagen)):
        d = hbar_dagen[i]
        prijs = hbar_dag[d]
        # pool: fees + IL in muntjes
        if stand == "POOL":
            ret = prijs / hbar_dag[hbar_dagen[i - 1]]
            il = 2 * math.sqrt(ret) / (1 + ret)
            pool_munt = pool_munt * il * (1 + dag_apr * 0.70)
        # signaal: S&P-rendement van `lag` dagen geleden
        sp_d = d - timedelta(days=lag)
        # zoek dichtstbijzijnde beursdag <= sp_d
        sp_sig = None
        for off in range(0, 4):
            k = sp_d - timedelta(days=off)
            if k in sp_rend:
                sp_sig = sp_rend[k]; break
        doel = "HBAR" if (sp_sig is not None and sp_sig >= drempel) else "POOL"
        if doel != stand:
            if doel == "HBAR":
                hbar_munt = pool_munt * (1 - fee); pool_munt = 0.0
            else:
                pool_munt = hbar_munt * (1 - fee); hbar_munt = 0.0
            stand = doel; swaps += 1

    eind_munt = pool_munt + hbar_munt
    eind_prijs = hbar_dag[hbar_dagen[-1]]
    hold_munt = INLEG / hbar_dag[hbar_dagen[0]]

    print(f"\nS&P-lead-backtest, {hbar_dagen[0]} .. {hbar_dagen[-1]}")
    print(f"Signaal: S&P-dagrendement {lag}d geleden >= {drempel*100:.1f}% -> HBAR, anders pool")
    print(f"Overlappende S&P-dagen: {len(sp_rend)} | swaps: {swaps}\n")
    print(f"  {'aanpak':22s} {'muntjes':>10s} {'vs hold':>9s} {'waarde':>9s}")
    print(f"  {'S&P-lead strategie':22s} {eind_munt:>10.0f} {(eind_munt/hold_munt-1)*100:+8.1f}% ${eind_munt*eind_prijs:>7.0f}")
    print(f"  {'HBAR vasthouden':22s} {hold_munt:>10.0f} {'  0.0%':>9s} ${hold_munt*eind_prijs:>7.0f}")
    print(f"  (kale pool ~ +7% muntjes uit eerdere test)")
    print("\nLees: verslaat de S&P-lead de kale pool/hold in muntjes? Zo niet, dan")
    print("loopt de S&P HBAR niet bruikbaar vooruit (past bij de zwakke 0,27-correlatie).")


if __name__ == "__main__":
    asyncio.run(main())
