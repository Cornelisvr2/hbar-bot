from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    from lp_manager import POOL_SLOT0_ABI_MINIMAL
    TESTNET_POOL_EVM = "0x37814eDc1ae88cf27c0C346648721FB04e7E0AE7"
    pool_contract = orchestrator.rpc_client.w3.eth.contract(
        address=TESTNET_POOL_EVM,
        abi=POOL_SLOT0_ABI_MINIMAL + [{
            "inputs": [], "name": "liquidity",
            "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
            "stateMutability": "view", "type": "function"
        }]
    )
    pool_liquidity = pool_contract.functions.liquidity().call()
    print(f"Pool's actieve liquidity (in-range, ruwe eenheid L): {pool_liquidity}")

    onze_swap_grootte_sauce = 25677.9907
    print(f"\nOnze recente swap: {onze_swap_grootte_sauce:.2f} SAUCE")
    print("Eerder vandaag gemeten: totaal 24u-pool-volume was slechts 2893 HBAR-equivalent")
    print(f"(bijna volledig onze eigen activiteit). Onze SINGLE swap van zonet is dus zelf al")
    print(f"een aanzienlijk deel van wat er de HELE voorgaande 24 uur aan volume was --")
    print(f"dat verklaart een prijsimpact van enkele procenten in \u00e9\u00e9n transactie.")

    await db.close()

asyncio.run(main())
