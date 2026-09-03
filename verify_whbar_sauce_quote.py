"""
verify_whbar_sauce_quote.py

Nu we weten dat er een ECHTE, actieve WHBAR/SAUCE-pool bestaat
(fee=3000, via test-api.saucerswap.finance bevestigd), testen we hier
een daadwerkelijke QuoterV2-call -- dit lost de decimalen-vraag die de
hele dag openstond definitief op.
"""

import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from hedera_address_utils import hedera_id_to_evm_address
from config import NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses


QUOTER_V2_ABI = [
    {
        "name": "quoteExactInputSingle", "type": "function", "stateMutability": "nonpayable",
        "inputs": [{
            "name": "params", "type": "tuple",
            "components": [
                {"name": "tokenIn", "type": "address"},
                {"name": "tokenOut", "type": "address"},
                {"name": "amountIn", "type": "uint256"},
                {"name": "fee", "type": "uint24"},
                {"name": "sqrtPriceLimitX96", "type": "uint160"},
            ],
        }],
        "outputs": [
            {"name": "amountOut", "type": "uint256"},
            {"name": "sqrtPriceX96After", "type": "uint160"},
            {"name": "initializedTicksCrossed", "type": "uint32"},
            {"name": "gasEstimate", "type": "uint256"},
        ],
    },
]

SAUCE_TESTNET_ID = "0.0.1183558"
SAUCE_DECIMALS = 6
WHBAR_DECIMALS = 8
POOL_FEE = 3000


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

    quoter = client.w3.eth.contract(address=v2.quoter_v2, abi=QUOTER_V2_ABI)

    amount_in_8dec = int(1.0 * (10 ** WHBAR_DECIMALS))
    params_8dec = (base.whbar_token, sauce_address, amount_in_8dec, POOL_FEE, 0)

    print("=== Test A: amountIn in WHBAR's eigen 8-decimalen-termen ===")
    try:
        result = quoter.functions.quoteExactInputSingle(params_8dec).call()
        amount_out_raw = result[0]
        amount_out_sauce = amount_out_raw / (10 ** SAUCE_DECIMALS)
        print(f"1 WHBAR (8-dec encoded) -> {amount_out_sauce} SAUCE")
        expected_ratio = 0.07866999 / 0.0013683127305514867
        print(f"Verwachte ratio (uit priceUsd): ~{expected_ratio:.2f} SAUCE per WHBAR")
    except Exception as e:
        print(f"FOUT: {str(e)[:200]}")

    print()

    amount_in_18dec = client.w3.to_wei(1.0, "ether")
    params_18dec = (base.whbar_token, sauce_address, amount_in_18dec, POOL_FEE, 0)

    print("=== Test B: amountIn in 18-decimalen (huidige swap_executor_v2.py-aanname) ===")
    try:
        result = quoter.functions.quoteExactInputSingle(params_18dec).call()
        amount_out_raw = result[0]
        amount_out_sauce = amount_out_raw / (10 ** SAUCE_DECIMALS)
        print(f"1 WHBAR (18-dec encoded) -> {amount_out_sauce} SAUCE")
        print("Als dit factor 10^10 groter is dan Test A, is de 18-decimalen-aanname FOUT.")
    except Exception as e:
        print(f"FOUT: {str(e)[:200]}")


if __name__ == "__main__":
    main()
