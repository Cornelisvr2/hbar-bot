"""
event_study.py -- de markt laat het nieuws beoordelen (fase 3).

Per gebeurtenis in news_events (nog zonder labeled_at, horizon verstreken):
  pre_move_1h    rendement in het uur VÓÓR de kop ("al ingeprijsd")
  abn_ret_{1,4,24}h   rendement na de kop, gedeeld door de normale
                 volatiliteit van dat uur op dat moment (rollend 30d) -> z
  abn_vol_{1,4}h volume na de kop t.o.v. het rollende gemiddelde -> ratio
  exc_ret_*      alleen HBAR: HBAR-rendement minus beta*BTC-rendement
                 (beta uit 30d-regressie op uurrendementen)
MACRO-gebeurtenissen worden op BTC gemeten (entity macro/markt_breed).

Daarna, over alle gelabelde gebeurtenissen:
  news_weights   per (asset, dimensie, waarde): gewicht = gemiddelde
                 |abn_ret_4h| gedeeld door het basisniveau (gemiddelde
                 |z| rond willekeurige momenten ~ 0.8 voor een z-score),
                 gekrompen naar 1 bij n<20; richting als tekenconsistentie
                 > 65% over n>=20; gewicht 0 als <= 1.1 (ruis).
  rapport        "wat bewoog de markt": top-gebeurtenissen, per categorie,
                 per kwartaal, per bron -> stdout + logs/event_study_rapport.md

    docker compose run --rm -T hbar-bot python3 event_study.py --labelen
    docker compose run --rm -T hbar-bot python3 event_study.py --gewichten
    docker compose run --rm -T hbar-bot python3 event_study.py --rapport
    docker compose run --rm -T hbar-bot python3 event_study.py --alles
Dagelijkse cron: --labelen (nieuwe gebeurtenissen), wekelijks --gewichten.
"""
import asyncio
import math
import os
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASISNIVEAU_Z = 0.80      # E|z| voor normaalverdeling = 0.798
RUIS_GRENS = 1.10
MIN_N_RICHTING = 20
HORIZONS = (1, 4, 24)


class Reeks:
    """5-min-candles van één symbool met snelle lookups en rollende volatiliteit per uur."""

    def __init__(self, rows):
        self.t = [r["ts"].timestamp() for r in rows]
        self.c = [r["close"] for r in rows]
        self.v = [r["volume"] for r in rows]
        # uurrendementen op de 5-min-grid (12 candles) + rollende sigma over 30d (720 uur)
        n = len(self.c)
        self.hr = [None] * n
        for i in range(12, n):
            if self.c[i - 12] > 0:
                self.hr[i] = math.log(self.c[i] / self.c[i - 12])
        self.sig = [None] * n
        venster = 30 * 24 * 12
        som = som2 = cnt = 0
        for i in range(n):
            x = self.hr[i]
            if x is not None:
                som += x; som2 += x * x; cnt += 1
            j = i - venster
            if j >= 0 and self.hr[j] is not None:
                som -= self.hr[j]; som2 -= self.hr[j] ** 2; cnt -= 1
            if cnt > 200:
                var = som2 / cnt - (som / cnt) ** 2
                self.sig[i] = math.sqrt(max(var, 1e-12))
        self.vol_gem = [None] * n
        som = cnt = 0
        for i in range(n):
            som += self.v[i]; cnt += 1
            j = i - venster
            if j >= 0:
                som -= self.v[j]; cnt -= 1
            if cnt > 200:
                self.vol_gem[i] = som / cnt

    def idx(self, ts):
        i = bisect_right(self.t, ts) - 1
        return i if i >= 0 else None

    def ret(self, ts, hours):
        i, j = self.idx(ts), self.idx(ts + hours * 3600)
        if i is None or j is None or j <= i or self.t[j] < ts + hours * 3600 - 600:
            return None
        return math.log(self.c[j] / self.c[i])

    def z(self, ts, hours):
        r, i = self.ret(ts, hours), self.idx(ts)
        if r is None or i is None or self.sig[i] is None:
            return None
        return r / (self.sig[i] * math.sqrt(hours))

    def vol_ratio(self, ts, hours):
        i, j = self.idx(ts), self.idx(ts + hours * 3600)
        if i is None or j is None or j <= i or self.vol_gem[i] is None:
            return None
        return (sum(self.v[i + 1:j + 1]) / (j - i)) / self.vol_gem[i]

    def beta(self, ts, other, dagen=30):
        i0, i1 = self.idx(ts - dagen * 86400), self.idx(ts)
        if i0 is None or i1 is None or i1 - i0 < 500:
            return 1.0
        xs, ys = [], []
        for k in range(i0, i1, 12):
            a, b = other.hr[k] if k < len(other.hr) else None, self.hr[k]
            if a is not None and b is not None:
                xs.append(a); ys.append(b)
        if len(xs) < 50:
            return 1.0
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        var = sum((x - mx) ** 2 for x in xs)
        return cov / var if var > 0 else 1.0


