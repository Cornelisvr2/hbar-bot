"""
nieuws_inzoom.py -- diepere analyse van de koersreactie op nieuws.

Aanleiding (11 sep 2026): de event_study.py-samenvatting (4u-gemiddelde,
|z|>=2) poetste de kleine-maar-consistente reacties weg, en telde
gebeurtenissen dubbel (45 koppen over 1 hack = 45 "events"). Dit script
kijkt scherper:

  - KORTE horizons: 15m, 30m, 1u, 2u -- waar een cryptoreactie echt zit,
    vóór de bearmarkt-drift eroverheen walst.
  - EVENT-CLUSTERING: koppen binnen CLUSTER_UREN met hoge woordoverlap in
    hun event_key worden één gebeurtenis (sterkste kop als representant).
  - HIT-RATE i.p.v. gemiddelde: hoe vaak beweegt de koers ná deze categorie
    in dezelfde richting? Consistente kleine tikken > één grote uitschieter.
  - REGIME-SPLIT: apart voor bull- en bear-dagen (200-daags MA op BTC),
    zodat de bearmarkt-drift het signaal niet verbergt. Voor HBAR het
    BTC-gecorrigeerde excess-rendement.

Leest candles_5m en news_events (labeling niet nodig -- rekent zelf op de
5-min-candles). Puur analytisch, verandert de bot niet.

    docker compose run --rm -T hbar-bot python3 nieuws_inzoom.py --asset HBAR --sinds 2026-03-01
    docker compose run --rm -T hbar-bot python3 nieuws_inzoom.py --asset BTC --min-n 10
"""
import asyncio
import math
import os
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HORIZONS_MIN = [15, 30, 60, 120]      # minuten
CLUSTER_UREN = 24.0
WOORD_OVERLAP_DREMPEL = 0.5           # aandeel gedeelde woorden om als 1 event te tellen
STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "s", "hbar", "hedera", "bitcoin", "btc", "crypto"}


class Reeks:
    def __init__(self, rows):
        self.t = [r["ts"].timestamp() for r in rows]
        self.c = [r["close"] for r in rows]
        # rollende sigma van het 30-min-rendement over 30 dagen, voor z-scores
        n = len(self.c)
        step = 6  # 30 min = 6 candles
        self.r30 = [None] * n
        for i in range(step, n):
            if self.c[i - step] > 0:
                self.r30[i] = math.log(self.c[i] / self.c[i - step])
        self.sig30 = [None] * n
        venster = 30 * 24 * 12
        som = som2 = cnt = 0
        for i in range(n):
            x = self.r30[i]
            if x is not None:
                som += x; som2 += x * x; cnt += 1
            j = i - venster
            if j >= 0 and self.r30[j] is not None:
                som -= self.r30[j]; som2 -= self.r30[j] ** 2; cnt -= 1
            if cnt > 200:
                var = som2 / cnt - (som / cnt) ** 2
                self.sig30[i] = math.sqrt(max(var, 1e-12))

    def idx(self, ts):
        i = bisect_right(self.t, ts) - 1
        return i if i >= 0 else None

    def ret(self, ts, minuten):
        i = self.idx(ts)
        j = self.idx(ts + minuten * 60)
        if i is None or j is None or j <= i or self.t[j] < ts + minuten * 60 - 300:
            return None
        return math.log(self.c[j] / self.c[i])

    def sig_at(self, ts):
        i = self.idx(ts)
        return self.sig30[i] if i is not None else None

    def boven_ma200(self, ts):
        """Ruwe bull/bear: staat de koers boven het 200-daags (in 5-min-candles) gemiddelde?"""
        i = self.idx(ts)
        if i is None or i < 200 * 24 * 12:
            return None
        window = self.c[i - 200 * 24 * 12: i: 288]  # dagelijkse samples
        if not window:
            return None
        ma = sum(window) / len(window)
        return self.c[i] > ma


def kernwoorden(event_key):
    return {w for w in event_key.lower().replace("-", " ").split() if w not in STOP and len(w) > 2}


def cluster(events):
    """Groepeer events binnen CLUSTER_UREN met hoge woordoverlap. Retourneert lijst van representanten."""
    events = sorted(events, key=lambda e: e["ts"])
    clusters = []
    for e in events:
        e["_kw"] = kernwoorden(e["event_key"])
        geplaatst = False
        for c in clusters:
            laatste = c[-1]
            if e["ts"] - laatste["ts"] > CLUSTER_UREN * 3600:
                continue
            gedeeld = e["_kw"] & laatste["_kw"]
            kleinste = min(len(e["_kw"]), len(laatste["_kw"])) or 1
            # Samenvoegen als (a) genoeg woordoverlap, OF (b) zelfde categorie
            # binnen hetzelfde etmaal -- dan is het vrijwel zeker dezelfde
            # marktgebeurtenis (11 juli: Bonzo-hack -> Hedera-paniek, Upbit-
            # opschorting, Sauce-hack; geen gedeelde woorden, wel één event).
            zelfde_dag_categorie = (e["category"] == laatste["category"]
                                     and e["ts"] - laatste["ts"] <= CLUSTER_UREN * 3600)
            if len(gedeeld) / kleinste >= WOORD_OVERLAP_DREMPEL or zelfde_dag_categorie:
                c.append(e); geplaatst = True; break
        if not geplaatst:
            clusters.append([e])
    # per cluster: de kop met de grootste magnitude_guess als representant, ts = vroegste
    reps = []
    for c in clusters:
        rep = max(c, key=lambda x: x["magnitude_guess"])
        rep = dict(rep)
        rep["ts"] = min(x["ts"] for x in c)
        rep["cluster_grootte"] = len(c)
        reps.append(rep)
    return reps


