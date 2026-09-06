import asyncio
from postgres_client import PostgresClient
from bot_data import fetch_dashboard_data

async def main():
    db = PostgresClient()
    await db.connect()
    data = await fetch_dashboard_data(db)
    import json
    print(json.dumps(data, indent=2, default=str))
    await db.close()

asyncio.run(main())