async def laad_reeksen(db):
    uit = {}
    async with db._pool.acquire() as conn:
        for sym in ("BTC", "HBAR"):
            rows = await conn.fetch("SELECT ts, close, volume FROM candles_5m WHERE symbol = $1 ORDER BY ts", sym)
            uit[sym] = Reeks(rows)
            print(f"[event-study] {sym}: {len(rows)} candles", flush=True)
    return uit


async def labelen(db, reeksen):
    nu = datetime.now(timezone.utc)
    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, asset, entity, published_at FROM news_events WHERE labeled_at IS NULL AND published_at < $1",
            nu - timedelta(hours=25))
    print(f"[event-study] {len(rows)} gebeurtenissen te labelen", flush=True)
    updates, n = [], 0
    for r in rows:
        ts = r["published_at"].timestamp()
        sym = "HBAR" if (r["asset"] == "HBAR" or r["entity"] == "HBAR") else "BTC"
        R = reeksen[sym]
        pre = R.ret(ts - 3600, 1)
        abn = {h: R.z(ts, h) for h in HORIZONS}
        vol = {h: R.vol_ratio(ts, h) for h in (1, 4)}
        exc = {h: None for h in HORIZONS}
        if sym == "HBAR":
            b = R.beta(ts, reeksen["BTC"])
            for h in HORIZONS:
                rh, rb = R.ret(ts, h), reeksen["BTC"].ret(ts, h)
                if rh is not None and rb is not None:
                    exc[h] = rh - b * rb
        if abn[1] is None and abn[4] is None:
            continue  # geen candles rond dit moment (gat in data)
        updates.append((pre, abn[1], abn[4], abn[24], vol[1], vol[4], exc[1], exc[4], exc[24], nu, r["id"]))
        n += 1
    if updates:
        async with db._pool.acquire() as conn:
            await conn.executemany(
                """UPDATE news_events SET pre_move_1h=$1, abn_ret_1h=$2, abn_ret_4h=$3, abn_ret_24h=$4,
                   abn_vol_1h=$5, abn_vol_4h=$6, exc_ret_1h=$7, exc_ret_4h=$8, exc_ret_24h=$9, labeled_at=$10
                   WHERE id=$11""", updates)
    print(f"[event-study] {n} gelabeld")


def _groep_stats(items):
    """items: lijst (abn4, exc4_of_None). -> gewicht, richting, n"""
    zs = [a for a, _ in items if a is not None]
    n = len(zs)
    if n == 0:
        return 1.0, None, 0
    ruw = (sum(abs(z) for z in zs) / n) / BASISNIVEAU_Z
    krimp = n / (n + 20)                      # n=20 -> half tussen 1 en ruw
    gewicht = 1.0 + krimp * (ruw - 1.0)
    if gewicht <= RUIS_GRENS:
        gewicht = 0.0
    richting = None
    if n >= MIN_N_RICHTING:
        pos = sum(1 for z in zs if z > 0) / n
        if pos >= 0.65:
            richting = 1.0
        elif pos <= 0.35:
            richting = -1.0
    return round(gewicht, 3), richting, n


