"""
backfill_markt.py -- 5-min-candles BTC/HBAR (Binance) naar candles_5m.

    docker compose run --rm -T hbar-bot python3 backfill_markt.py --dagen 730
Hervatbaar: begint bij de laatste opgeslagen candle per symbool.
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def main():
    dagen = int(sys.argv[sys.argv.index("--dagen") + 1]) if "--dagen" in sys.argv else 730
    from binance_klines_client import BinanceKlinesClient
    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    client = BinanceKlinesClient()
    einde = time.time()
    for symbol in ("BTC", "HBAR"):
        async with db._pool.acquire() as conn:
            laatste = await conn.fetchval("SELECT max(ts) FROM candles_5m WHERE symbol = $1", symbol)
        start = (laatste.timestamp() + 300) if laatste else (einde - dagen * 86400)
        print(f"[markt] {symbol}: ophalen vanaf {datetime.fromtimestamp(start, tz=timezone.utc):%Y-%m-%d %H:%M} UTC ...", flush=True)
        totaal = 0
        # in stukken van 30 dagen, zodat een afgebroken run niet alles kwijt is
        cur = start
        while cur < einde:
            tot = min(cur + 30 * 86400, einde)
            kl = client.fetch_range(symbol, cur, tot, interval="5m", pause_seconds=0.25)
            rijen = [(symbol, datetime.fromtimestamp(k.open_time, tz=timezone.utc), k.open, k.high, k.low, k.close, k.volume) for k in kl]
            if rijen:
                async with db._pool.acquire() as conn:
                    await conn.executemany(
                        "INSERT INTO candles_5m (symbol, ts, open, high, low, close, volume) VALUES ($1,$2,$3,$4,$5,$6,$7) "
                        "ON CONFLICT (symbol, ts) DO NOTHING", rijen)
            totaal += len(rijen)
            print(f"[markt] {symbol}: {datetime.fromtimestamp(cur, tz=timezone.utc):%Y-%m-%d} .. +{len(rijen)} (totaal {totaal})", flush=True)
            cur = tot
    print("[markt] klaar.")


if __name__ == "__main__":
    asyncio.run(main())
