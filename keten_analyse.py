"""
keten_analyse.py -- algemeen nieuws -> aandelen -> BTC -> HBAR.

Toetst de these: HBAR is aan het eind van de keten een beta op risk-on/
risk-off-stemming die vaak op de AANDELENMARKT begint (algemeen/macro-
nieuws), via BTC naar HBAR doorwerkt. Als dat klopt, telt de brede
markt-stemming meer dan HBAR-specifiek nieuws.

Meet twee dingen op DAGNIVEAU (de aandelenmarkt handelt niet 24/7, dus dag
is de betrouwbare eenheid met gratis data):

1. VERWEVENHEID: dagelijkse rendementen van S&P 500, Nasdaq, BTC en HBAR
   over dezelfde periode -> correlatiematrix + HBAR's beta t.o.v. elk.
   Laat zien hoe sterk HBAR met de aandelenmarkt meebeweegt.

2. NIEUWS-DAGEN: op dagen met een hoog-impact macro-gebeurtenis
   (news_events, entity macro/markt_breed, magnitude >= 4) -> bewoog de
   hele risicomarkt (S&P + BTC + HBAR) dan dezelfde kant op? Dat is de
   keten in actie.

Bronnen: macro_inputs (fred: SP500, NASDAQCOM) + candles_5m (BTC, HBAR,
naar dagcloses) + news_events. Puur analytisch.

    docker compose run --rm -T hbar-bot python3 keten_analyse.py
    docker compose run --rm -T hbar-bot python3 keten_analyse.py --sinds 2025-01-01
"""
import asyncio
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def dagrend(dagen_prijzen):
    """dict {date: close} -> dict {date: dagrendement}."""
    items = sorted(dagen_prijzen.items())
    out = {}
    for i in range(1, len(items)):
        d, p = items[i]
        pv = items[i - 1][1]
        if pv and pv > 0:
            out[d] = p / pv - 1
    return out


def corr(xs, ys):
    n = len(xs)
    if n < 10:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx and dy else None


def beta(ys, xs):
    """beta van y t.o.v. x (hoeveel y beweegt per 1% x)."""
    n = len(xs)
    if n < 10:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    var = sum((x - mx) ** 2 for x in xs)
    return cov / var if var else None


async def main():
    a = sys.argv
    sinds = a[a.index("--sinds") + 1] if "--sinds" in a else "2024-09-01"
    sinds_d = datetime.fromisoformat(sinds).date()

    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()

    # aandelen uit macro_inputs
    reeksen = {}
    async with db._pool.acquire() as conn:
        for series, naam in [("SP500", "S&P500"), ("NASDAQCOM", "Nasdaq")]:
            rows = await conn.fetch(
                "SELECT ts, value FROM macro_inputs WHERE source='fred' AND series=$1 AND ts >= $2 ORDER BY ts",
                series, datetime.combine(sinds_d, datetime.min.time(), tzinfo=timezone.utc))
            reeksen[naam] = {r["ts"].date(): r["value"] for r in rows}
        # BTC en HBAR uit candles_5m -> dagcloses
        for sym in ("BTC", "HBAR"):
            rows = await conn.fetch(
                "SELECT ts, close FROM candles_5m WHERE symbol=$1 AND ts >= $2 ORDER BY ts",
                sym, datetime.combine(sinds_d, datetime.min.time(), tzinfo=timezone.utc))
            dagen = {}
            for r in rows:
                dagen[r["ts"].date()] = r["close"]
            reeksen[sym] = dagen
        # hoog-impact macro-gebeurtenissen
        macro_ev = await conn.fetch(
            """SELECT published_at::date d, count(*) n FROM news_events
               WHERE (asset='MACRO' OR entity IN ('macro','markt_breed')) AND magnitude_guess >= 4
                 AND published_at::date >= $1 GROUP BY 1""", sinds_d)
    macro_dagen = {r["d"]: r["n"] for r in macro_ev}

    rend = {k: dagrend(v) for k, v in reeksen.items()}
    # gemeenschappelijke dagen (waar alle vier een rendement hebben -- dus beursdagen)
    gemeen = set(rend["S&P500"]) & set(rend["Nasdaq"]) & set(rend["BTC"]) & set(rend["HBAR"])
    gemeen = sorted(gemeen)
    print(f"\nKeten-analyse (dagniveau), {sinds} .. nu")
    print(f"Gemeenschappelijke beursdagen met alle reeksen: {len(gemeen)}\n")
    if len(gemeen) < 20:
        print("Te weinig overlappende dagen -- draai de macro-loader een tijd zodat SP500/Nasdaq zich vullen.")
        return

    def kol(naam):
        return [rend[naam][d] for d in gemeen]

    print("== Verwevenheid: correlatie van dagrendementen ==")
    paren = [("S&P500", "BTC"), ("Nasdaq", "BTC"), ("BTC", "HBAR"),
             ("S&P500", "HBAR"), ("Nasdaq", "HBAR"), ("S&P500", "Nasdaq")]
    for x, y in paren:
        c = corr(kol(x), kol(y))
        print(f"  {x:8s} <-> {y:8s}: {c:+.2f}" if c is not None else f"  {x} <-> {y}: n.v.t.")
    print("\n== HBAR-beta (hoeveel HBAR beweegt per 1% van...) ==")
    for x in ("S&P500", "Nasdaq", "BTC"):
        b = beta(kol("HBAR"), kol(x))
        print(f"  t.o.v. {x:8s}: {b:+.2f}x" if b is not None else f"  t.o.v. {x}: n.v.t.")

    # nieuws-dagen: bewoog de hele risicomarkt samen?
    nieuws = [d for d in gemeen if d in macro_dagen]
    print(f"\n== Hoog-impact macro-nieuwsdagen: {len(nieuws)} ==")
    if len(nieuws) >= 8:
        samen = 0
        for d in nieuws:
            tekens = [rend[k][d] > 0 for k in ("S&P500", "BTC", "HBAR")]
            if all(tekens) or not any(tekens):
                samen += 1
        gem_hbar = sum(rend["HBAR"][d] for d in nieuws) / len(nieuws) * 100
        gem_sp = sum(rend["S&P500"][d] for d in nieuws) / len(nieuws) * 100
        print(f"  S&P, BTC én HBAR dezelfde kant op: {samen}/{len(nieuws)} dagen ({100*samen/len(nieuws):.0f}%)")
        print(f"  gemiddeld die dagen: S&P {gem_sp:+.2f}%, HBAR {gem_hbar:+.2f}%")
        # correlatie op alleen nieuwsdagen vs alle dagen
        c_nieuws = corr([rend["S&P500"][d] for d in nieuws], [rend["HBAR"][d] for d in nieuws])
        c_alle = corr(kol("S&P500"), kol("HBAR"))
        print(f"  S&P<->HBAR correlatie op nieuwsdagen: {c_nieuws:+.2f} (alle dagen: {c_alle:+.2f})"
              if c_nieuws is not None else "")
    else:
        print("  Te weinig gelabelde macro-nieuwsdagen -- vult zich naarmate de bot draait.")

    print("\nLees: hoge correlatie + beta > 1 t.o.v. S&P/Nasdaq betekent dat HBAR")
    print("vooral een risk-on/risk-off-beta is die met de aandelenmarkt meebeweegt.")
    print("Dan telt de brede stemming meer dan HBAR-specifiek nieuws -- en is een")
    print("risk-on/risk-off-indicator op het dashboard zinvoller dan losse koppen.")


if __name__ == "__main__":
    asyncio.run(main())
