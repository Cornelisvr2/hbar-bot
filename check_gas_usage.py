from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

TX_HASH = "0xca0563c0fed55b742a203a46f61862dc6024f998d3ae7d486e60816066df7834"

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)

    receipt = orchestrator.rpc_client.w3.eth.get_transaction_receipt(TX_HASH)
    gas_used = receipt['gasUsed']
    print(f"Daadwerkelijk gasverbruik (positie 349 openen): {gas_used}")
    print(f"Ingestelde limiet: 1.200.000")
    print(f"Marge: {(1_200_000 - gas_used) / gas_used * 100:.1f}%")

    await db.close()

asyncio.run(main())
