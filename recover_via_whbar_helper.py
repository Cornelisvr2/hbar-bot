"""
recover_via_whbar_helper.py

DE JUISTE manier om WHBAR terug te unwrappen naar native HBAR --
via het aparte WhbarHelper-contract (0.0.5286055 op testnet), NIET via
de SwapRouter.

WhbarHelper.unwrapWhbar(wad) vereist EERST een approve() -- het
contract haalt de WHBAR actief op via safeTransferFrom().
"""

import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from hedera_address_utils import hedera_id_to_evm_address
from config import NETWORK_SETTINGS, resolve_testnet_addresses
from swap_executor import ERC20_ABI


WHBAR_HELPER_TESTNET_ID = "0.0.5286055"

WHBAR_HELPER_ABI = [
    {
        "name": "unwrapWhbar",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "wad", "type": "uint256"}],
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
    whbar_balance_raw = whbar_contract.functions.balanceOf(client.address).call()
    whbar_balance = whbar_balance_raw / (10 ** 8)

    print(f"WhbarHelper-adres: {whbar_helper_address}")
    print(f"Huidige WHBAR-balans: {whbar_balance}")
    hbar_before = client.get_hbar_balance()
    print(f"HBAR-balans vooraf: {hbar_before}")

    if whbar_balance_raw == 0:
        print("Niets om terug te halen.")
        return

    print("\nStap 1: approve() voor WhbarHelper...")
    approve_fn = whbar_contract.functions.approve(whbar_helper_address, whbar_balance_raw)
    approve_tx = client.build_and_send_transaction(approve_fn)
    approve_receipt = client.wait_for_receipt(approve_tx)
    print(f"Approve-status: {approve_receipt['status']}")

    if approve_receipt["status"] != "success":
        print("Approve mislukt -- stoppen.")
        return

    print("\nStap 2: unwrapWhbar() aanroepen op WhbarHelper...")
    whbar_helper = client.w3.eth.contract(address=whbar_helper_address, abi=WHBAR_HELPER_ABI)
    unwrap_fn = whbar_helper.functions.unwrapWhbar(whbar_balance_raw)
    tx_hash = client.build_and_send_transaction(unwrap_fn, gas_limit=1_000_000)
    receipt = client.wait_for_receipt(tx_hash)

    print(f"Status: {receipt['status']}")
    print(f"Tx hash: {tx_hash}")

    hbar_after = client.get_hbar_balance()
    whbar_balance_after_raw = whbar_contract.functions.balanceOf(client.address).call()
    whbar_balance_after = whbar_balance_after_raw / (10 ** 8)

    print(f"\nHBAR-balans erna: {hbar_after} (verschil: {hbar_after - hbar_before:+.4f})")
    print(f"WHBAR-balans erna: {whbar_balance_after}")

    if whbar_balance_after < whbar_balance:
        print("\nGELUKT -- WhbarHelper is de juiste route.")
    else:
        print("\nNog steeds niet gelukt -- verder uitzoekwerk nodig.")


if __name__ == "__main__":
    main()
