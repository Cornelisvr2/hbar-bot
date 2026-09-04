from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    whbar_balance_raw = lp.whbar_token.functions.balanceOf(orchestrator.rpc_client.address).call()
    whbar_balance = whbar_balance_raw / (10 ** 8)
    print(f"Vastzittende WHBAR: {whbar_balance:.8f}")

    if whbar_balance_raw == 0:
        print("Niets te herstellen.")
        await db.close()
        return

    approve_fn = lp.whbar_token.functions.approve(lp.config.whbar_helper_address, whbar_balance_raw)
    approve_tx = orchestrator.rpc_client.build_and_send_transaction(approve_fn)
    orchestrator.rpc_client.wait_for_receipt(approve_tx)

    unwrap_fn = lp.whbar_helper.functions.unwrapWhbar(whbar_balance_raw)
    unwrap_tx = orchestrator.rpc_client.build_and_send_transaction(unwrap_fn)
    receipt = orchestrator.rpc_client.wait_for_receipt(unwrap_tx)
    print(f"Unwrap-status: {receipt['status']}")
    print(f"Hersteld: {whbar_balance:.8f} HBAR")

    await db.close()

asyncio.run(main())
