from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    rpc = orchestrator.rpc_client

    print("=== Huidige, daadwerkelijke netwerk-gasprijs ===")
    huidige_gas_prijs_wei = rpc.w3.eth.gas_price
    max_fee_per_gas_wei = int(huidige_gas_prijs_wei * 1.2)  # zelfde 20%-marge als build_and_send_transaction
    print(f"Actuele gasprijs: {huidige_gas_prijs_wei} wei")
    print(f"max_fee_per_gas (met 20% marge): {max_fee_per_gas_wei} wei")

    print("\n=== Wat zou de mint-transactie (gas_limit_override=1.200.000) MAXIMAAL kunnen kosten? ===")
    gas_limit_mint = 1_200_000
    max_kosten_wei = gas_limit_mint * max_fee_per_gas_wei
    max_kosten_hbar = max_kosten_wei / (10 ** 18)
    print(f"Maximale, gereserveerde kosten: {max_kosten_wei} wei = {max_kosten_hbar:.4f} HBAR")

    print("\n=== Vergelijking met de reserve ===")
    print(f"Bij een reserve van 50 HBAR: {'VOLDOENDE' if max_kosten_hbar <= 50 else 'TE WEINIG'} "
          f"(verschil: {50 - max_kosten_hbar:+.4f} HBAR)")
    print(f"Bij een reserve van 100 HBAR: {'VOLDOENDE' if max_kosten_hbar <= 100 else 'TE WEINIG'} "
          f"(verschil: {100 - max_kosten_hbar:+.4f} HBAR)")

    print("\n=== Ter referentie: de wrap-stap zelf gebruikt GEEN vaste gas_limit (auto-schatting) ===")
    print("Als de auto-schatting voor wrapWhbar() ook maar in de buurt komt van een vergelijkbaar")
    print("gas-verbruik, komt DAAR nog een vergelijkbaar bedrag bovenop, VOORDAT de mint-stap "
          "uberhaupt aan de beurt is.")

    await db.close()

asyncio.run(main())
