from swap_executor_v2 import build_swap_config_v2
from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, HEDERA_NETWORK
import os

config = build_swap_config_v2(HEDERA_NETWORK)
print(f"Config fee_tier (uit de default, mogelijk verouderd): {config.fee_tier}")

settings = NETWORK_SETTINGS[HEDERA_NETWORK]
network_config = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
rpc_client = HederaRpcClient(network_config, os.environ["HEDERA_BOT_PRIVATE_KEY"])

from swap_executor_v2 import SwapExecutorV2
executor = SwapExecutorV2(rpc_client, config)

amount_in_raw = int(1.0 * (10 ** config.whbar_decimals))

for test_fee_tier in [500, 1500, 3000, 10000]:
    try:
        params = (config.whbar_address, config.usdc_address, amount_in_raw, test_fee_tier, 0)
        result = executor.quoter.functions.quoteExactInputSingle(params).call()
        prijs = result[0] / (10 ** config.usdc_decimals)
        print(f"fee_tier={test_fee_tier}: 1 HBAR = {prijs:.6f} USDC")
    except Exception as e:
        print(f"fee_tier={test_fee_tier}: FOUT -- {e}")
