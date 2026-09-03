"""
transfer_hbar_to_bot.py

Stuurt native HBAR van een bron-account (het nieuwe, apart aangemaakte
account) door naar het bestaande bot-account -- zodat de WHBAR-
associatie van eerder vandaag behouden blijft.

Gebruik: zet SOURCE_ACCOUNT_PRIVATE_KEY als environment-variabele
(NOOIT in de chat plakken, alleen rechtstreeks op de VPS instellen).
"""

import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS


BOT_ACCOUNT_EVM_ADDRESS = "0x293ba5c20033400807217980E796A6C2abf70367"


def main():
    source_private_key = os.environ.get("SOURCE_ACCOUNT_PRIVATE_KEY")
    if not source_private_key:
        print("Geen SOURCE_ACCOUNT_PRIVATE_KEY gezet -- zie het bestand voor uitleg.")
        return

    amount_hbar = float(os.environ.get("TRANSFER_AMOUNT_HBAR", "8.0"))

    settings = NETWORK_SETTINGS["testnet"]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, source_private_key)

    print(f"Bron-account: {client.address}")
    print(f"Bestemming (bot-account): {BOT_ACCOUNT_EVM_ADDRESS}")
    print(f"Bedrag: {amount_hbar} HBAR")

    balance_before = client.get_hbar_balance()
    print(f"Balans bron-account vooraf: {balance_before} HBAR")

    amount_wei = client.w3.to_wei(amount_hbar, "ether")
    nonce = client.w3.eth.get_transaction_count(client.account.address)
    gas_price = int(client.w3.eth.gas_price * 1.2)

    tx = {
        "chainId": client.network.chain_id,
        "to": BOT_ACCOUNT_EVM_ADDRESS,
        "value": amount_wei,
        "gas": 100_000,
        "maxFeePerGas": gas_price,
        "maxPriorityFeePerGas": client.w3.to_wei(1, "gwei"),
        "nonce": nonce,
    }

    print("\nTransactie versturen...")
    signed_tx = client.w3.eth.account.sign_transaction(tx, client.account.key)
    tx_hash = client.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = client.wait_for_receipt(client.w3.to_hex(tx_hash))

    print(f"Status: {receipt['status']}")
    print(f"Tx hash: {client.w3.to_hex(tx_hash)}")

    if receipt["status"] == "success":
        print("\nGelukt! Controleer de nieuwe balans van het bot-account met "
              "de bekende balans-check.")
    else:
        print("\nMISLUKT -- controleer handmatig via HashScan.")


if __name__ == "__main__":
    main()
