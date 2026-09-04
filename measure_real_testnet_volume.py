from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from config import NETWORK_SETTINGS
import asyncio
import requests
import os
from web3 import Web3

# Standaard Uniswap V3 Swap-event-signatuur (SaucerSwap V2 is hierop
# gebaseerd) -- event Swap(address indexed sender, address indexed
# recipient, int256 amount0, int256 amount1, uint160 sqrtPriceX96,
# uint128 liquidity, int24 tick)
SWAP_EVENT_ABI = {
    "anonymous": False,
    "inputs": [
        {"indexed": True, "name": "sender", "type": "address"},
        {"indexed": True, "name": "recipient", "type": "address"},
        {"indexed": False, "name": "amount0", "type": "int256"},
        {"indexed": False, "name": "amount1", "type": "int256"},
        {"indexed": False, "name": "sqrtPriceX96", "type": "uint160"},
        {"indexed": False, "name": "liquidity", "type": "uint128"},
        {"indexed": False, "name": "tick", "type": "int24"},
    ],
    "name": "Swap",
    "type": "event",
}

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)

    ONS_TESTNET_POOL_CONTRACT_ID = "0.0.2661057"  # bevestigd, uit eerder werk vandaag
    mirror_node_url = NETWORK_SETTINGS[os.environ.get("HEDERA_NETWORK", "testnet")]["mirror_node_url"]

    print(f"Onze testnet-pool: {ONS_TESTNET_POOL_CONTRACT_ID}")
    print(f"Mirror node: {mirror_node_url}")

    w3 = Web3()
    swap_topic = w3.keccak(text="Swap(address,address,int256,int256,uint160,uint128,int24)").hex()
    print(f"Swap-event-topic: {swap_topic}")

    url = (
        f"{mirror_node_url}/api/v1/contracts/{ONS_TESTNET_POOL_CONTRACT_ID}/results/logs"
        f"?order=desc&limit=100"
    )
    print(f"\nAanroep: {url}")
    resp = requests.get(url, timeout=15)
    print(f"Statuscode: {resp.status_code}")
    data = resp.json()
    logs = data.get("logs", [])
    print(f"Aantal recente logs (ongefilterd): {len(logs)}")

    swap_logs = [l for l in logs if l.get("topics") and l["topics"][0] == swap_topic]
    print(f"Waarvan Swap-events: {len(swap_logs)}")

    if swap_logs:
        print("\n=== Meest recente Swap-events ===")
        for log in swap_logs[:5]:
            print(f"  timestamp={log.get('timestamp')}, data={log.get('data')[:80]}...")
    else:
        print("\nGeen Swap-events gevonden in de meest recente 100 logs van deze pool.")

    await db.close()

asyncio.run(main())
