"""
verify_whbar_sauce_pool.py

Sanity-check: bestaat er een WHBAR/SAUCE-pool op testnet (V1 en V2)?
SAUCE is gekoppeld aan actieve farming/staking-systemen (Masterchef,
Mothership) volgens de officiele contract-tabel, wat sterk suggereert
dat er WEL liquiditeit is -- in tegenstelling tot het losse USDC-
testtoken dat geen pool bleek te hebben.
"""

import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from hedera_address_utils import hedera_id_to_evm_address
from config import NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses


V1_FACTORY_ABI = [
    {
        "name": "getPair", "type": "function", "stateMutability": "view",
        "inputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"}],
        "outputs": [{"name": "pair", "type": "address"}],
    },
]

V2_FACTORY_ABI = [
    {
        "name": "getPool", "type": "function", "stateMutability": "view",
        "inputs": [
            {"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"},
            {"name": "fee", "type": "uint24"},
        ],
        "outputs": [{"name": "pool", "type": "address"}],
    },
]

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
SAUCE_TESTNET_ID = "0.0.1183558"


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
    sauce_address = hedera_id_to_evm_address(SAUCE_TESTNET_ID)

    print(f"WHBAR-adres: {base.whbar_token}")
    print(f"SAUCE-adres: {sauce_address}")
    print()

    v1_factory = client.w3.eth.contract(address=base.factory, abi=V1_FACTORY_ABI)
    try:
        pair = v1_factory.functions.getPair(base.whbar_token, sauce_address).call()
        exists_v1 = pair.lower() != ZERO_ADDRESS.lower()
        print(f"V1 WHBAR/SAUCE-pool: {'BESTAAT -- ' + pair if exists_v1 else 'geen (nul-adres)'}")
    except Exception as e:
        print(f"V1-check FOUT: {str(e)[:150]}")

    v2_factory = client.w3.eth.contract(address=v2.factory, abi=V2_FACTORY_ABI)
    for fee_tier in (500, 1500, 3000, 10000):  # gecorrigeerd 23 aug 2026 o.b.v. officiele docs
        try:
            pool = v2_factory.functions.getPool(base.whbar_token, sauce_address, fee_tier).call()
            exists_v2 = pool.lower() != ZERO_ADDRESS.lower()
            print(f"V2 WHBAR/SAUCE-pool (fee={fee_tier}): "
                  f"{'BESTAAT -- ' + pool if exists_v2 else 'geen (nul-adres)'}")
        except Exception as e:
            print(f"V2-check fee={fee_tier} FOUT: {str(e)[:150]}")


if __name__ == "__main__":
    main()
