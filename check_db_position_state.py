from postgres_client import PostgresClient
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    positie = await db.get_active_lp_position()
    print(f"Database active_lp_position: {positie}")
    await db.close()

asyncio.run(main())
