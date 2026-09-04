from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    mint_fee_tinybar = lp._get_mint_fee_tinybar()
    print(f"mint_fee_tinybar: {mint_fee_tinybar}")
    mint_fee_hbar = mint_fee_tinybar / (10 ** 8)
    print(f"In HBAR: {mint_fee_hbar:.6f}")

    payable_value_wei = mint_fee_tinybar * (10 ** 10)
    payable_value_hbar = payable_value_wei / (10 ** 18)
    print(f"payable_value (msg.value voor de mint-transactie): {payable_value_hbar:.6f} HBAR")

    print("\n=== Ter vergelijking: huidige, werkelijke NATIVE HBAR-balans ===")
    native_hbar = float(orchestrator.rpc_client.get_hbar_balance())
    print(f"Native HBAR-balans NU: {native_hbar:.4f}")

    await db.close()

asyncio.run(main())
