from swap_executor_v2 import build_swap_config_v2, SwapExecutorV2
from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, HEDERA_NETWORK
import os

KLEIN_TESTBEDRAG_HBAR = 300.0
BEVESTIGDE_PRIJS = 0.077361  # zonet rechtstreeks geverifieerd via get_live_pool_price()
SLIPPAGE = 0.02  # 2%

settings = NETWORK_SETTINGS[HEDERA_NETWORK]
network_config = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
rpc_client = HederaRpcClient(network_config, os.environ["HEDERA_BOT_PRIVATE_KEY"])

fee_tier = int(os.environ.get("LP_FEE_TIER", "3000"))
config = build_swap_config_v2(HEDERA_NETWORK, fee_tier=fee_tier)
executor = SwapExecutorV2(rpc_client, config)

# Handmatige swap, ZONDER de probleemquote-aanroep -- min_out direct
# berekend op basis van de al-bevestigde prijs plus slippage-marge.
verwachte_usdc = KLEIN_TESTBEDRAG_HBAR * BEVESTIGDE_PRIJS
min_out_raw = int(verwachte_usdc * (1 - SLIPPAGE) * (10 ** config.usdc_decimals))
amount_in_8dec = int(KLEIN_TESTBEDRAG_HBAR * (10 ** 8))
amount_in_wei_for_msg_value = rpc_client.w3.to_wei(KLEIN_TESTBEDRAG_HBAR, "ether")

print(f"Verwacht: {verwachte_usdc:.4f} USDC, min_out (met {SLIPPAGE*100:.0f}% marge): "
      f"{min_out_raw/(10**config.usdc_decimals):.4f} USDC")

params = (
    config.whbar_address, config.usdc_address, config.fee_tier,
    rpc_client.address, executor._deadline(),
    amount_in_8dec, min_out_raw, 0,
)
swap_fn = executor.router.functions.exactInputSingle(params)

try:
    tx_hash = rpc_client.build_and_send_transaction(swap_fn, value_wei=amount_in_wei_for_msg_value)
    print(f"Tx-hash: {tx_hash}")
    receipt = rpc_client.wait_for_receipt(tx_hash)
    print(f"Status: {receipt['status']}")
except Exception as e:
    print(f"FOUT: {type(e).__name__}: {e}")
