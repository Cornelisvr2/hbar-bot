"""
recover_stuck_whbar.py

Haalt het gestrande WHBAR-saldo terug naar native HBAR via een LOSSE,
NIET-gebundelde unwrapWHBAR()-aanroep. Dit test tegelijk of unwrapWHBAR
uberhaupt werkt op zichzelf (los van de multicall-vraag).
"""

import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses
from swap_executor_v2 import SWAP_ROUTER_ABI
from swap_executor import ERC20_ABI


def main():
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    settings = NETWORK_SETTINGS["testnet"]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, private_key)

    base = resolve_testnet_addresses()
    v2 = resolve_testnet_v2_addresses()

    whbar_contract = client.w3.eth.contract(address=base.whbar_token, abi=ERC20_ABI)
    whbar_balance_raw = whbar_contract.functions.balanceOf(client.address).call()
    whbar_balance = whbar_balance_raw / (10 ** 8)

    print(f"Huidige WHBAR-balans: {whbar_balance}")
    hbar_before = client.get_hbar_balance()
    print(f"HBAR-balans vooraf: {hbar_before}")

    if whbar_balance_raw == 0:
        print("Niets om terug te halen.")
        return

    router = client.w3.eth.contract(address=v2.swap_router, abi=SWAP_ROUTER_ABI)

    print("\nunwrapWHBAR() versturen als LOSSE (niet-gebundelde) transactie...")
    unwrap_fn = router.functions.unwrapWHBAR(0, client.address)
    tx_hash = client.build_and_send_transaction(unwrap_fn)
    receipt = client.wait_for_receipt(tx_hash)

    print(f"Status: {receipt['status']}")
    print(f"Tx hash: {tx_hash}")

    hbar_after = client.get_hbar_balance()
    whbar_balance_after_raw = whbar_contract.functions.balanceOf(client.address).call()
    whbar_balance_after = whbar_balance_after_raw / (10 ** 8)

    print(f"\nHBAR-balans erna: {hbar_after} (verschil: {hbar_after - hbar_before:+.4f})")
    print(f"WHBAR-balans erna: {whbar_balance_after}")

    if whbar_balance_after < whbar_balance:
        print("\nGELUKT -- WHBAR-balans is gedaald, unwrapWHBAR werkt op zichzelf. "
              "Het probleem zit dus specifiek in de multicall-bundeling, niet in "
              "unwrapWHBAR zelf.")
    else:
        print("\nOOK DIT WERKTE NIET -- unwrapWHBAR lijkt fundamenteel niet te doen "
              "wat we verwachten, ook los van multicall. Verdere uitzoekwerk nodig.")


if __name__ == "__main__":
    main()
