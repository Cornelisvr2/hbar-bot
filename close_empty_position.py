from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    print("Positie 76712 sluiten (haalt eventuele resterende tokens terug)...")
    tx_hash = lp.close_position(76712)
    print(f"Tx-hash: {tx_hash}")

    print("\n=== Wallet-balans na sluiten ===")
    hbar = float(orchestrator.rpc_client.get_hbar_balance())
    usdc = orchestrator._get_swappable_usdc_balance()
    print(f"HBAR: {hbar:.4f}")
    print(f"USDC: {usdc:.4f}")

    await db.clear_active_lp_position()
    await db.close()

asyncio.run(main())
