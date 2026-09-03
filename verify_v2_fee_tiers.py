"""
verify_v2_fee_tiers.py

Probeert quote_hbar_to_usdc() met verschillende fee-tiers, om te
onderscheiden of een revert komt door (a) de verkeerde/aangenomen
fee-tier (3000), of (b) iets anders zoals een decimalen-probleem.

Als GEEN ENKELE fee-tier werkt, wijst dat sterker op een dieperliggend
probleem (decimalen, adressen) dan op simpelweg de verkeerde tier.
Als EEN tier wel werkt, was de eerdere revert puur de fee-tier-aanname.
"""

import os

from swap_executor_v2 import SwapExecutorV2, build_swap_config_v2
from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS


def main():
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    if not private_key:
        print("Geen HEDERA_BOT_PRIVATE_KEY gezet.")
        return

    settings = NETWORK_SETTINGS["testnet"]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, private_key)

    fee_tiers = [500, 1500, 3000, 10000]  # gecorrigeerd 23 aug 2026 o.b.v. officiele docs
    any_success = False

    for fee_tier in fee_tiers:
        config = build_swap_config_v2("testnet", fee_tier=fee_tier)
        executor = SwapExecutorV2(client, config)
        try:
            quote = executor.quote_hbar_to_usdc(1.0)
            print(f"Fee-tier {fee_tier}: SUCCES -- quote = {quote} USDC")
            any_success = True
        except Exception as e:
            error_msg = str(e)[:100]
            print(f"Fee-tier {fee_tier}: FOUT -- {error_msg}")

    print()
    if any_success:
        print("Minstens 1 fee-tier werkt -- de eerdere revert was vermoedelijk "
              "puur de verkeerde fee-tier-aanname, geen decimalen-probleem.")
    else:
        print("GEEN ENKELE fee-tier werkt -- dit wijst op een dieperliggend "
              "probleem (decimalen, adressen, of geen liquiditeit in welke "
              "pool dan ook op testnet voor dit paar).")


if __name__ == "__main__":
    main()