async def main():
    a = sys.argv
    asset = a[a.index("--asset") + 1] if "--asset" in a else "HBAR"
    sinds = a[a.index("--sinds") + 1] if "--sinds" in a else "2025-09-01"
    min_n = int(a[a.index("--min-n") + 1]) if "--min-n" in a else 5

    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    async with db._pool.acquire() as conn:
        R = {s: Reeks(await conn.fetch("SELECT ts, close FROM candles_5m WHERE symbol=$1 ORDER BY ts", s))
             for s in ("BTC", "HBAR")}
        rows = await conn.fetch(
            """SELECT category, novelty, magnitude_guess, event_key, published_at
               FROM news_events
               WHERE (asset=$1 OR ($1='BTC' AND asset='MACRO')) AND published_at >= $2::timestamptz
               ORDER BY published_at""", asset, sinds)
    meet = R[asset]
    btc = R["BTC"]

    events = [{"category": r["category"], "novelty": r["novelty"], "magnitude_guess": r["magnitude_guess"],
               "event_key": r["event_key"], "ts": r["published_at"].timestamp()} for r in rows]
    voor = len(events)
    events = cluster(events)
    print(f"\n{asset} sinds {sinds}: {voor} koppen -> {len(events)} gebeurtenissen na clustering "
          f"(binnen {CLUSTER_UREN:.0f}u, woordoverlap>={WOORD_OVERLAP_DREMPEL:.0%})\n")

    # per categorie x horizon: hit-rate en gemiddelde excess-z, gesplitst naar regime
    per_cat = defaultdict(list)
    for e in events:
        # excess t.o.v. BTC (voor HBAR); voor BTC gewoon het eigen rendement
        row = {"category": e["category"], "novelty": e["novelty"], "regime": meet.boven_ma200(e["ts"])}
        for m in HORIZONS_MIN:
            r = meet.ret(e["ts"], m)
            if asset == "HBAR" and r is not None:
                rb = btc.ret(e["ts"], m)
                r = (r - rb) if rb is not None else None
            sig = meet.sig_at(e["ts"])
            row[f"z{m}"] = (r / (sig * math.sqrt(m / 30)) if (r is not None and sig) else None)
        per_cat[e["category"]].append(row)

    def blok(titel, filt):
        rijen = []
        for cat, lst in per_cat.items():
            sub = [x for x in lst if filt(x)]
            if len(sub) < min_n:
                continue
            cel = []
            for m in HORIZONS_MIN:
                zs = [x[f"z{m}"] for x in sub if x.get(f"z{m}") is not None]
                if not zs:
                    cel.append("   -"); continue
                gem = sum(zs) / len(zs)
                pos = sum(1 for z in zs if z > 0) / len(zs)
                hit = max(pos, 1 - pos)  # consistentie naar de dominante kant
                richting = "+" if pos >= 0.5 else "-"
                cel.append(f"{richting}{gem:+.2f}/{hit:.0%}")
            rijen.append((cat, len(sub), cel))
        rijen.sort(key=lambda r: -max(abs(float(c.split("/")[0].replace("+","").replace("-","") or 0))
                                       if "/" in c else 0 for c in r[2]))
        print(f"## {titel}")
        print(f"  {'categorie':22s} {'n':>3s}  " + "  ".join(f"{m}m(z/hit)".rjust(12) for m in HORIZONS_MIN))
        for cat, n, cel in rijen:
            print(f"  {cat:22s} {n:>3d}  " + "  ".join(c.rjust(12) for c in cel))
        print()

    blok("Alle dagen", lambda x: True)
    blok("Alleen BEAR-dagen (koers < MA200)", lambda x: x["regime"] is False)
    blok("Alleen BULL-dagen (koers > MA200)", lambda x: x["regime"] is True)
    print("Lezen: '-0.42/68%' = gemiddeld -0,42 sigma, en 68% van de gebeurtenissen")
    print("bewoog dezelfde (dominante) kant op. Hoge hit% + consistente richting = signaal,")
    print("ook als de sigma klein is. Voor HBAR is het rendement BTC-gecorrigeerd (excess).")


if __name__ == "__main__":
    asyncio.run(main())
