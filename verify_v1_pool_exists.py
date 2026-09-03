"""
verify_v1_pool_exists.py

Zelfde controle als verify_v2_pool_exists.py, maar dan voor de V1
(klassieke AMM) Factory -- via getPair() i.p.v. getPool() (geen
fee-tier-parameter nodig, V1 heeft maar 1 pool per paar).
"""

import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, resolve_testnet_addresses


V1_FACTORY_ABI = [
    {
        "name": "getPair",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "tokenA", "type": "address"},
            {"name": "tokenB", "type": "address"},
        ],
        "outputs": [{"name": "pair", "type": "address"}],
    },
]

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def main():
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    if not private_key:
        print("Geen HEDERA_BOT_PRIVATE_KEY gezet.")
        return

    settings = NETWORK_SETTINGS["testnet"]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, private_key)

    base = resolve_testnet_addresses()
    v1_factory_address = base.factory

    print(f"V1 Factory-adres: {v1_factory_address}")
    print(f"WHBAR-adres:      {base.whbar_token}")
    print(f"USDC-adres:       {base.usdc}")
    print()

    factory = client.w3.eth.contract(address=v1_factory_address, abi=V1_FACTORY_ABI)

    try:
        pair_address = factory.functions.getPair(base.whbar_token, base.usdc).call()
        exists = pair_address.lower() != ZERO_ADDRESS.lower()
        if exists:
            print(f"V1-POOL BESTAAT: {pair_address}")
            print("\nDe V1-route is dus bruikbaar op testnet -- overweeg "
                  "execute_hbar_swap_standalone.py's --engine v1 te gebruiken "
                  "i.p.v. v2, totdat er een V2-testnet-pool beschikbaar is.")
        else:
            print("Geen V1-pool (nul-adres) -- ook de klassieke AMM-route "
                  "heeft geen testnet-liquiditeit voor dit paar.")
    except Exception as e:
        print(f"FOUT bij het opvragen: {str(e)[:200]}")


if __name__ == "__main__":
    main()
