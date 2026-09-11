"""
backfill_kalender.py -- historische macro-kalender uit FRED, 2 jaar terug.

De live event_calendar (Forex Factory) reikt maar ~1 week vooruit, dus er is
geen historie om de kalender-anticipatie op te backtesten. FRED heeft wel
alle historische waarden van de kern-indicatoren MET hun publicatiedatum
(release dates). Dit script zet elke publicatie als event in event_calendar:
naam, publicatietijd, de waarde (actual) en de vorige waarde (previous).

Wat FRED NIET geeft is de consensus-VERWACHTING (estimate) -- die is
historisch alleen bij betaalde bronnen. Voor de backtest is dat geen ramp:
de 'vlak'-variant (klap ontwijken) heeft geen verwachting nodig, en voor de
'surprise'-variant benaderen we de verrassing met (actual - previous):
een cijfer dat hoger is dan de vorige maand is een ruwe proxy voor "hoger
dan normaal". Niet perfect, wel genoeg om de strategie te toetsen.

Indicatoren (release ~08:30 ET = 12:30/13:30 UTC afh. van zomertijd; we
gebruiken de FRED-release-timestamp waar beschikbaar, anders 13:30 UTC):
  CPIAUCSL  CPI                 PAYEMS    Non-farm payrolls
  CPILFESL  Core CPI            UNRATE    Werkloosheid
  PPIFIS    PPI                 FEDFUNDS  Fed funds rate (FOMC-uitkomst)
  PCEPI     PCE

    docker compose run --rm -T hbar-bot python3 backfill_kalender.py --dagen 730
"""
import asyncio
import os
import sys
from datetime import datetime, time, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UA = {"User-Agent": "hbar-bot-kalender-backfill/1.0"}
# series_id -> (mooie naam, impact, 'hoog is slecht voor risico'?)
INDICATOREN = {
    "CPIAUCSL": ("CPI m/m", "high"),
    "CPILFESL": ("Core CPI m/m", "high"),
    "PPIFIS":   ("PPI m/m", "high"),
    "PCEPI":    ("PCE price index", "high"),
    "PAYEMS":   ("Non-farm payrolls", "high"),
    "UNRATE":   ("Unemployment rate", "high"),
    "FEDFUNDS": ("Fed funds rate (FOMC)", "high"),
}
DEFAULT_RELEASE_UTC = time(13, 30)  # ~08:30 ET


import re as _re
def _mask(t):
    return _re.sub(r"(api_key)=[^&\s]+", r"\1=***", str(t))

def _get(url, params):
    r = requests.get(url, params=params, headers=UA, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {_mask(r.url)}")
    return r.json()


def haal_indicator(sid, key, start):
    """Genereer (naam, ts, actual, previous) per publicatie van deze indicator."""
    naam, _impact = INDICATOREN[sid]
    # observaties met hun WERKELIJKE publicatiemoment (realtime_start = wanneer de waarde
    # voor het eerst gepubliceerd werd). output_type=4 geeft de eerste release per periode.
    # realtime_start/_end over de hele periode -> FRED geeft elke observatie
    # met de datum waarop de waarde voor het eerst beschikbaar was (de
    # release). De observatie-datum (o["date"]) is de PERIODE (bv. de maand),
    # realtime_start is de PUBLICATIEDAG -- die willen we als event-tijd.
    vandaag = datetime.now(timezone.utc).date().isoformat()
    data = _get("https://api.stlouisfed.org/fred/series/observations", {
        "series_id": sid, "api_key": key, "file_type": "json",
        "observation_start": start,
        "realtime_start": start, "realtime_end": vandaag,
    })
    # per periode-datum de VROEGSTE realtime_start = eerste release
    eerste = {}
    for o in data.get("observations", []):
        val = o.get("value")
        if val in (None, ".", ""):
            continue
        d = o.get("date"); rt = o.get("realtime_start")
        if d is None or rt is None:
            continue
        if d not in eerste or rt < eerste[d][0]:
            try:
                eerste[d] = (rt, float(val))
            except ValueError:
                continue
    vorige = None
    for d in sorted(eerste):
        rt, actual = eerste[d]
        try:
            dag = datetime.fromisoformat(rt)
        except ValueError:
            continue
        ts = datetime.combine(dag.date(), DEFAULT_RELEASE_UTC, tzinfo=timezone.utc)
        yield naam, ts, actual, vorige
        vorige = actual


async def main():
    a = sys.argv
    dagen = int(a[a.index("--dagen") + 1]) if "--dagen" in a else 730
    key = os.environ.get("FRED_API_KEY")
    if not key:
        print("FRED_API_KEY ontbreekt."); return
    start = (datetime.now(timezone.utc) - timedelta(days=dagen)).date().isoformat()

    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()

    rijen, per_ind = [], {}
    for sid in INDICATOREN:
        try:
            events = list(haal_indicator(sid, key, start))
        except Exception as e:
            print(f"  {sid}: MISLUKT -- {e}")
            continue
        per_ind[sid] = len(events)
        naam, impact = INDICATOREN[sid]
        for nm, ts, actual, previous in events:
            # estimate blijft NULL (FRED heeft geen consensus); previous als proxy
            rijen.append(("fred_release", nm, ts, "US", impact, "markt_breed", None, previous, actual))

    if rijen:
        async with db._pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO event_calendar (source, name, ts, country, impact, asset, estimate, previous, actual)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                   ON CONFLICT (source, name, ts) DO UPDATE SET actual=EXCLUDED.actual,
                       previous=EXCLUDED.previous, fetched_at=now()""",
                rijen)
    print(f"[kalender-backfill] {len(rijen)} events geschreven:")
    for sid, n in per_ind.items():
        print(f"  {INDICATOREN[sid][0]:24s} {n}")


if __name__ == "__main__":
    asyncio.run(main())
