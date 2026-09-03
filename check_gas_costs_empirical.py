from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    rpc = orchestrator.rpc_client

    trades = await db.get_recent_trades(limit=30)
    print(f"Aantal recente trades: {len(trades)}")

    gas_kosten_hbar = []
    for t in trades:
        if not t["tx_hash"]:
            continue
        try:
            receipt = rpc.w3.eth.get_transaction_receipt(t["tx_hash"])
            kosten_wei = receipt["gasUsed"] * receipt["effectiveGasPrice"]
            kosten_hbar = kosten_wei / (10 ** 18)
            gas_kosten_hbar.append(kosten_hbar)
        except Exception:
            continue

    if gas_kosten_hbar:
        gemiddeld = sum(gas_kosten_hbar) / len(gas_kosten_hbar)
        print(f"Aantal met bruikbare gaskosten: {len(gas_kosten_hbar)}")
        print(f"Gemiddelde gaskosten per SWAP-operatie: {gemiddeld:.4f} HBAR")
        print(f"Min: {min(gas_kosten_hbar):.4f}, Max: {max(gas_kosten_hbar):.4f}")
        print(f"\nGeschatte volledige heen-en-terug-cyclus (sluiten+swap+swap+openen, 4 operaties): "
              f"{gemiddeld*4:.4f} HBAR")
    else:
        print("Geen bruikbare gaskosten gevonden.")

    await db.close()

asyncio.run(main())
