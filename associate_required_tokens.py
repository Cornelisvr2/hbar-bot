"""
associate_required_tokens.py

Associeert de drie vereiste tokens (WHBAR, SAUCE, LP-NFT) in EEN
transactie via Hedera's HTS-systeemcontract op adres 0x167
(0.0.359 in Hedera-formaat) -- dit is de EVM-route voor
TokenAssociateTransaction, zodat we niet de aparte Hedera SDK nodig
hebben (die tot nu toe bewust niet is gebruikt in dit project).

Kost een kleine hoeveelheid HBAR aan gas -- niet gratis zoals de
read-only verificatiescripts.
"""

import os

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
    # WHBAR is al apart geassocieerd (23 aug 2026, via diagnose_single_associate.py
    # met 5.000.000 gas) -- hier bewust weggelaten, want associateTokens()
    # faalt soms als ook maar 1 van de meegegeven tokens al geassocieerd is.
    "SAUCE": "0.0.1183558",
    "LP-NFT (SaucerSwapV2)": "0.0.1310436",
}


def main():
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    if not private_key:
        print("Geen HEDERA_BOT_PRIVATE_KEY gezet.")
        return

    settings = NETWORK_SETTINGS["testnet"]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, private_key)

    token_addresses = [hedera_id_to_evm_address(tid) for tid in REQUIRED_TOKENS_TESTNET.values()]

    print(f"Account: {client.address}")
    print("Te associeren tokens:")
    for label, tid in REQUIRED_TOKENS_TESTNET.items():
        print(f"  {label}: {tid}")

    hts = client.w3.eth.contract(address=HTS_PRECOMPILE_ADDRESS, abi=HTS_PRECOMPILE_ABI)
    associate_fn = hts.functions.associateTokens(client.address, token_addresses)

    print("\nTransactie versturen (gas wordt dynamisch geschat)...")
    tx_hash = client.build_and_send_transaction(associate_fn)
    receipt = client.wait_for_receipt(tx_hash)

    print(f"Status: {receipt['status']}")
    print(f"Tx hash: {tx_hash}")

    if receipt["status"] == "success":
        print("\nAlle drie de tokens succesvol geassocieerd. Verifieer met "
              "verify_token_associations.py.")
    else:
        print("\nMISLUKT -- controleer de transactie handmatig via HashScan. "
              "Mogelijke oorzaken: onvoldoende HBAR voor gas, of een token "
              "was al geassocieerd (associateTokens faalt soms als ook maar "
              "1 van de tokens al geassocieerd is -- dan moet je ze mogelijk "
              "los proberen).")


if __name__ == "__main__":
    main()
