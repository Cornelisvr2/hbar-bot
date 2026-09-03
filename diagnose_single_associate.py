"""
diagnose_single_associate.py

Test de ENKELVOUDIGE associateToken() (geen array) voor precies 1 token
(WHBAR), om te isoleren of het probleem specifiek bij de array-versie
(associateTokens, meervoud) ligt, of dieper zit.
"""

import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from hedera_address_utils import hedera_id_to_evm_address
from config import NETWORK_SETTINGS


HTS_PRECOMPILE_ADDRESS = "0x0000000000000000000000000000000000000167"

HTS_PRECOMPILE_ABI_SINGLE = [
    {
        "name": "associateToken",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "token", "type": "address"},
        ],
        "outputs": [{"name": "responseCode", "type": "int64"}],
    },
]

WHBAR_TESTNET_ID = "0.0.15058"


def main():
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    settings = NETWORK_SETTINGS["testnet"]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, private_key)

    whbar_address = hedera_id_to_evm_address(WHBAR_TESTNET_ID)

    hts = client.w3.eth.contract(address=HTS_PRECOMPILE_ADDRESS, abi=HTS_PRECOMPILE_ABI_SINGLE)
    associate_fn = hts.functions.associateToken(client.address, whbar_address)

    print(f"Account: {client.address}")
    print(f"Token (WHBAR): {whbar_address}")
    print("\nTransactie versturen (enkelvoudige associateToken, 2.000.000 gas)...")

    tx_hash = client.build_and_send_transaction(associate_fn, gas_limit=5_000_000)
    receipt = client.wait_for_receipt(tx_hash)

    print(f"Status: {receipt['status']}")
    print(f"Tx hash: {tx_hash}")


if __name__ == "__main__":
    main()
