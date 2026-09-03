from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

# Bekende, echte open/sluit-transacties van vandaag
BEKENDE_TX_HASHES = {
    "open (positie 351)": "0x710cb09b6c155072638d2691182e443914828a85fe8f6f8ab8073d631cfbe4aa",
}

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    rpc = orchestrator.rpc_client

    for label, tx_hash in BEKENDE_TX_HASHES.items():
        try:
            receipt = rpc.w3.eth.get_transaction_receipt(tx_hash)
            kosten_wei = receipt["gasUsed"] * receipt["effectiveGasPrice"]
            kosten_hbar = kosten_wei / (10 ** 18)
            print(f"{label}: gasUsed={receipt['gasUsed']}, kosten={kosten_hbar:.4f} HBAR")
        except Exception as e:
            print(f"{label}: kon niet ophalen -- {e}")

    await db.close()

asyncio.run(main())
