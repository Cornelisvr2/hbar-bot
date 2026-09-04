from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import get_live_pool_price, tick_to_price
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    from bot_data import V2_POSITION_MANAGER_ABI
    position_manager = orchestrator.rpc_client.w3.eth.contract(
        address=lp.config.position_manager_address, abi=V2_POSITION_MANAGER_ABI
    )
    positie = position_manager.functions.positions(76712).call()
    print(f"Positie 76712 on-chain: tick_lower={positie[5]}, tick_upper={positie[6]}, liquidity={positie[7]}")

    print(f"\nlp.config.token0: {lp.config.token0}")
    print(f"lp.config.token1: {lp.config.token1}")

    echte_prijs = get_live_pool_price(
        orchestrator.rpc_client, lp.config.factory_address,
        lp.config.token0, lp.config.token1, lp.config.fee_tier,
        8, orchestrator._usdc_decimals,
    )
    print(f"\nWerkelijke, correcte prijs NU (met dezelfde config-parameters): {echte_prijs}")

    await db.close()

asyncio.run(main())
