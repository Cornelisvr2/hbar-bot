"""
test_large_buffer_only.py

Test op suggestie van SaucerSwap support: msg.value = amount0Desired +
~0.7 HBAR, ZONDER de wrap+approve-stap die we eerder toevoegden.
"""

import asyncio
import os
import requests

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from hedera_address_utils import hedera_id_to_evm_address
from config import NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses
import lp_manager
from lp_manager import (
    LpManager, LpPositionConfig, VolatilityRegime,
    compute_amount1_for_amount0, compute_amount0_for_amount1, get_live_pool_price,
)
from postgres_client import PostgresClient
from swap_executor import ERC20_ABI

lp_manager.RANGE_WIDTH_BY_REGIME[VolatilityRegime.LOW] = 0.10

SAUCE_TESTNET_ID = "0.0.1183558"
SAUCE_DECIMALS = 6
WHBAR_DECIMALS = 8
POOL_FEE = 3000

LARGE_BUFFER_TINYBAR = int(0.7 * (10 ** 8))


async def main():
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
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
        whbar_helper_address=None,
        factory_address=v2.factory,
        fee_tier=POOL_FEE,
        token0_decimals=WHBAR_DECIMALS, token1_decimals=SAUCE_DECIMALS,
    )
    manager = LpManager(client, config)

    GAS_RESERVE_HBAR = 25.0

    hbar_balance = float(client.get_hbar_balance())
    hbar_balance = max(0.0, hbar_balance - GAS_RESERVE_HBAR)
    sauce_contract = client.w3.eth.contract(address=sauce_address, abi=ERC20_ABI)
    sauce_balance = sauce_contract.functions.balanceOf(client.address).call() / (10 ** SAUCE_DECIMALS)
    print(f"Huidige balans: {hbar_balance:.4f} HBAR + {sauce_balance:.2f} SAUCE")

    live_price = get_live_pool_price(
        client, v2.factory, base.whbar_token, sauce_address, POOL_FEE,
        WHBAR_DECIMALS, SAUCE_DECIMALS,
    )
    print(f"Live pool-prijs: {live_price}")

    tick_lower, tick_upper = manager.compute_range(
        live_price, VolatilityRegime.LOW, sentiment_direction=0.0
    )
    print(f"Range (LOW, 10%): [{tick_lower}, {tick_upper}]")

    hbar_raw_available = int(1.0 * (10 ** WHBAR_DECIMALS))
    usdc_raw_available = int(sauce_balance * (10 ** SAUCE_DECIMALS))
    needed_usdc_for_full_hbar = compute_amount1_for_amount0(
        hbar_raw_available, live_price, tick_lower, tick_upper, WHBAR_DECIMALS, SAUCE_DECIMALS
    )
    hbar_raw, usdc_raw = hbar_raw_available, min(needed_usdc_for_full_hbar, usdc_raw_available)

    print(f"\n=== Positie openen (ALLEEN grote msg.value-buffer, geen wrap): "
          f"{hbar_raw/(10**WHBAR_DECIMALS):.4f} HBAR + {usdc_raw/(10**SAUCE_DECIMALS):.2f} SAUCE ===")
    print(f"Buffer: {LARGE_BUFFER_TINYBAR} tinybar (0.7 HBAR)")

    manager._ensure_token_approval(config.token0, int(hbar_raw * 1.005))
    manager._ensure_token_approval(config.token1, int(usdc_raw * 1.005))

    deadline = manager._deadline()
    params = (
        config.token0, config.token1, config.fee_tier,
        tick_lower, tick_upper,
        hbar_raw, usdc_raw,
        int(hbar_raw * 0.85), int(usdc_raw * 0.85),
        client.address, deadline,
    )
    mint_encoded = manager.position_manager.encode_abi("mint", args=[params])
    refund_eth_encoded = manager.position_manager.encode_abi("refundETH", args=[])

    decimal_correction = 10 ** (18 - WHBAR_DECIMALS)
    payable_value = (hbar_raw + LARGE_BUFFER_TINYBAR) * decimal_correction

    try:
        multicall_fn = manager.position_manager.functions.multicall([mint_encoded, refund_eth_encoded])
        tx_hash = client.build_and_send_transaction(
            multicall_fn, value_wei=payable_value, gas_limit=1_200_000,
        )
        receipt = client.wait_for_receipt(tx_hash)
        if receipt["status"] != "success":
            print(f"MISLUKT: {tx_hash}")
        else:
            token_id = manager._extract_token_id_from_mint(tx_hash)
            print(f"GELUKT -- nieuwe positie: token_id={token_id}")

            db = PostgresClient()
            await db.connect()
            await db.save_active_lp_position(token_id, tick_lower, tick_upper)
            await db.close()
    except requests.exceptions.HTTPError as e:
        print(f"HTTP-statuscode: {e.response.status_code}")
        print(f"Ruwe responstekst:\n{e.response.text}")
    except Exception as e:
        print(f"MISLUKT: {e}")


if __name__ == "__main__":
    asyncio.run(main())
