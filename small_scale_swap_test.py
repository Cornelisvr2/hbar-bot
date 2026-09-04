from swap_executor_v2 import build_swap_config_v2, SwapExecutorV2
from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, HEDERA_NETWORK
import os

KLEIN_TESTBEDRAG_HBAR = 300.0

settings = NETWORK_SETTINGS[HEDERA_NETWORK]
network_config = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
rpc_client = HederaRpcClient(network_config, os.environ["HEDERA_BOT_PRIVATE_KEY"])

fee_tier = int(os.environ.get("LP_FEE_TIER", "3000"))
config = build_swap_config_v2(HEDERA_NETWORK, fee_tier=fee_tier)
executor = SwapExecutorV2(rpc_client, config)

print(f"=== Stap 1: quote voor {KLEIN_TESTBEDRAG_HBAR} HBAR -> USDC ===")
verwachte_usdc = executor.quote_hbar_to_usdc(KLEIN_TESTBEDRAG_HBAR)
print(f"Verwacht: {verwachte_usdc:.4f} USDC")

print(f"\n=== Stap 2: daadwerkelijke swap uitvoeren ===")
resultaat = executor.swap_hbar_to_usdc(KLEIN_TESTBEDRAG_HBAR)
print(f"Tx-hash: {resultaat.tx_hash}")
print(f"Resultaat: {resultaat}")
