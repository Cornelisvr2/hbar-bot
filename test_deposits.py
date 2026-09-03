from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from bot_data import get_total_deposits_hbar
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    adres = orchestrator.rpc_client.address
    print(f"Ons adres: {adres}")

    totaal = get_total_deposits_hbar(adres)
    print(f"Totaal berekende, externe stortingen: {totaal:.4f} HBAR")

    await db.close()

asyncio.run(main())
