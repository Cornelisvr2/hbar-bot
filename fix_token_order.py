from lp_manager import get_live_pool_price
from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, HEDERA_NETWORK, resolve_mainnet_v2_addresses, resolve_mainnet_addresses
import os

settings = NETWORK_SETTINGS[HEDERA_NETWORK]
network_config = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
rpc_client = HederaRpcClient(network_config, os.environ["HEDERA_BOT_PRIVATE_KEY"])

v2 = resolve_mainnet_v2_addresses()
base = resolve_mainnet_addresses()
fee_tier = int(os.environ.get("LP_FEE_TIER", "3000"))

# Test 1: zoals voorheen (WHBAR als token0, USDC als token1)
prijs1 = get_live_pool_price(
    rpc_client, v2.factory, base.whbar_token, base.usdc, fee_tier,
    8, base.usdc_decimals,
)
print(f"WHBAR als token0, USDC als token1: {prijs1:.8f}")

# Test 2: omgekeerd (USDC als token0, WHBAR als token1) -- past bij de
# daadwerkelijke, numerieke adresvolgorde op mainnet
prijs2 = get_live_pool_price(
    rpc_client, v2.factory, base.usdc, base.whbar_token, fee_tier,
    base.usdc_decimals, 8,
)
print(f"USDC als token0, WHBAR als token1: {prijs2:.8f}")
print(f"(dit zou de prijs van 1 USDC in HBAR moeten zijn, dus 1/prijs2 = HBAR-prijs in USD)")
print(f"1 / prijs2 = {1/prijs2:.6f} USD per HBAR")