async def gewichten(db):
    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT asset, entity, category, novelty, source_feed, abn_ret_4h, exc_ret_4h FROM news_events WHERE labeled_at IS NOT NULL")
    groepen = defaultdict(list)
    for r in rows:
        meetasset = "HBAR" if (r["asset"] == "HBAR" or r["entity"] == "HBAR") else "BTC"
        item = (r["abn_ret_4h"], r["exc_ret_4h"])
        groepen[(meetasset, "category", r["category"])].append(item)
        groepen[(meetasset, "novelty", r["novelty"])].append(item)
        groepen[(meetasset, "source", (r["source_feed"] or "?")[:60])].append(item)
        groepen[(meetasset, "cat_nov", f"{r['category']}|{r['novelty']}")].append(item)
    uit = []
    for (asset, dim, val), items in groepen.items():
        g, d, n = _groep_stats(items)
        uit.append((asset, dim, val, g, d, n))
    async with db._pool.acquire() as conn:
        await conn.executemany(
            """INSERT INTO news_weights (asset, dimension, value, weight, direction, n, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6, now())
               ON CONFLICT (asset, dimension, value) DO UPDATE SET weight=EXCLUDED.weight, direction=EXCLUDED.direction,
               n=EXCLUDED.n, updated_at=now()""", uit)
    print(f"[event-study] {len(uit)} gewichten bijgewerkt")


