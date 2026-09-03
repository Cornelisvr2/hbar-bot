"""
wrap_hbar_to_whbar.py

Wrapt native HBAR naar WHBAR (1:1) via WhbarHelper.deposit() --
bevestigd correct patroon uit de officiele docs
(developers/whbar/wrap-hbar-for-whbar).
"""

import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from hedera_address_utils import hedera_id_to_evm_address
from config import NETWORK_SETTINGS, resolve_testnet_addresses
from swap_executor import ERC20_ABI


WHBAR_HELPER_TESTNET_ID = "0.0.5286055"
WRAP_AMOUNT_HBAR = 0.5

WHBAR_HELPER_ABI = [
    {
        "name": "deposit",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [],
        "outputs": [],
    },
]


def main():
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    settings = NETWORK_SETTINGS["testnet"]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, private_key)

    base = resolve_testnet_addresses()
    whbar_helper_address = hedera_id_to_evm_address(WHBAR_HELPER_TESTNET_ID)

    whbar_contract = client.w3.eth.contract(address=base.whbar_token, abi=ERC20_ABI)
    whbar_balance_before = whbar_contract.functions.balanceOf(client.address).call() / (10 ** 8)
    hbar_before = client.get_hbar_balance()

    print(f"HBAR-balans vooraf: {hbar_before}")
    print(f"WHBAR-balans vooraf: {whbar_balance_before}")
    print(f"\n{WRAP_AMOUNT_HBAR} HBAR wrappen naar WHBAR...")

    whbar_helper = client.w3.eth.contract(address=whbar_helper_address, abi=WHBAR_HELPER_ABI)
    deposit_fn = whbar_helper.functions.deposit()
    value_wei = client.w3.to_wei(WRAP_AMOUNT_HBAR, "ether")

    tx_hash = client.build_and_send_transaction(deposit_fn, value_wei=value_wei)
    receipt = client.wait_for_receipt(tx_hash)

    print(f"Status: {receipt['status']}")
    print(f"Tx hash: {tx_hash}")

    hbar_after = client.get_hbar_balance()
    whbar_balance_after = whbar_contract.functions.balanceOf(client.address).call() / (10 ** 8)

    print(f"\nHBAR-balans erna: {hbar_after} (verschil: {hbar_after - hbar_before:+.4f})")
    print(f"WHBAR-balans erna: {whbar_balance_after} (verschil: {whbar_balance_after - whbar_balance_before:+.4f})")


if __name__ == "__main__":
    main()
