"""
verify_v2_pool_exists.py

Vraagt de V2 Factory rechtstreeks (getPool) of er uberhaupt een pool
bestaat voor WHBAR/USDC op testnet, voor elke fee-tier. Dit omzeilt de
QuoterV2-logica volledig -- als de Factory een nul-adres teruggeeft,
bestaat de pool simpelweg niet (los van decimalen of andere logica in
swap_executor_v2.py).
"""

import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses


FACTORY_ABI = [
    {
        "name": "getPool",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "tokenA", "type": "address"},
            {"name": "tokenB", "type": "address"},
            {"name": "fee", "type": "uint24"},
        ],
        "outputs": [{"name": "pool", "type": "address"}],
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
    v2 = resolve_testnet_v2_addresses()

    print(f"Factory-adres: {v2.factory}")
    print(f"WHBAR-adres:   {base.whbar_token}")
    print(f"USDC-adres:    {base.usdc}")
    print()

    factory = client.w3.eth.contract(address=v2.factory, abi=FACTORY_ABI)

    fee_tiers = [500, 1500, 3000, 10000]  # gecorrigeerd 23 aug 2026 o.b.v. officiele docs
    any_pool_found = False

    for fee_tier in fee_tiers:
        try:
            pool_address = factory.functions.getPool(
                base.whbar_token, base.usdc, fee_tier
            ).call()
            exists = pool_address.lower() != ZERO_ADDRESS.lower()
            status = f"POOL BESTAAT: {pool_address}" if exists else "geen pool (nul-adres)"
            print(f"Fee-tier {fee_tier}: {status}")
            if exists:
                any_pool_found = True
        except Exception as e:
            print(f"Fee-tier {fee_tier}: FOUT bij het opvragen -- {str(e)[:150]}")

    print()
    if any_pool_found:
        print("Er bestaat minstens 1 pool -- het probleem zit dus NIET in "
              "'geen pool', maar mogelijk in de quote/decimalen-logica zelf, "
              "of de pool heeft geen liquiditeit.")
    else:
        print("GEEN ENKELE pool bestaat voor dit paar op testnet, bij geen "
              "van de vier gangbare fee-tiers. Dit verklaart de eerdere "
              "reverts volledig, los van decimalen. Mogelijk moet er eerst "
              "een testnet-pool aangemaakt/geseeded worden, of de "
              "WHBAR/USDC-adressen kloppen niet.")


if __name__ == "__main__":
    main()
