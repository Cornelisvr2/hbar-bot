"""
diagnose_associate_error.py

Zelfde als associate_required_tokens.py, maar vangt de HTTPError expliciet
op en print de ruwe responstekst van de RPC-relay -- dat verbergt
requests.raise_for_status() normaal, en juist die tekst vertelt ons wat
er precies mis is (te hoge gas, verkeerd adres, malformed payload, etc.).
"""

import os
import requests

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from hedera_address_utils import hedera_id_to_evm_address
from config import NETWORK_SETTINGS


HTS_PRECOMPILE_ADDRESS = "0x0000000000000000000000000000000000000167"

HTS_PRECOMPILE_ABI = [
    {
        "name": "associateTokens",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "tokens", "type": "address[]"},
        ],
        "outputs": [{"name": "responseCode", "type": "int64"}],
    },
]

REQUIRED_TOKENS_TESTNET = {
    "SAUCE": "0.0.1183558",
    "LP-NFT (SaucerSwapV2)": "0.0.1310436",
}


def main():
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    settings = NETWORK_SETTINGS["testnet"]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, private_key)

    token_addresses = [hedera_id_to_evm_address(tid) for tid in REQUIRED_TOKENS_TESTNET.values()]
    hts = client.w3.eth.contract(address=HTS_PRECOMPILE_ADDRESS, abi=HTS_PRECOMPILE_ABI)
    associate_fn = hts.functions.associateTokens(client.address, token_addresses)

    try:
        estimated_gas = associate_fn.estimate_gas({"from": client.address})
        print(f"Geschatte gas (voor de 50% marge): {estimated_gas}")
        print(f"Uiteindelijke gas_limit die verstuurd wordt: {int(estimated_gas * 1.5)}")

        tx_hash = client.build_and_send_transaction(associate_fn)
        print(f"Onverwacht gelukt: {tx_hash}")
    except requests.exceptions.HTTPError as e:
        print(f"HTTP-statuscode: {e.response.status_code}")
        print(f"Ruwe responstekst van de RPC-relay:\n{e.response.text}")
    except Exception as e:
        print(f"Ander soort fout: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
