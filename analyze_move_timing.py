from binance_klines_client import BinanceKlinesClient
from postgres_client import PostgresClient
import asyncio
import datetime

async def main():
    client = BinanceKlinesClient()
    nu = datetime.datetime.now(datetime.timezone.utc)
    start = nu - datetime.timedelta(hours=24)

    print("=== BTC, 15-minuten-candles, laatste 24 uur ===")
    klines = client.get_klines("BTC", interval="15m", start_time=start.timestamp(), limit=96)
    vorige_close = None
    for k in klines:
        tijd = datetime.datetime.fromtimestamp(k.open_time, tz=datetime.timezone.utc)
        verandering = ""
        if vorige_close:
            pct = (k.close - vorige_close) / vorige_close * 100
            merk = "  <<<<" if abs(pct) >= 0.5 else ""
            verandering = f"  {pct:+.2f}%{merk}"
        print(f"{tijd.strftime('%H:%M')} UTC | close={k.close:.2f}{verandering}")
        vorige_close = k.close

    print("\n=== Nieuws-tijdlijn (sentiment_log), laatste 24 uur, chronologisch ===")
    db = PostgresClient()
    await db.connect()
    rows = await db._pool.fetch(
        "SELECT created_at, asset, headline, sentiment_score FROM sentiment_log "
        "WHERE created_at > NOW() - INTERVAL '24 hours' ORDER BY created_at ASC"
    )
    for r in rows:
        print(f"{r['created_at'].strftime('%H:%M')} UTC | {r['asset']:4s} score={r['sentiment_score']:+.3f} | {r['headline'][:65]}")
    await db.close()

asyncio.run(main())
