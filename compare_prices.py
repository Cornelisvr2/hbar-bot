from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import get_live_pool_price
from config import resolve_testnet_v2_addresses
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    gecko_prijs = orchestrator.geckoterminal.get_pool_snapshot().price_usd
    print(f'GeckoTerminal price_usd: {gecko_prijs}')

    v2_addr = resolve_testnet_v2_addresses()
    pool_prijs = get_live_pool_price(
        orchestrator.rpc_client, v2_addr.factory,
        lp.config.token0, lp.config.token1,
        lp.config.fee_tier, lp.config.token0_decimals, lp.config.token1_decimals,
    )
    print(f'Pool eigen prijs (rechtstreeks via slot0): {pool_prijs}')
    print()
    print(f'Verhouding: {pool_prijs / gecko_prijs:.2f}x')

    await db.close()

asyncio.run(main())
