"""
verify_v2_decimals_test.py

Snelle, kosteloze verificatie: klopt de decimalen-aanname in
swap_executor_v2.py voor HBAR-bedragen (18 decimalen via to_wei("ether"))?

quote_hbar_to_usdc() is een read-only call -- geen kosten, geen risico.

Verwachting: 1 HBAR bij een prijs van ~$0.078/HBAR moet een quote van
ongeveer 0.078 USDC teruggeven. Als de uitkomst in de orde van 10^10 te
groot of te klein is, klopt de decimalen-aanname NIET (zie de discussie
in PLAN.md, code-verificatieronde 2).
"""

import os

from swap_executor_v2 import SwapExecutorV2, build_swap_config_v2
from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS


def main():
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    if not private_key:
        print("Geen HEDERA_BOT_PRIVATE_KEY gezet -- kan geen RPC-client opbouwen.")
        return

    settings = NETWORK_SETTINGS["testnet"]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, private_key)

    config = build_swap_config_v2("testnet")
    executor = SwapExecutorV2(client, config)

    try:
        quote = executor.quote_hbar_to_usdc(1.0)
        print(f"Quote voor 1 HBAR: {quote} USDC")
        print("Verwacht: ergens rond 0.01-0.20 USDC (bij de huidige testnet-prijs)")

        if quote > 1000 or (0 < quote < 0.0000001):
            print("\nWAARSCHUWING: dit getal wijkt extreem af van het verwachte "
                  "bereik -- de decimalen-aanname in swap_executor_v2.py klopt "
                  "vermoedelijk NIET. Niet gebruiken voor een echte swap voordat "
                  "dit is uitgezocht.")
        else:
            print("\nGetal ligt in een plausibel bereik -- geen directe aanwijzing "
                  "voor een decimalen-fout (maar dit is geen 100%-garantie, alleen "
                  "een sanity-check).")
    except Exception as e:
        print(f"Fout bij het ophalen van de quote: {e}")
        print("Dit kan ook op een ander probleem wijzen (bv. verkeerde fee-tier, "
              "geen liquiditeit in de pool) -- niet per se de decimalen-kwestie.")


if __name__ == "__main__":
    main()
