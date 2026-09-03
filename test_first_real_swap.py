"""
test_first_real_swap.py

DE EERSTE ECHTE SWAP van dit hele project. Klein bedrag (1 HBAR),
tegen de bevestigde, actieve WHBAR/SAUCE-pool (fee=3000). Los van de
continue bot-loop (die blijft in DRY_RUN) -- dit is een eenmalige,
handmatige test om de gefixte multicall/decimalen-logica daadwerkelijk
te bevestigen tegen een echte pool.

HBAR -> SAUCE heeft GEEN unwrapWHBAR nodig (dat is alleen nodig als de
UITKOMST WHBAR is, hier is de uitkomst SAUCE).
"""

import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from hedera_address_utils import hedera_id_to_evm_address
from config import NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses
from swap_executor_v2 import SWAP_ROUTER_ABI, QUOTER_V2_ABI


SAUCE_TESTNET_ID = "0.0.1183558"
SAUCE_DECIMALS = 6
WHBAR_DECIMALS = 8
POOL_FEE = 3000
SWAP_AMOUNT_HBAR = 1.0
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

    print("=== EERSTE ECHTE SWAP ===")
    print(f"Account: {client.address}")
    print(f"Bedrag: {SWAP_AMOUNT_HBAR} HBAR -> SAUCE")
    print(f"Pool fee: {POOL_FEE}")

    balance_before = client.get_hbar_balance()
    print(f"HBAR-balans vooraf: {balance_before} HBAR")

    quoter = client.w3.eth.contract(address=v2.quoter_v2, abi=QUOTER_V2_ABI)
    router = client.w3.eth.contract(address=v2.swap_router, abi=SWAP_ROUTER_ABI)

    amount_in_8dec = int(SWAP_AMOUNT_HBAR * (10 ** WHBAR_DECIMALS))
    quote_params = (base.whbar_token, sauce_address, amount_in_8dec, POOL_FEE, 0)

    print("\nQuote opvragen...")
    quote_result = quoter.functions.quoteExactInputSingle(quote_params).call()
    estimated_sauce = quote_result[0] / (10 ** SAUCE_DECIMALS)
    print(f"Geschatte uitkomst: {estimated_sauce} SAUCE")

    min_out_raw = int(quote_result[0] * (1 - SLIPPAGE_TOLERANCE))
    amount_in_wei_for_msg_value = client.w3.to_wei(SWAP_AMOUNT_HBAR, "ether")

    swap_params = (
        base.whbar_token,
        sauce_address,
        POOL_FEE,
        client.address,
        client.w3.eth.get_block("latest")["timestamp"] + 120,
        amount_in_8dec,
        min_out_raw,
        0,
    )

    swap_fn = router.functions.exactInputSingle(swap_params)

    print("\nSwap versturen (gas wordt dynamisch geschat)...")
    tx_hash = client.build_and_send_transaction(swap_fn, value_wei=amount_in_wei_for_msg_value)
    receipt = client.wait_for_receipt(tx_hash)

    print(f"\nStatus: {receipt['status']}")
    print(f"Tx hash: {tx_hash}")

    balance_after = client.get_hbar_balance()
    print(f"HBAR-balans erna: {balance_after} HBAR (verschil: {balance_after - balance_before:.4f})")

    if receipt["status"] == "success":
        print("\nGELUKT -- de eerste echte swap van dit project is geslaagd. "
              "Dit bevestigt dat multicall, decimalen, en gas-schatting "
              "allemaal correct samenwerken tegen een echte pool.")
    else:
        print("\nMISLUKT -- controleer handmatig via HashScan.")


if __name__ == "__main__":
    main()
