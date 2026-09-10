"""
backfill_nieuws.py -- twee jaar nieuws terugladen en classificeren.

Bronnen:
  coindesk  CoinDesk Data API (voormalig CryptoCompare), nieuwsarchief van
            100+ uitgevers, gepagineerd terug in de tijd. COINDESK_API_KEY.
            Koppen worden op trefwoord aan BTC en/of HBAR gekoppeld.
  gdelt     GDELT DOC 2.0 (keyloos): wereldnieuws per dag op macro-
            trefwoorden (Fed, Treasury, tarieven, Iran, olie, CPI ...).
            Max 250 per query -> per dag één query per trefwoordgroep.

Stappen (elk apart aan te roepen, allemaal hervatbaar):
  --ophalen     bronnen -> news_raw (ontdubbeld op genormaliseerde kop,
                ruisfilter uit rss_news_client, trefwoordpoort voor MACRO)
  --classificeren  news_raw (classified=false) -> Claude Haiku -> news_events
                (MACRO alleen bewaren bij magnitude >= 3; parallel, met
                --workers N, standaard 4)

    docker compose run --rm -T hbar-bot python3 backfill_nieuws.py --ophalen --dagen 730
    docker compose run --rm -T hbar-bot python3 backfill_nieuws.py --classificeren --workers 4
    docker compose run --rm -T hbar-bot python3 backfill_nieuws.py --classificeren --limit 200   # proefrun
    docker compose run --rm -T hbar-bot python3 backfill_nieuws.py --status

Kosten: ~0,0007 USD per classificatie (Haiku). Geschat 10-20k koppen na
filtering over 2 jaar -> 10-15 USD eenmalig.
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rss_news_client import ASSET_KEYWORDS, is_noise_headline, normalize_headline  # noqa: E402

UA = {"User-Agent": "hbar-bot-backfill/1.0"}
COINDESK_URL = "https://data-api.coindesk.com/news/v1/article/list"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERIES = {
    "fed": '("Federal Reserve" OR Powell OR FOMC OR "rate cut" OR "rate hike") sourcelang:english',
    "treasury": '(Bessent OR Yellen OR "Treasury Secretary" OR "Treasury yields") sourcelang:english',
    "trade": '(tariffs OR "trade war" OR sanctions) (markets OR stocks OR economy) sourcelang:english',
    "geo": '(Iran OR Israel OR Russia OR Taiwan OR Houthi) (strike OR attack OR war OR missile) sourcelang:english',
    "inflation": '("inflation data" OR CPI OR "jobs report" OR payrolls OR recession OR "oil prices") sourcelang:english',
    "crypto_reg": '(SEC OR regulation OR ETF) (bitcoin OR crypto) sourcelang:english',
}
GDELT_DOMAINS_OK = ("reuters.com", "apnews.com", "cnbc.com", "bloomberg.com", "ft.com", "wsj.com", "bbc.co.uk",
                    "bbc.com", "theguardian.com", "nytimes.com", "washingtonpost.com", "politico.com",
                    "axios.com", "marketwatch.com", "cnn.com", "foxbusiness.com", "aljazeera.com",
                    "france24.com", "dw.com", "economist.com", "barrons.com", "yahoo.com")


# ------------------------------------------------------------------ ophalen
def _assets_voor(title: str, keywords: str = "") -> list[str]:
    t = f"{title} {keywords}".lower()
    uit = []
    if any(k in t for k in ASSET_KEYWORDS["BTC"]):
        uit.append("BTC")
    if any(k in t for k in ASSET_KEYWORDS["HBAR"]):
        uit.append("HBAR")
    return uit


def haal_coindesk(dagen: int, key: str):
    """Genereert (asset, title, ts, source_name, url) uit het CoinDesk-archief, nieuw -> oud."""
    grens = time.time() - dagen * 86400
    to_ts = int(time.time())
    n_calls = 0
    while to_ts > grens:
        r = requests.get(COINDESK_URL, params={"lang": "EN", "limit": 100, "to_ts": to_ts},
                         headers={"authorization": f"Apikey {key}", **UA}, timeout=30)
        n_calls += 1
        if r.status_code == 429:
            time.sleep(10)
            continue
        r.raise_for_status()
        data = r.json().get("Data") or []
        if not data:
            break
        oudste = to_ts
        for a in data:
            ts = int(a.get("PUBLISHED_ON") or 0)
            if ts <= 0:
                continue
            oudste = min(oudste, ts)
            titel = (a.get("TITLE") or "").strip()
            kw = a.get("KEYWORDS") or ""
            cats = " ".join(c.get("NAME", "") for c in (a.get("CATEGORY_DATA") or []))
            for asset in _assets_voor(titel, f"{kw} {cats}"):
                yield asset, titel, ts, (a.get("SOURCE_DATA") or {}).get("NAME", ""), a.get("URL", "")
        if oudste >= to_ts:
            break
        to_ts = oudste - 1
        if n_calls % 20 == 0:
            print(f"[coindesk] tot {datetime.fromtimestamp(to_ts, tz=timezone.utc):%Y-%m-%d} ({n_calls} calls)", flush=True)
        time.sleep(0.5)


def haal_gdelt(dagen: int):
    """Genereert (asset='MACRO', title, ts, domain, url) per dag per trefwoordgroep."""
    einde = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    dag = einde - timedelta(days=dagen)
    while dag < einde:
        volgende = dag + timedelta(days=1)
        for naam, q in GDELT_QUERIES.items():
            try:
                r = requests.get(GDELT_URL, params={
                    "query": q, "mode": "artlist", "maxrecords": 250, "format": "json", "sort": "datedesc",
                    "startdatetime": dag.strftime("%Y%m%d%H%M%S"), "enddatetime": volgende.strftime("%Y%m%d%H%M%S")},
                    headers=UA, timeout=40)
                if r.status_code != 200 or not r.text.strip().startswith("{"):
                    time.sleep(2)
                    continue
                for a in r.json().get("articles", []):
                    dom = (a.get("domain") or "").lower()
                    if not any(dom.endswith(d) for d in GDELT_DOMAINS_OK):
                        continue
                    titel = (a.get("title") or "").strip()
                    try:
                        ts = int(datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp())
                    except Exception:
                        continue
                    yield "MACRO", titel, ts, dom, a.get("url", "")
            except Exception as e:
                print(f"[gdelt] {dag:%Y-%m-%d} {naam}: {e}", flush=True)
            time.sleep(1.2)  # GDELT: max ~1 req/sec
        if dag.day == 1:
            print(f"[gdelt] {dag:%Y-%m}", flush=True)
        dag = volgende


async def ophalen(dagen: int, bronnen: list[str]):
    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    buffer, stats = [], {"in": 0, "ruis": 0, "poort": 0, "opgeslagen": 0}

    async def flush():
        nonlocal buffer
        if not buffer:
            return
        async with db._pool.acquire() as conn:
            res = await conn.executemany(
                "INSERT INTO news_raw (asset, headline, headline_key, published_at, source, source_name, url) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (asset, headline_key) DO NOTHING", buffer)
        stats["opgeslagen"] += len(buffer)
        buffer = []

    gens = []
    if "coindesk" in bronnen:
        key = os.environ.get("COINDESK_API_KEY")
        if not key:
            print("COINDESK_API_KEY ontbreekt -- coindesk overgeslagen")
        else:
            gens.append(("coindesk_archive", haal_coindesk(dagen, key)))
    if "gdelt" in bronnen:
        gens.append(("gdelt", haal_gdelt(dagen)))

    for bron, gen in gens:
        for asset, titel, ts, source_name, url in gen:
            stats["in"] += 1
            if is_noise_headline(titel, url):
                stats["ruis"] += 1
                continue
            if asset == "MACRO" and not any(k in titel.lower() for k in ASSET_KEYWORDS["MACRO"]):
                stats["poort"] += 1
                continue
            sleutel = normalize_headline(titel)
            if not sleutel:
                continue
            buffer.append((asset, titel[:300], sleutel, datetime.fromtimestamp(ts, tz=timezone.utc), bron, source_name[:80], url[:500]))
            if len(buffer) >= 500:
                await flush()
                print(f"[ophalen] {bron}: {stats}", flush=True)
        await flush()
    print(f"[ophalen] klaar: {stats} (opgeslagen = aangeboden; dubbelen zijn stil overgeslagen)")


# ------------------------------------------------------------ classificeren
async def classificeren(limit: int | None, workers: int):
    from postgres_client import PostgresClient
    from llm_sentiment_engine import LlmSentimentEngine
    db = PostgresClient()
    await db.connect()
    llm = LlmSentimentEngine()
    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, asset, headline, headline_key, published_at, source_name, url FROM news_raw "
            "WHERE classified = FALSE ORDER BY published_at DESC" + (f" LIMIT {int(limit)}" if limit else ""))
    print(f"[classificeren] {len(rows)} koppen te doen, {workers} parallel", flush=True)
    sem = asyncio.Semaphore(workers)
    teller = {"ok": 0, "bewaard": 0, "fout": 0, "t0": time.time()}

    async def doe(r):
        async with sem:
            cls = await asyncio.to_thread(llm.classify_headline, r["asset"], r["headline"])
        async with db._pool.acquire() as conn:
            if cls is None:
                teller["fout"] += 1
                await conn.execute("UPDATE news_raw SET skipped = 'llm_fout' WHERE id = $1", r["id"])
                return
            bewaar = not (r["asset"] == "MACRO" and cls.magnitude_guess < 3)
            if bewaar:
                await conn.execute(
                    """INSERT INTO news_events (asset, headline, headline_key, published_at, source_feed, url,
                                                category, entity, novelty, magnitude_guess, event_key, llm_rationale)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) ON CONFLICT (asset, headline_key) DO NOTHING""",
                    r["asset"], r["headline"], r["headline_key"], r["published_at"], r["source_name"], r["url"],
                    cls.category, cls.entity, cls.novelty, cls.magnitude_guess, cls.event_key, cls.rationale)
                teller["bewaard"] += 1
            await conn.execute("UPDATE news_raw SET classified = TRUE, skipped = $2 WHERE id = $1",
                               r["id"], None if bewaar else "te_klein")
            teller["ok"] += 1
            if teller["ok"] % 100 == 0:
                snelheid = teller["ok"] / max(time.time() - teller["t0"], 1)
                print(f"[classificeren] {teller['ok']}/{len(rows)} ({teller['bewaard']} bewaard, {teller['fout']} fout, {snelheid:.1f}/s)", flush=True)

    await asyncio.gather(*(doe(r) for r in rows))
    print(f"[classificeren] klaar: {teller['ok']} geclassificeerd, {teller['bewaard']} bewaard, {teller['fout']} fouten")


async def status():
    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    async with db._pool.acquire() as conn:
        raw = await conn.fetch("SELECT asset, source, count(*) n, sum(classified::int) gedaan, min(published_at)::date vanaf, max(published_at)::date tot FROM news_raw GROUP BY 1,2 ORDER BY 1,2")
        ev = await conn.fetch("SELECT asset, count(*) n, count(labeled_at) gelabeld, min(published_at)::date vanaf FROM news_events GROUP BY 1")
        c = await conn.fetch("SELECT symbol, count(*) n, min(ts)::date vanaf, max(ts)::date tot FROM candles_5m GROUP BY 1")
    print("news_raw:");    [print("  ", dict(r)) for r in raw]
    print("news_events:"); [print("  ", dict(r)) for r in ev]
    print("candles_5m:");  [print("  ", dict(r)) for r in c]


def main():
    a = sys.argv
    dagen = int(a[a.index("--dagen") + 1]) if "--dagen" in a else 730
    if "--ophalen" in a:
        bronnen = a[a.index("--bron") + 1].split(",") if "--bron" in a else ["coindesk", "gdelt"]
        asyncio.run(ophalen(dagen, bronnen))
    elif "--classificeren" in a:
        limit = int(a[a.index("--limit") + 1]) if "--limit" in a else None
        workers = int(a[a.index("--workers") + 1]) if "--workers" in a else 4
        asyncio.run(classificeren(limit, workers))
    elif "--status" in a:
        asyncio.run(status())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
