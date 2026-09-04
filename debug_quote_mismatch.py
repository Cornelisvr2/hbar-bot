from swap_executor_v2 import build_swap_config_v2, SwapExecutorV2
from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, HEDERA_NETWORK
import os

print(f"HEDERA_NETWORK: {HEDERA_NETWORK}")
config = build_swap_config_v2(HEDERA_NETWORK)
print(f"fee_tier: {config.fee_tier}")
print(f"whbar_decimals: {config.whbar_decimals}")
print(f"usdc_decimals: {config.usdc_decimals}")
print(f"whbar_address: {config.whbar_address}")
print(f"usdc_address: {config.usdc_address}")

settings = NETWORK_SETTINGS[HEDERA_NETWORK]
network_config = NetworkConfig(
    rpc_url=settings["rpc_url"], chain_id=settings["chain_id"],
    private_key=os.environ["HEDERA_BOT_PRIVATE_KEY"],
)
rpc_client = HederaRpcClient(network_config)
executor = SwapExecutorV2(rpc_client, config)

# Rechtstreeks, met de BEVESTIGDE fee-tier (1500) in plaats van de config-default
amount_in_raw = int(1.0 * (10 ** config.whbar_decimals))
params = (
    config.whbar_address, config.usdc_address, amount_in_raw, 1500, 0,
)
result = executor.quoter.functions.quoteExactInputSingle(params).call()
print(f"\nRuwe quote-uitkomst (amount_out), MET fee_tier=1500: {result[0]}")
print(f"Gedeeld door 10^6 (USDC-standaard): {result[0] / (10**6):.6f}")
print(f"Gedeeld door config.usdc_decimals ({config.usdc_decimals}): {result[0] / (10**config.usdc_decimals):.6f}")
