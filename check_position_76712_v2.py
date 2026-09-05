from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import get_live_pool_price
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    print(f"lp.config.token0: {lp.config.token0} (decimals: {lp.config.token0_decimals})")
    print(f"lp.config.token1: {lp.config.token1} (decimals: {lp.config.token1_decimals})")

    echte_prijs = get_live_pool_price(
        orchestrator.rpc_client, lp.config.factory_address,
        lp.config.token0, lp.config.token1, lp.config.fee_tier,
        lp.config.token0_decimals, lp.config.token1_decimals,
    )
    print(f"\nCorrecte prijs, met de JUISTE decimalen (zoals de productie-code nu doet): {echte_prijs}")

    await db.close()

asyncio.run(main())
