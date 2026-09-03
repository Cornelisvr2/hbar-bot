from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import POOL_SLOT0_ABI_MINIMAL, V2_FACTORY_ABI_MINIMAL
from config import resolve_testnet_v2_addresses
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    v2 = resolve_testnet_v2_addresses()
    factory = orchestrator.rpc_client.w3.eth.contract(address=v2.factory, abi=V2_FACTORY_ABI_MINIMAL)
    pool_address = factory.functions.getPool(lp.config.token0, lp.config.token1, lp.config.fee_tier).call()
    pool = orchestrator.rpc_client.w3.eth.contract(address=pool_address, abi=POOL_SLOT0_ABI_MINIMAL)
    slot0 = pool.functions.slot0().call()

    print(f'slot0(): {slot0}')
    print(f'observationCardinality: {slot0[4]}')
    print(f'observationCardinalityNext: {slot0[5]}')
    print()
    if slot0[4] <= 1:
        print('LET OP: cardinaliteit is 1 (of minder) -- GEEN historische data opgeslagen, TWAP is NIET direct mogelijk.')
    else:
        print(f'TWAP zou mogelijk moeten zijn -- {slot0[4]} historische waarnemingen beschikbaar.')

    await db.close()

asyncio.run(main())
