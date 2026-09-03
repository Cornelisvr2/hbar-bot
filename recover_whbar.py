from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    hersteld = orchestrator.lp_manager.check_and_recover_stuck_whbar()
    print(f"Hersteld: {hersteld} HBAR")
    await db.close()

asyncio.run(main())
