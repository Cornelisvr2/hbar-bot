"""
macro_data_loader.py -- fase 2 nieuws/macro-plan (10 sep 2026).

Haalt externe reeksen op en zet ze in `macro_inputs` (source, series, ts,
value) en geplande gebeurtenissen in `event_calendar`. Elke bron in zijn
eigen try/except: één kapotte API mag de rest niet tegenhouden. Idempotent
(upsert), dus veilig om vaker te draaien.

Bronnen (stand 10 sep 2026):
  fred         DXY-proxy DTWEXBGS, DGS10, DGS2, DFII10 (reële rente), DFF,
               VIXCLS, SP500 -- dagreeksen, FRED_API_KEY
  fmp          economische kalender (VS, impact High/Medium): FOMC, CPI,
               NFP, PPI, retail sales ... -- FMP_API_KEY
  forexfactory zelfde kalender, keyloos, als reserve
  binance_fut  funding rate (8u) en open interest (1u) BTCUSDT + HBARUSDT
  fng          Fear & Greed (alternative.me)
  defillama    TVL Hedera-chain
  coingecko    BTC-dominantie, totale markt-cap, stablecoin-cap (keyloos, /global)
  coinmarketcal geplande crypto-events BTC/HBAR (v2, gratis plan: 7 dagen
               vooruit, alleen titel+datum) -- COINMARKETCAL_API_KEY

Draaien (in de bot-container, 1x per dag via cron; Binance-reeksen mogen
vaker):
    docker compose run --rm -T hbar-bot python3 macro_data_loader.py
    docker compose run --rm -T hbar-bot python3 macro_data_loader.py --bron fred,fmp
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UA = {"User-Agent": "hbar-bot-macro-loader/1.0"}
FRED_SERIES = ["DTWEXBGS", "DGS10", "DGS2", "DFII10", "DFF", "VIXCLS", "SP500"]
FUT_SYMBOLS = ["BTCUSDT", "HBARUSDT"]


import re as _re
_KEY_RE = _re.compile(r"(apikey|api_key|x-api-key|token)=[^&\s]+", _re.I)


def _maskeer(tekst: str) -> str:
    """Keys nooit in logs/foutmeldingen (10 sep 2026: FMP-key lekte via een 403-URL)."""
    return _KEY_RE.sub(r"\1=***", str(tekst))


def _get(url, params=None, timeout=20):
    try:
        r = requests.get(url, params=params, headers=UA, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise RuntimeError(_maskeer(e)) from None


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("%", "").replace("K", "e3").replace("M", "e6").replace("B", "e9"))
    except Exception:
        return None


# ---------------------------------------------------------------- bronnen
def laad_fred(dagen=120):
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise EnvironmentError("FRED_API_KEY ontbreekt")
    start = (datetime.now(timezone.utc) - timedelta(days=dagen)).date().isoformat()
    rijen = []
    for sid in FRED_SERIES:
        data = _get("https://api.stlouisfed.org/fred/series/observations",
                    {"series_id": sid, "api_key": key, "file_type": "json", "observation_start": start})
        for o in data.get("observations", []):
            v = _num(o.get("value"))
            if v is None or o.get("value") == ".":
                continue
            rijen.append(("fred", sid, datetime.fromisoformat(o["date"]).replace(tzinfo=timezone.utc), v))
        time.sleep(0.2)
    return rijen, []


def laad_fmp(dagen_vooruit=14, dagen_terug=7):
    key = os.environ.get("FMP_API_KEY")
    if not key:
        raise EnvironmentError("FMP_API_KEY ontbreekt")
    nu = datetime.now(timezone.utc)
    params = {"from": (nu - timedelta(days=dagen_terug)).date().isoformat(),
              "to": (nu + timedelta(days=dagen_vooruit)).date().isoformat(), "apikey": key}
    try:
        data = _get("https://financialmodelingprep.com/stable/economic-calendar", params)
    except Exception as e1:
        try:
            data = _get("https://financialmodelingprep.com/api/v3/economic_calendar", params)
        except Exception as e2:
            raise RuntimeError(f"stable: {e1} | v3: {e2}")
    events = []
    for e in data:
        if (e.get("country") or "").upper() not in ("US", "USA", "UNITED STATES"):
            continue
        impact = (e.get("impact") or "").lower()
        if impact not in ("high", "medium"):
            continue
        try:
            ts = datetime.fromisoformat(str(e["date"]).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        events.append(("fmp", e.get("event", "")[:120], ts, "US", impact, "markt_breed",
                       _num(e.get("estimate")), _num(e.get("previous")), _num(e.get("actual"))))
    return [], events


def laad_forexfactory():
    data = _get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
    events = []
    for e in data:
        if e.get("country") != "USD" or (e.get("impact") or "").lower() not in ("high", "medium"):
            continue
        try:
            ts = datetime.fromisoformat(str(e["date"]).replace("Z", "+00:00"))
        except Exception:
            continue
        events.append(("forexfactory", e.get("title", "")[:120], ts.astimezone(timezone.utc), "US",
                       (e.get("impact") or "").lower(), "markt_breed",
                       _num(e.get("forecast")), _num(e.get("previous")), _num(e.get("actual"))))
    return [], events


def laad_binance_futures():
    rijen = []
    for sym in FUT_SYMBOLS:
        for f in _get("https://fapi.binance.com/fapi/v1/fundingRate", {"symbol": sym, "limit": 90}):
            rijen.append(("binance_fut", f"funding_{sym}",
                          datetime.fromtimestamp(f["fundingTime"] / 1000, tz=timezone.utc), float(f["fundingRate"])))
        for o in _get("https://fapi.binance.com/futures/data/openInterestHist",
                      {"symbol": sym, "period": "1h", "limit": 168}):
            rijen.append(("binance_fut", f"oi_usd_{sym}",
                          datetime.fromtimestamp(o["timestamp"] / 1000, tz=timezone.utc), float(o["sumOpenInterestValue"])))
        time.sleep(0.3)
    return rijen, []


def laad_fng():
    data = _get("https://api.alternative.me/fng/", {"limit": 60, "format": "json"})
    rijen = [("fng", "fear_greed", datetime.fromtimestamp(int(d["timestamp"]), tz=timezone.utc), float(d["value"]))
             for d in data.get("data", [])]
    return rijen, []


def laad_defillama():
    data = _get("https://api.llama.fi/v2/historicalChainTvl/Hedera")
    rijen = [("defillama", "tvl_hedera_usd", datetime.fromtimestamp(d["date"], tz=timezone.utc), float(d["tvl"]))
             for d in data[-120:]]
    return rijen, []


def laad_coingecko_global():
    g = _get("https://api.coingecko.com/api/v3/global")["data"]
    ts = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    rijen = [("coingecko", "btc_dominance_pct", ts, float(g["market_cap_percentage"]["btc"])),
             ("coingecko", "total_mcap_usd", ts, float(g["total_market_cap"]["usd"]))]
    return rijen, []


def laad_coinmarketcal():
    """
    CoinMarketCal v2 (10 sep 2026): het oude host developers.coinmarketcal.com
    bestaat niet meer. Gratis plan: komende 7 dagen, top-100 coins, alleen
    titel+datum (geen categorie/impact), 24u vertraagd, 3k calls/mnd.
    Eén call per dag volstaat; we filteren client-side op BTC/HBAR.
    """
    key = os.environ.get("COINMARKETCAL_API_KEY")
    if not key:
        raise EnvironmentError("COINMARKETCAL_API_KEY ontbreekt")
    r = requests.get("https://api.coinmarketcal.com/v2/events",
                     params={"sortBy": "date_asc", "limit": 100},
                     headers={"x-api-key": key, "Accept": "application/json", **UA}, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {_maskeer(r.text[:200])}")
    events = []
    for e in r.json().get("data", []):
        symbolen = {(c.get("symbol") or "").upper() for c in e.get("coins", [])}
        asset = "BTC" if "BTC" in symbolen else "HBAR" if "HBAR" in symbolen else None
        if asset is None:
            continue
        ts = None
        for veld in ("date", "dateEvent", "displayedDate"):
            raw = e.get(veld)
            if not raw:
                continue
            for fmt in (None, "%d %b %Y"):
                try:
                    ts = (datetime.fromisoformat(str(raw).replace("Z", "+00:00")) if fmt is None
                          else datetime.strptime(str(raw), fmt))
                    break
                except Exception:
                    continue
            if ts:
                break
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        impact = e.get("impact")
        niveau = ("high" if impact and float(impact) >= 7.5 else "medium") if impact is not None else "medium"
        events.append(("coinmarketcal", (e.get("title") or "")[:120], ts, None, niveau, asset, None, None, None))
    return [], events


BRONNEN = {
    "fred": laad_fred, "fmp": laad_fmp, "forexfactory": laad_forexfactory,
    "binance_fut": laad_binance_futures, "fng": laad_fng, "defillama": laad_defillama,
    "coingecko": laad_coingecko_global, "coinmarketcal": laad_coinmarketcal,
}


# ---------------------------------------------------------------- opslag
async def schrijf(rijen, events):
    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    async with db._pool.acquire() as conn:
        if rijen:
            await conn.executemany(
                """INSERT INTO macro_inputs (source, series, ts, value) VALUES ($1,$2,$3,$4)
                   ON CONFLICT (source, series, ts) DO UPDATE SET value = EXCLUDED.value, fetched_at = now()""",
                rijen)
        if events:
            await conn.executemany(
                """INSERT INTO event_calendar (source, name, ts, country, impact, asset, estimate, previous, actual)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                   ON CONFLICT (source, name, ts) DO UPDATE SET impact = EXCLUDED.impact, estimate = EXCLUDED.estimate,
                       previous = EXCLUDED.previous, actual = EXCLUDED.actual, fetched_at = now()""",
                events)


def main():
    gekozen = list(BRONNEN)
    if "--bron" in sys.argv:
        gekozen = sys.argv[sys.argv.index("--bron") + 1].split(",")
    alle_rijen, alle_events, verslag = [], [], []
    for naam in gekozen:
        try:
            rijen, events = BRONNEN[naam]()
            alle_rijen += rijen
            alle_events += events
            verslag.append(f"{naam}: {len(rijen)} waarden, {len(events)} events")
        except Exception as e:
            verslag.append(f"{naam}: MISLUKT -- {_maskeer(e)}")
    if "--dry" not in sys.argv:
        asyncio.run(schrijf(alle_rijen, alle_events))
    print(f"[macro-data] {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    for r in verslag:
        print("  " + r)
    print(f"  totaal: {len(alle_rijen)} waarden, {len(alle_events)} events {'(dry, niet opgeslagen)' if '--dry' in sys.argv else 'opgeslagen'}")


if __name__ == "__main__":
    main()
