from postgres_client import PostgresClient
import asyncio
import datetime

async def main():
    db = PostgresClient()
    await db.connect()

    print("=== Strategy-signals rond het openingsmoment (12:15-12:30) ===")
    rows = await db._pool.fetch(
        "SELECT created_at, direction, confidence, reasoning FROM strategy_signals "
        "WHERE created_at BETWEEN '2026-09-04 12:15:00+02' AND '2026-09-04 12:30:00+02' "
        "ORDER BY created_at ASC"
    )
    for r in rows:
        print(f"{r['created_at']} | {r['direction']} conf={r['confidence']:.2f} | {r['reasoning']}")

    print()
    print("=== Trades rond hetzelfde moment ===")
    rows2 = await db._pool.fetch(
        "SELECT created_at, direction, amount_in, engine FROM trades "
        "WHERE created_at BETWEEN '2026-09-04 12:15:00+02' AND '2026-09-04 12:30:00+02' "
        "ORDER BY created_at ASC"
    )
    for r in rows2:
        print(f"{r['created_at']} | {r['direction']} bedrag={r['amount_in']:.4f} engine={r['engine']}")

    await db.close()

asyncio.run(main())
