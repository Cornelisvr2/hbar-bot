from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

TX_HASH = "0xca0563c0fed55b742a203a46f61862dc6024f998d3ae7d486e60816066df7834"

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    token_id = lp._extract_token_id_from_mint(TX_HASH)
    print(f'Token ID gevonden: {token_id}')

    positie = lp.position_manager.functions.positions(token_id).call()
    tick_lower, tick_upper, liquidity = positie[3], positie[4], positie[5]
    print(f'Verificatie: tick_lower={tick_lower}, tick_upper={tick_upper}, liquidity={liquidity}')

    if liquidity > 0:
        await db.save_active_lp_position(token_id, tick_lower, tick_upper)
        print('Opgeslagen in de database.')
    else:
        print('LET OP: liquiditeit is 0 -- iets klopt niet, niet opgeslagen.')

    await db.close()

asyncio.run(main())
