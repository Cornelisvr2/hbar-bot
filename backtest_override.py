"""
backtest_override.py -- wat had de nieuws-override THEORETISCH opgeleverd?

Vraag: als we bij elke bewezen grote gebeurtenis HBAR hadden aangehouden
(long) of naar USDC waren gegaan (verdedigend), hoeveel meer/minder dan de
kale strategieen? Draait op news_events (gelabeld door event_study.py) en
candles_5m. Puur historisch, geen live handel.

Twee varianten:
  long   -> bij een positieve bewezen gebeurtenis HBAR aanhouden voor de
            horizon; anders USDC. Meet "extra HBAR verzamelen op goed nieuws".
  defensief -> bij een negatieve bewezen gebeurtenis naar USDC voor de
            horizon; anders HBAR. Meet "waarde beschermen op slecht nieuws".

Regels (afgestemd op het V4-plan, sectie 7):
  - alleen novelty=nieuw_feit, magnitude_guess >= MIN_MAG (default 4);
  - categorie moet in de event-study een gewicht >= MIN_GEWICHT en een
    richting hebben (uit news_weights); "marktcommentaar" en ruis vallen af;
  - pre_move_1h < MAX_PREMOVE sigma (anders al ingeprijsd, te laat);
  - swap-rondje kost FEE (default 0,8%); horizon HORIZON_H uur.
Vergelijkt eindwaarde met HBAR-vasthouden, USDC en de kale pool.

    docker compose run --rm -T hbar-bot python3 backtest_override.py --variant long
    docker compose run --rm -T hbar-bot python3 backtest_override.py --variant defensief --min-mag 4 --fee 0.8
Rapporteert ook de 20 gebeurtenissen die het meest bijdroegen (met bron).
"""
import asyncio
import os
import sys
from bisect import bisect_right
from datetime import timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

INLEG = 2000.0


class Prijs:
    def __init__(self, rows):
        self.t = [r["ts"].timestamp() for r in rows]
        self.c = [r["close"] for r in rows]

    def at(self, ts):
        i = bisect_right(self.t, ts) - 1
        return self.c[i] if 0 <= i < len(self.c) else None


async def main():
    a = sys.argv
    variant = a[a.index("--variant") + 1] if "--variant" in a else "long"
    min_mag = int(a[a.index("--min-mag") + 1]) if "--min-mag" in a else 4
    min_gewicht = float(a[a.index("--min-gewicht") + 1]) if "--min-gewicht" in a else 1.3
    max_premove = float(a[a.index("--max-premove") + 1]) if "--max-premove" in a else 0.5
    fee = float(a[a.index("--fee") + 1]) / 100 if "--fee" in a else 0.008
    horizon_h = float(a[a.index("--horizon") + 1]) if "--horizon" in a else 8.0

    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    async with db._pool.acquire() as conn:
        prijs = Prijs(await conn.fetch("SELECT ts, close FROM candles_5m WHERE symbol='HBAR' ORDER BY ts"))
        weights = await conn.fetch("SELECT asset, value, weight, direction FROM news_weights WHERE dimension='category'")
        ev = await conn.fetch(
            """SELECT published_at, asset, entity, category, novelty, magnitude_guess, event_key,
                      source_feed, headline, pre_move_1h, abn_ret_4h
               FROM news_events WHERE labeled_at IS NOT NULL AND novelty='nieuw_feit'
               ORDER BY published_at""")
    if not prijs.t:
        print("Geen candles.")
        return
    # gewicht+richting per (meetasset, categorie)
    W = {(r["asset"], r["value"]): (r["weight"], r["direction"]) for r in weights}

    def meetasset(r):
        return "HBAR" if (r["asset"] == "HBAR" or r["entity"] == "HBAR") else "BTC"

    # bepaal de triggers
    triggers = []
    for r in ev:
        if r["magnitude_guess"] < min_mag or r["pre_move_1h"] is None or abs(r["pre_move_1h"]) >= max_premove:
            continue
        g, d = W.get((meetasset(r), r["category"]), (1.0, None))
        if g < min_gewicht or d is None:
            continue
        # long-variant: alleen positieve richting; defensief: alleen negatieve
        if variant == "long" and d <= 0:
            continue
        if variant == "defensief" and d >= 0:
            continue
        triggers.append(r)

    # simuleer op HBAR-koers: buiten trigger-vensters de grondstand aanhouden.
    # long: grondstand USDC, in venster HBAR. defensief: grondstand HBAR, in venster USDC.
    grond_hbar = (variant == "defensief")
    # bouw tijdsvensters (start, eind)
    vensters = sorted((r["published_at"].timestamp(), r["published_at"].timestamp() + horizon_h * 3600, r) for r in triggers)
    # merge overlappende vensters van dezelfde richting
    merged = []
    for s0, s1, r in vensters:
        if merged and s0 <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], s1), merged[-1][2])
        else:
            merged.append((s0, s1, r))

    # loop over de hele periode in HBAR-eenheden vs USDC
    waarde = INLEG
    in_hbar = grond_hbar
    p_start = prijs.c[0]
    eenheden = INLEG / p_start if in_hbar else 0.0
    usdc = 0.0 if in_hbar else INLEG
    swaps = 0
    bijdragen = []

    punten = sorted(set([prijs.t[0], prijs.t[-1]] + [m[0] for m in merged] + [m[1] for m in merged]))
    huidige = grond_hbar
    for i in range(len(punten) - 1):
        t = punten[i]
        in_venster = any(s0 <= t < s1 for s0, s1, _ in merged)
        wil_hbar = (not grond_hbar and in_venster) or (grond_hbar and not in_venster)
        if wil_hbar != huidige:
            p = prijs.at(t)
            if p:
                if wil_hbar:  # USDC -> HBAR
                    eenheden = (usdc * (1 - fee)) / p; usdc = 0.0
                else:          # HBAR -> USDC
                    usdc = eenheden * p * (1 - fee); eenheden = 0.0
                swaps += 1
                huidige = wil_hbar
    # eindwaarde
    eind = usdc + eenheden * prijs.c[-1]

    # bijdrage per trigger (grof: rendement over het venster)
    for s0, s1, r in merged:
        p0, p1 = prijs.at(s0), prijs.at(s1)
        if p0 and p1:
            rr = (p1 / p0 - 1) * 100
            bijdragen.append((rr if not grond_hbar else -rr, r))

    hodl = INLEG * (prijs.c[-1] / prijs.c[0])
    print(f"\n=== Override-backtest ({variant}) ===")
    print(f"triggers: {len(triggers)} -> {len(merged)} vensters | horizon {horizon_h:.0f}u | fee {fee*100:.1f}% | {swaps} swaps")
    print(f"filters: magnitude>={min_mag}, gewicht>={min_gewicht}, |pre_move|<{max_premove}\n")
    print(f"  {variant}-strategie      €{eind:8.2f}  ({(eind/INLEG-1)*100:+.1f}%)")
    print(f"  HBAR vasthouden         €{hodl:8.2f}  ({(hodl/INLEG-1)*100:+.1f}%)")
    print(f"  USDC vasthouden         €{INLEG:8.2f}  (+0.0%)")
    print(f"  (kale pool ~ €2577 uit pool_rendement.py)")
    print(f"\nGrootste bijdragen (rendement over het venster, met bron):")
    for rr, r in sorted(bijdragen, key=lambda x: -abs(x[0]))[:20]:
        print(f"  {r['published_at']:%Y-%m-%d} {rr:+5.1f}%  {r['category']:20s} {(r['source_feed'] or '?')[:18]:18s} {r['headline'][:52]}")


if __name__ == "__main__":
    asyncio.run(main())
