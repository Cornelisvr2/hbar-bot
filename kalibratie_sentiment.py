"""
kalibratie_sentiment.py -- is de LLM-sentimentscore voorspellend?

NIEUW (10 sep 2026, op verzoek; stap 3-voorcontrole uit PLAN.md). Geen
model, alleen meten: voor elke gescoorde headline in sentiment_log het
koersrendement (Binance, 5-min-candles) op t-1u (al ingeprijsd?), t+1u en
t+4u. Voor HBAR ook het BTC-gecorrigeerde 'excess'-rendement (HBAR minus
BTC, beta=1 -- grove maar eerlijke correctie voor marktbeta).

Geeft per asset:
  - n (na ontdubbeling op genormaliseerde kop)
  - Spearman-rangcorrelatie score <-> rendement (+1u, +4u, en -1u)
  - bucket-tabel: per scoreklasse gemiddeld rendement en 'hit rate'
    (teken van de score = teken van het rendement)
  - dezelfde tabel voor alleen idiosyncratische (asset-specifieke) koppen

Interpretatie:
  - correlatie ~0 en hit rate ~50%  -> score voorspelt niets (nog)
  - correlatie met -1u > met +1u    -> nieuws loopt achter de koers aan
  - alleen idiosyncratisch werkt    -> marktbrede koppen weglaten uit de score

Draaien IN de bot-container (heeft asyncpg, requests en DATABASE_URL):
    docker compose exec -T hbar-bot python3 kalibratie_sentiment.py
    docker compose exec -T hbar-bot python3 kalibratie_sentiment.py --dagen 14
Schrijft ook logs/kalibratie_sentiment.csv (één regel per headline) voor
eigen analyse in een spreadsheet.
"""
import asyncio
import csv
import os
import sys
import time
from bisect import bisect_right
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HORIZONS_H = (-1, 1, 4)
BUCKETS = ((-9, -0.3, "<= -0.3"), (-0.3, -0.1, "-0.3..-0.1"), (-0.1, 0.1, "neutraal"),
           (0.1, 0.3, "0.1..0.3"), (0.3, 9, ">= 0.3"))


def spearman(xs, ys):
    n = len(xs)
    if n < 5:
        return None
    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else None


class PriceSeries:
    def __init__(self, klines):
        self.t = [k.open_time for k in klines]
        self.c = [k.close for k in klines]

    def at(self, ts: float):
        i = bisect_right(self.t, ts) - 1
        return self.c[i] if i >= 0 else None

    def ret(self, ts: float, hours: float):
        p0, p1 = self.at(ts), self.at(ts + hours * 3600)
        if p0 is None or p1 is None or p0 <= 0:
            return None
        if ts + hours * 3600 > self.t[-1] + 300:  # horizon nog niet verstreken
            return None
        return (p1 / p0 - 1) * 100


