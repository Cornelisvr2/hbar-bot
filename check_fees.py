from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from bot_data import V2_POSITION_MANAGER_ABI
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager
    client = orchestrator.rpc_client

    positie = await db.get_active_lp_position()
    print(f"Actieve positie (database): {positie}")

    if positie:
        position_manager = client.w3.eth.contract(
            address=lp.config.position_manager_address, abi=V2_POSITION_MANAGER_ABI
        )
        on_chain = position_manager.functions.positions(positie["token_id"]).call()
        print(f"On-chain positie-data: {on_chain}")
        print(f"  liquidity: {on_chain[5]}")
        print(f"  tokensOwed0 (HBAR, al-geregistreerd): {on_chain[8]}")
        print(f"  tokensOwed1 (SAUCE, al-geregistreerd): {on_chain[9]}")

        UINT128_MAX = (2 ** 128) - 1
        fee0, fee1 = position_manager.functions.collect(
            (positie["token_id"], client.address, UINT128_MAX, UINT128_MAX)
        ).call({"from": client.address})
        print(f"\nGesimuleerde collect()-uitkomst:")
        print(f"  amount0 (HBAR-raw): {fee0} ({fee0/(10**8):.6f} HBAR)")
        print(f"  amount1 (SAUCE-raw): {fee1} ({fee1/(10**6):.6f} SAUCE)")

    await db.close()

asyncio.run(main())
