"""
test_low_v3.py

Test met een TIJDELIJK, alleen-in-dit-script verbrede LOW-breedte
(7% i.p.v. de standaard 5%), om te isoleren of het probleem specifiek
bij de 5%-breedte zit, of bij smalle ranges in het algemeen.
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

# Monkey-patch: TIJDELIJK, alleen in dit proces, de LOW-breedte verbreden
# van 5% naar 7% -- raakt de productiecode niet aan.
lp_manager.RANGE_WIDTH_BY_REGIME[VolatilityRegime.LOW] = 0.07


SAUCE_TESTNET_ID = "0.0.1183558"
SAUCE_DECIMALS = 6
WHBAR_DECIMALS = 8
POOL_FEE = 3000


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
        whbar_helper_address=base.whbar_helper,
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
    print(f"Huidige balans: {hbar_balance:.4f} HBAR (na {GAS_RESERVE_HBAR:.0f} HBAR gas-reserve) + {sauce_balance:.2f} SAUCE")

    live_price = get_live_pool_price(
        client, v2.factory, base.whbar_token, sauce_address, POOL_FEE,
        WHBAR_DECIMALS, SAUCE_DECIMALS,
    )
    print(f"Live pool-prijs: {live_price}")

    tick_lower, tick_upper = manager.compute_range(
        live_price, VolatilityRegime.LOW, sentiment_direction=0.0
    )
    print(f"Range (LOW, verbreed naar 7%): [{tick_lower}, {tick_upper}]")

    hbar_raw_available = int(1.0 * (10 ** WHBAR_DECIMALS))
    usdc_raw_available = int(sauce_balance * (10 ** SAUCE_DECIMALS))
    needed_usdc_for_full_hbar = compute_amount1_for_amount0(
        hbar_raw_available, live_price, tick_lower, tick_upper, WHBAR_DECIMALS, SAUCE_DECIMALS
    )
    hbar_raw, usdc_raw = hbar_raw_available, min(needed_usdc_for_full_hbar, usdc_raw_available)

    print(f"\n=== Positie openen: {hbar_raw/(10**WHBAR_DECIMALS):.4f} HBAR "
          f"+ {usdc_raw/(10**SAUCE_DECIMALS):.2f} SAUCE ===")

    try:
        token_id = manager.open_position(
            hbar_raw, usdc_raw, live_price,
            volatility_regime=VolatilityRegime.LOW, sentiment_direction=0.0,
            slippage_tolerance=0.15, gas_limit_override=1_200_000,
        )
        print(f"GELUKT -- nieuwe positie: token_id={token_id}")

        db = PostgresClient()
        await db.connect()
        await db.clear_active_lp_position()
        await db.save_active_lp_position(token_id, tick_lower, tick_upper)
        await db.close()
        print("Database bijgewerkt.")
    except requests.exceptions.HTTPError as e:
        print(f"HTTP-statuscode: {e.response.status_code}")
        print(f"Ruwe responstekst:\n{e.response.text}")
    except Exception as e:
        print(f"MISLUKT: {e}")


if __name__ == "__main__":
    asyncio.run(main())
