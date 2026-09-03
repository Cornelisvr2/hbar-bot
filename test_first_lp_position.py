"""
test_first_lp_position.py

DE EERSTE ECHTE LP-POSITIE van dit project. Klein bedrag, geopend en
DIRECT weer gesloten in dezelfde run -- test de volledige cyclus
(mint met multicall+payable+mint-fee, en de zojuist gecorrigeerde
close_position met de WhbarHelper-route) in een keer.
"""

import os
import time

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from hedera_address_utils import hedera_id_to_evm_address
from config import NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses
from lp_manager import LpManager, LpPositionConfig, VolatilityRegime


SAUCE_TESTNET_ID = "0.0.1183558"
SAUCE_DECIMALS = 6
WHBAR_DECIMALS = 8
POOL_FEE = 3000

HBAR_SIDE_AMOUNT = 0.3
SAUCE_SIDE_AMOUNT = 17.0


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

    config = LpPositionConfig(
        position_manager_address=v2.position_manager,
        token0=base.whbar_token, token1=sauce_address,
        whbar_address=base.whbar_token,
        whbar_helper_address=base.whbar_helper,
        factory_address=v2.factory,
        mirror_node_url=settings["mirror_node_url"],
        fee_tier=POOL_FEE,
        token0_decimals=WHBAR_DECIMALS, token1_decimals=SAUCE_DECIMALS,
    )
    manager = LpManager(client, config)

    print("=== EERSTE ECHTE LP-POSITIE ===")
    print(f"Account: {client.address}")

    hbar_before = client.get_hbar_balance()
    print(f"HBAR-balans vooraf: {hbar_before}")

    from swap_executor_v2 import QUOTER_V2_ABI
    quoter = client.w3.eth.contract(address=v2.quoter_v2, abi=QUOTER_V2_ABI)
    quote_params = (base.whbar_token, sauce_address, 10**WHBAR_DECIMALS, POOL_FEE, 0)
    quote_result = quoter.functions.quoteExactInputSingle(quote_params).call()
    current_price = quote_result[0] / (10 ** SAUCE_DECIMALS)
    print(f"Huidige prijsverhouding: {current_price} SAUCE per WHBAR")

    amount0_raw = int(HBAR_SIDE_AMOUNT * (10 ** WHBAR_DECIMALS))

    # amount1 WISKUNDIG AFLEIDEN uit amount0 en de tick-range, i.p.v. een
    # los geschat SAUCE-bedrag (24 aug 2026, aandachtspunt uit de docs) --
    # zelfde principe als Uniswap V3 SDK's Position.fromAmount0().
    from lp_manager import compute_amount1_for_amount0
    tick_lower, tick_upper = manager.compute_range(current_price, VolatilityRegime.NORMAL, 0.0)
    amount1_raw = compute_amount1_for_amount0(
        amount0_raw, current_price, tick_lower, tick_upper, WHBAR_DECIMALS, SAUCE_DECIMALS
    )
    sauce_side_amount = amount1_raw / (10 ** SAUCE_DECIMALS)
    print(f"Afgeleid amount1: {sauce_side_amount:.4f} SAUCE (i.p.v. het eerder geschatte {SAUCE_SIDE_AMOUNT})")

    print(f"\nPositie openen: {HBAR_SIDE_AMOUNT} WHBAR + {sauce_side_amount:.4f} SAUCE...")
    import requests
    try:
        token_id = manager.open_position(
            amount0_raw, amount1_raw, current_price,
            slippage_tolerance=0.15,  # gericht gekozen op basis van de exacte trace-analyse (~11.5% afwijking)
            volatility_regime=VolatilityRegime.NORMAL, sentiment_direction=0.0,
            gas_limit_override=1_200_000,  # omzeilt de falende estimate_gas-simulatie (25 aug 2026)
        )
        print(f"GELUKT -- positie geopend, token_id={token_id}")
    except requests.exceptions.HTTPError as e:
        print(f"HTTP-statuscode: {e.response.status_code}")
        print(f"Ruwe responstekst van de RPC-relay:\n{e.response.text}")
        return
    except Exception as e:
        print(f"MISLUKT bij het openen: {e}")
        return

    hbar_after_open = client.get_hbar_balance()
    print(f"HBAR-balans na openen: {hbar_after_open} (verschil: {hbar_after_open - hbar_before:+.4f})")

    print("\nEven wachten (5 sec) voordat we de positie weer sluiten...")
    time.sleep(5)

    print(f"\nPositie {token_id} weer sluiten...")
    try:
        close_tx = manager.close_position(token_id)
        print(f"Sluit-status: {'GELUKT' if close_tx else 'MISLUKT'}, tx={close_tx}")
    except Exception as e:
        print(f"MISLUKT bij het sluiten: {e}")
        return

    hbar_final = client.get_hbar_balance()
    print(f"\nHBAR-balans na sluiten: {hbar_final} (totale verschil t.o.v. start: {hbar_final - hbar_before:+.4f})")
    print("\nDit totale verschil is puur gas-kosten voor de volledige open+close-cyclus.")


if __name__ == "__main__":
    main()
