from postgres_client import PostgresClient
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    rows = await db._pool.fetch(
        "SELECT created_at, asset, headline, sentiment_score, volatility_sigma, confidence, is_idiosyncratic "
        "FROM sentiment_log "
        "WHERE created_at > NOW() - INTERVAL '24 hours' ORDER BY created_at DESC LIMIT 40"
    )
    print(f"Aantal sentiment-analyses in de laatste 24 uur: {len(rows)}")
    for r in rows:
        idio = "IDIO" if r["is_idiosyncratic"] else "    "
        print(f"{r['created_at']} | {r['asset']:4s} | score={r['sentiment_score']:+.3f} sigma={r['volatility_sigma']:.2f} "
              f"conf={r['confidence']:.2f} {idio} | {r['headline'][:70]}")
    await db.close()

asyncio.run(main())
