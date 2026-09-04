from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

TOKEN_ID = 352  # bevestigd via de mirror node: bestaat, gemint om 12:21

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    from bot_data import V2_POSITION_MANAGER_ABI
    position_manager = orchestrator.rpc_client.w3.eth.contract(
        address=lp.config.position_manager_address, abi=V2_POSITION_MANAGER_ABI
    )
    on_chain = position_manager.functions.positions(TOKEN_ID).call()
    tick_lower, tick_upper, liquidity = on_chain[3], on_chain[4], on_chain[5]
    print(f"On-chain bevestigd: token_id={TOKEN_ID}, tick_lower={tick_lower}, "
          f"tick_upper={tick_upper}, liquidity={liquidity}")

    if liquidity == 0:
        print("WAARSCHUWING: liquidity=0 -- deze positie is leeg, mogelijk toch iets anders misgegaan. "
              "NIET automatisch herstellen, eerst handmatig controleren.")
        await db.close()
        return

    # In het geheugen van de LEVENDE bot bijwerken (geldt tot de volgende herstart,
    # daarna pakt de opstart-herstel-logica het uit de database).
    lp.state.token_id = TOKEN_ID
    lp.state.tick_lower = tick_lower
    lp.state.tick_upper = tick_upper
    lp.state.is_open = True

    await db.save_active_lp_position(TOKEN_ID, tick_lower, tick_upper)
    print("Opgeslagen in de database.")

    await db.close()

asyncio.run(main())