async def rapport(db):
    async with db._pool.acquire() as conn:
        ev = await conn.fetch(
            """SELECT asset, entity, category, novelty, magnitude_guess, event_key, headline, published_at, source_feed,
                      pre_move_1h, abn_ret_1h, abn_ret_4h, abn_ret_24h, abn_vol_4h, exc_ret_4h
               FROM news_events WHERE labeled_at IS NOT NULL""")
        w = await conn.fetch("SELECT * FROM news_weights ORDER BY asset, dimension, weight DESC")
    L = []
    P = L.append
    P(f"# Wat bewoog de markt -- event-study over {len(ev)} gebeurtenissen\n")
    P(f"_Gegenereerd {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. z = beweging gedeeld door de normale volatiliteit van dat moment; |z| > 2 is uitzonderlijk._\n")

    def tabel(kop, rijen, kolommen):
        P(f"\n## {kop}\n")
        P("| " + " | ".join(kolommen) + " |")
        P("|" + "---|" * len(kolommen))
        for r in rijen:
            P("| " + " | ".join(str(x) for x in r) + " |")

    # 1. gewichten per categorie
    for asset in ("BTC", "HBAR"):
        rijen = [(r["value"], r["n"], f"{r['weight']:.2f}", {1.0: "omhoog", -1.0: "omlaag"}.get(r["direction"], "geen"))
                 for r in w if r["asset"] == asset and r["dimension"] == "category"]
        tabel(f"{asset}: gewicht per categorie (1,00 = toeval; 0 = ruis)", rijen, ["categorie", "n", "gewicht", "richting"])
        rijen = [(r["value"], r["n"], f"{r['weight']:.2f}") for r in w if r["asset"] == asset and r["dimension"] == "novelty"]
        tabel(f"{asset}: gewicht per nieuwheid", rijen, ["nieuwheid", "n", "gewicht"])
        rijen = [(r["value"], r["n"], f"{r['weight']:.2f}") for r in w if r["asset"] == asset and r["dimension"] == "source" and r["n"] >= 30][:15]
        tabel(f"{asset}: bronnen met >= 30 koppen, op gewicht", rijen, ["bron", "n", "gewicht"])

    # 2. magnitude_guess vs werkelijke beweging (kalibratie van de LLM-inschatting)
    per_m = defaultdict(list)
    for r in ev:
        if r["abn_ret_4h"] is not None:
            per_m[r["magnitude_guess"]].append(abs(r["abn_ret_4h"]))
    tabel("Klopt de omvang-inschatting van de LLM? gem |z| na 4u per magnitude",
          [(m, len(v), f"{sum(v) / len(v):.2f}") for m, v in sorted(per_m.items())], ["magnitude", "n", "gem |z| 4u"])

    # 3. al ingeprijsd?
    paren = [(r["pre_move_1h"], r["abn_ret_1h"]) for r in ev if r["pre_move_1h"] is not None and r["abn_ret_1h"] is not None]
    if len(paren) > 50:
        zelfde = sum(1 for p, a in paren if (p > 0) == (a > 0)) / len(paren)
        P(f"\n## Al ingeprijsd?\nBij {zelfde:.0%} van de gebeurtenissen had de koers in het uur vóór de kop al dezelfde richting als het uur erna (50% = geen verband). "
          f"Hoe hoger, hoe meer het nieuws achter de koers aanloopt.\n")

    # 4. top-gebeurtenissen per jaar (op |z| 4u, gegroepeerd op event_key)
    per_key = defaultdict(list)
    for r in ev:
        if r["abn_ret_4h"] is not None:
            per_key[(r["published_at"].year, r["event_key"].lower())].append(r)
    for jaar in sorted({k[0] for k in per_key}):
        top = sorted(((k, v) for k, v in per_key.items() if k[0] == jaar),
                     key=lambda kv: -max(abs(x["abn_ret_4h"]) for x in kv[1]))[:15]
        rijen = []
        for (j, key), items in top:
            x = max(items, key=lambda r: abs(r["abn_ret_4h"]))
            rijen.append((x["published_at"].strftime("%m-%d"), x["category"], x["event_key"][:40], len(items),
                          f"{x['abn_ret_1h'] or 0:+.1f}", f"{x['abn_ret_4h']:+.1f}", f"{x['abn_ret_24h'] or 0:+.1f}"))
        tabel(f"{jaar}: grootste bewegingen na nieuws (z na 1u / 4u / 24u)", rijen,
              ["datum", "categorie", "gebeurtenis", "koppen", "1u", "4u", "24u"])

    # 5. per kwartaal: welke categorie deed ertoe (regime-drift)
    per_q = defaultdict(lambda: defaultdict(list))
    for r in ev:
        if r["abn_ret_4h"] is not None:
            q = f"{r['published_at'].year}Q{(r['published_at'].month - 1) // 3 + 1}"
            per_q[q][r["category"]].append(abs(r["abn_ret_4h"]))
    rijen = []
    for q in sorted(per_q):
        cats = sorted(per_q[q].items(), key=lambda kv: -(sum(kv[1]) / len(kv[1])))
        rijen.append((q, sum(len(v) for v in per_q[q].values()),
                      ", ".join(f"{c} ({sum(v) / len(v) / BASISNIVEAU_Z:.1f})" for c, v in cats[:3] if len(v) >= 5)))
    tabel("Per kwartaal: categorieën met de grootste beweging (gewicht)", rijen, ["kwartaal", "n", "top-3 categorieën"])

    tekst = "\n".join(L)
    pad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "event_study_rapport.md")
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    open(pad, "w").write(tekst)
    print(tekst)
    print(f"\n[rapport] {pad}")


async def main():
    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    a = sys.argv
    alles = "--alles" in a
    if alles or "--labelen" in a:
        reeksen = await laad_reeksen(db)
        await labelen(db, reeksen)
    if alles or "--gewichten" in a:
        await gewichten(db)
    if alles or "--rapport" in a:
        await rapport(db)
    if not any(x in a for x in ("--alles", "--labelen", "--gewichten", "--rapport")):
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())
