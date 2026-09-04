from lp_manager import get_live_pool_price
from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, HEDERA_NETWORK, resolve_mainnet_v2_addresses, resolve_mainnet_addresses
import os

print(f"=== V2-verificatie op {HEDERA_NETWORK} ===\n")

settings = NETWORK_SETTINGS[HEDERA_NETWORK]
network_config = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
rpc_client = HederaRpcClient(network_config, os.environ["HEDERA_BOT_PRIVATE_KEY"])

v2 = resolve_mainnet_v2_addresses()
base = resolve_mainnet_addresses()

print(f"Factory: {v2.factory}")
print(f"WHBAR: {base.whbar_token}")
print(f"USDC: {base.usdc}")

fee_tier = int(os.environ.get("LP_FEE_TIER", "3000"))
print(f"Fee-tier (uit LP_FEE_TIER): {fee_tier}")

try:
    prijs = get_live_pool_price(
        rpc_client, v2.factory, base.whbar_token, base.usdc, fee_tier,
        8, base.usdc_decimals,
    )
    print(f"\nDaadwerkelijke, on-chain pool-prijs (1 HBAR in USDC): {prijs:.6f}")
except Exception as e:
    print(f"\nFOUT: {e}")