async def laad_headlines(dagen: float):
    from postgres_client import PostgresClient
    from rss_news_client import normalize_headline
    db = PostgresClient()
    await db.connect()
    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT asset, headline, sentiment_score, confidence, is_idiosyncratic, created_at
               FROM sentiment_log
               WHERE created_at > now() - ($1 || ' days')::interval
               ORDER BY created_at""", str(dagen))
    gezien, uit = set(), []
    for r in rows:
        sleutel = (r["asset"], normalize_headline(r["headline"]))
        if sleutel in gezien:
            continue
        gezien.add(sleutel)
        ts = r["created_at"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        uit.append({"asset": r["asset"], "headline": r["headline"], "score": float(r["sentiment_score"]),
                    "conf": float(r["confidence"] or 0), "idio": bool(r["is_idiosyncratic"]),
                    "ts": ts.timestamp(), "tijd": ts.isoformat(timespec="minutes")})
    return rows and len(rows), uit


def tabel(rijen, veld, titel):
    print(f"\n  {titel}  (n={len(rijen)})")
    print(f"  {'scoreklasse':12s} {'n':>4s} {'gem +1u %':>10s} {'hit +1u':>8s} {'gem +4u %':>10s} {'hit +4u':>8s}")
    for lo, hi, naam in BUCKETS:
        b = [r for r in rijen if lo <= r["score"] < hi]
        if not b:
            continue
        def stats(h):
            v = [r[f"{veld}{h}"] for r in b if r.get(f"{veld}{h}") is not None]
            if not v:
                return "   -", "   -"
            gem = sum(v) / len(v)
            if naam == "neutraal":
                return f"{gem:+.2f}", "  n.v.t."
            hits = sum(1 for r in b if r.get(f"{veld}{h}") is not None and (r[f"{veld}{h}"] > 0) == (r["score"] > 0))
            return f"{gem:+.2f}", f"{100 * hits / len(v):.0f}%"
        g1, h1 = stats(1)
        g4, h4 = stats(4)
        print(f"  {naam:12s} {len(b):4d} {g1:>10s} {h1:>8s} {g4:>10s} {h4:>8s}")


def correlaties(rijen, veld, label):
    out = []
    for h in HORIZONS_H:
        paren = [(r["score"], r[f"{veld}{h}"]) for r in rijen if r.get(f"{veld}{h}") is not None]
        rho = spearman([p[0] for p in paren], [p[1] for p in paren])
        out.append(f"{h:+d}u: {rho:+.3f} (n={len(paren)})" if rho is not None else f"{h:+d}u: n.v.t.")
    print(f"  Spearman score<->{label}: " + " | ".join(out))


async def main():
    dagen = float(sys.argv[sys.argv.index("--dagen") + 1]) if "--dagen" in sys.argv else 30
    n_ruw, rijen = await laad_headlines(dagen)
    if not rijen:
        print("Geen headlines gevonden.")
        return
    print(f"sentiment_log: {n_ruw} regels, {len(rijen)} unieke headlines (laatste {dagen:g} dagen)")

    from binance_klines_client import BinanceKlinesClient
    client = BinanceKlinesClient()
    t0 = min(r["ts"] for r in rijen) - 2 * 3600
    t1 = time.time()
    series = {}
    for asset in ("BTC", "HBAR"):
        kl = client.fetch_range(asset, t0, t1, interval="5m")
        series[asset] = PriceSeries(kl)
        print(f"{asset}: {len(kl)} 5-min-candles opgehaald")

    for r in rijen:
        s = series[r["asset"]]
        for h in HORIZONS_H:
            r[f"ret{h}"] = s.ret(r["ts"], h)
            if r["asset"] == "HBAR":
                rb = series["BTC"].ret(r["ts"], h)
                r[f"exc{h}"] = (r[f"ret{h}"] - rb) if (r[f"ret{h}"] is not None and rb is not None) else None

    for asset in ("BTC", "HBAR"):
        sub = [r for r in rijen if r["asset"] == asset]
        if not sub:
            continue
        print(f"\n=== {asset} ===")
        correlaties(sub, "ret", "rendement")
        tabel(sub, "ret", "Alle koppen -- ruw rendement")
        idio = [r for r in sub if r["idio"]]
        if idio:
            tabel(idio, "ret", "Alleen asset-specifieke koppen -- ruw rendement")
        if asset == "HBAR":
            correlaties(sub, "exc", "excess (HBAR-BTC)")
            tabel(sub, "exc", "Alle koppen -- excess t.o.v. BTC")
            if idio:
                tabel(idio, "exc", "Alleen HBAR-specifiek -- excess t.o.v. BTC")

    # basisniveau: hoe groot is een 'normale' beweging?
    for asset in ("BTC", "HBAR"):
        v = [abs(r["ret1"]) for r in rijen if r["asset"] == asset and r.get("ret1") is not None]
        if v:
            print(f"\n{asset}: gemiddelde |1u-beweging| rond een kop = {sum(v) / len(v):.2f}%")

    pad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "kalibratie_sentiment.csv")
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    velden = ["asset", "tijd", "score", "conf", "idio", "ret-1", "ret1", "ret4", "exc-1", "exc1", "exc4", "headline"]
    with open(pad, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=velden, extrasaction="ignore")
        w.writeheader()
        for r in rijen:
            w.writerow({k: (round(r[k], 3) if isinstance(r.get(k), float) else r.get(k, "")) for k in velden})
    print(f"\nCSV: {pad}")


if __name__ == "__main__":
    asyncio.run(main())
