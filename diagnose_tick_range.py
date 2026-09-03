"""
diagnose_tick_range.py

Vraagt de WERKELIJKE huidige tick rechtstreeks bij de pool op (via
slot0()) en vergelijkt die met onze eigen berekende tick_lower/tick_upper.
"""

import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from hedera_address_utils import hedera_id_to_evm_address
from config import NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses
from lp_manager import LpManager, LpPositionConfig, VolatilityRegime


SAUCE_TESTNET_ID = "0.0.1183558"
SAUCE_DECIMALS = 6
WHBAR_DECIMALS = 8
POOL_FEE = 3000

V2_FACTORY_ABI = [
    {
        "name": "getPool", "type": "function", "stateMutability": "view",
        "inputs": [
            {"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"},
            {"name": "fee", "type": "uint24"},
        ],
        "outputs": [{"name": "pool", "type": "address"}],
    },
]

POOL_SLOT0_ABI = [
    {
        "name": "slot0", "type": "function", "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"},
            {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"},
            {"name": "feeProtocol", "type": "uint8"},
            {"name": "unlocked", "type": "bool"},
        ],
    },
]


def main():
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    settings = NETWORK_SETTINGS["testnet"]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, private_key)

    base = resolve_testnet_addresses()
    v2 = resolve_testnet_v2_addresses()
    sauce_address = hedera_id_to_evm_address(SAUCE_TESTNET_ID)

    factory = client.w3.eth.contract(address=v2.factory, abi=V2_FACTORY_ABI)
    pool_address = factory.functions.getPool(base.whbar_token, sauce_address, POOL_FEE).call()
    print(f"Pool-adres: {pool_address}")

    pool = client.w3.eth.contract(address=pool_address, abi=POOL_SLOT0_ABI)
    slot0 = pool.functions.slot0().call()
    actual_current_tick = slot0[1]
    print(f"WERKELIJKE huidige tick (rechtstreeks van de pool): {actual_current_tick}")

    config = LpPositionConfig(
        position_manager_address=v2.position_manager,
        token0=base.whbar_token, token1=sauce_address,
        whbar_address=base.whbar_token,
        fee_tier=POOL_FEE,
        token0_decimals=WHBAR_DECIMALS, token1_decimals=SAUCE_DECIMALS,
    )
    manager = LpManager(client, config)

    from swap_executor_v2 import QUOTER_V2_ABI
    quoter = client.w3.eth.contract(address=v2.quoter_v2, abi=QUOTER_V2_ABI)
    quote_params = (base.whbar_token, sauce_address, 10**WHBAR_DECIMALS, POOL_FEE, 0)
    quote_result = quoter.functions.quoteExactInputSingle(quote_params).call()
    current_price = quote_result[0] / (10 ** SAUCE_DECIMALS)
    print(f"Onze prijs (via quote): {current_price} SAUCE per WHBAR")

    tick_lower, tick_upper = manager.compute_range(current_price, VolatilityRegime.NORMAL, 0.0)
    print(f"Onze berekende range: [{tick_lower}, {tick_upper}]")

    if tick_lower <= actual_current_tick <= tick_upper:
        print("\nDe werkelijke tick VALT BINNEN onze range -- dit is dus NIET de oorzaak.")
    else:
        print(f"\nPROBLEEM GEVONDEN: de werkelijke tick ({actual_current_tick}) VALT NIET "
              f"binnen onze berekende range [{tick_lower}, {tick_upper}]! "
              f"Dit verklaart de aanhoudende 'Price slippage check'-fout volledig.")


if __name__ == "__main__":
    main()
