"""
test_reverse_swap.py

TWEEDE echte swap: SAUCE -> HBAR, de omgekeerde richting van
test_first_real_swap.py. Dit is het belangrijkste nog niet empirisch
geteste code-pad: hier is de UITKOMST WHBAR, dus is de unwrapWHBAR-fix
(gisteren toegevoegd op basis van de officiele docs, nooit eerder live
getest) daadwerkelijk nodig -- zonder deze fix zou het resultaat
steken blijven als WHBAR-ERC20-token i.p.v. native HBAR.

Vereist een voorafgaande approve() voor SAUCE (niet nodig bij de
vorige test, want daar was de input native HBAR).
"""

import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from hedera_address_utils import hedera_id_to_evm_address
from config import NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses
from swap_executor_v2 import SWAP_ROUTER_ABI, QUOTER_V2_ABI
from swap_executor import ERC20_ABI


SAUCE_TESTNET_ID = "0.0.1183558"
SAUCE_DECIMALS = 6
WHBAR_DECIMALS = 8
POOL_FEE = 3000
SWAP_AMOUNT_SAUCE = 5.0
SLIPPAGE_TOLERANCE = 0.02


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

    print("=== TWEEDE ECHTE SWAP (omgekeerde richting) ===")
    print(f"Account: {client.address}")
    print(f"Bedrag: {SWAP_AMOUNT_SAUCE} SAUCE -> HBAR")

    hbar_balance_before = client.get_hbar_balance()
    sauce_contract = client.w3.eth.contract(address=sauce_address, abi=ERC20_ABI)
    sauce_balance_before_raw = sauce_contract.functions.balanceOf(client.address).call()
    sauce_balance_before = sauce_balance_before_raw / (10 ** SAUCE_DECIMALS)

    print(f"HBAR-balans vooraf: {hbar_balance_before} HBAR")
    print(f"SAUCE-balans vooraf: {sauce_balance_before} SAUCE")

    amount_in_raw = int(SWAP_AMOUNT_SAUCE * (10 ** SAUCE_DECIMALS))

    print("\nApprove() voor SAUCE versturen...")
    approve_fn = sauce_contract.functions.approve(v2.swap_router, amount_in_raw)
    approve_tx = client.build_and_send_transaction(approve_fn)
    approve_receipt = client.wait_for_receipt(approve_tx)
    print(f"Approve-status: {approve_receipt['status']}")

    if approve_receipt["status"] != "success":
        print("Approve mislukt -- swap wordt niet geprobeerd.")
        return

    quoter = client.w3.eth.contract(address=v2.quoter_v2, abi=QUOTER_V2_ABI)
    quote_params = (sauce_address, base.whbar_token, amount_in_raw, POOL_FEE, 0)

    print("\nQuote opvragen...")
    quote_result = quoter.functions.quoteExactInputSingle(quote_params).call()
    estimated_hbar = quote_result[0] / (10 ** WHBAR_DECIMALS)
    print(f"Geschatte uitkomst: {estimated_hbar} HBAR")

    min_out_raw = int(quote_result[0] * (1 - SLIPPAGE_TOLERANCE))

    router = client.w3.eth.contract(address=v2.swap_router, abi=SWAP_ROUTER_ABI)
    swap_params = (
        sauce_address,
        base.whbar_token,
        POOL_FEE,
        v2.swap_router,  # KRITIEK: router-adres, NIET client.address --
        # anders heeft unwrapWHBAR daarna niets om te unwrappen (empirisch
        # bevestigd 24 aug 2026: eerste poging bleef steken als WHBAR).
        client.w3.eth.get_block("latest")["timestamp"] + 120,
        amount_in_raw,
        min_out_raw,
        0,
    )

    swap_encoded = router.encode_abi("exactInputSingle", args=[swap_params])
    unwrap_encoded = router.encode_abi("unwrapWHBAR", args=[0, client.address])

    print("\nSwap + unwrapWHBAR versturen via multicall...")
    multicall_fn = router.functions.multicall([swap_encoded, unwrap_encoded])
    tx_hash = client.build_and_send_transaction(multicall_fn)
    receipt = client.wait_for_receipt(tx_hash)

    print(f"\nStatus: {receipt['status']}")
    print(f"Tx hash: {tx_hash}")

    hbar_balance_after = client.get_hbar_balance()
    sauce_balance_after_raw = sauce_contract.functions.balanceOf(client.address).call()
    sauce_balance_after = sauce_balance_after_raw / (10 ** SAUCE_DECIMALS)

    print(f"HBAR-balans erna: {hbar_balance_after} HBAR "
          f"(verschil: {hbar_balance_after - hbar_balance_before:+.4f})")
    print(f"SAUCE-balans erna: {sauce_balance_after} SAUCE "
          f"(verschil: {sauce_balance_after - sauce_balance_before:+.4f})")

    if receipt["status"] == "success" and (hbar_balance_after - hbar_balance_before) > 0:
        print("\nGELUKT -- de HBAR-balans is daadwerkelijk gestegen, wat bevestigt "
              "dat unwrapWHBAR correct werkte en het resultaat NIET is blijven "
              "steken als WHBAR-ERC20-token.")
    elif receipt["status"] == "success":
        print("\nTransactie geslaagd, maar HBAR-balans is niet duidelijk gestegen -- "
              "controleer handmatig of het bedrag als WHBAR is blijven steken "
              "(zoek WHBAR-balans in je wallet).")
    else:
        print("\nMISLUKT -- controleer handmatig via HashScan.")


if __name__ == "__main__":
    main()
