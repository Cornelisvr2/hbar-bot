from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)

    sauce_balans = orchestrator._get_swappable_usdc_balance()
    print(f"Huidige SAUCE-balans: {sauce_balans:.4f}")

    if sauce_balans <= 0:
        print("Niets te swappen.")
        await db.close()
        return

    gelukt = await orchestrator._run_swap_and_log("USDC_TO_HBAR", sauce_balans, None)
    print(f"Swap gelukt: {gelukt}")

    await db.close()

asyncio.run(main())
