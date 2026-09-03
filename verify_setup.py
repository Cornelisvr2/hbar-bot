"""
verify_setup.py

Read-only verificatiescript -- verstuurt GEEN transacties, kost geen gas.
Checkt of alles correct is opgezet voordat je een echte swap probeert:

1. RPC-verbinding werkt
2. Bot-account is bereikbaar en toont een HBAR-balance
3. Router's on-chain whbar()-adres komt overeen met onze config
4. Een quote kan worden opgehaald (bewijst dat de pool bestaat en liquide is)

Gebruik:
    export HEDERA_BOT_PRIVATE_KEY="0x..."
    python3 verify_setup.py
"""

import os
import sys

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from swap_executor import SwapExecutor, build_swap_config
from config import HEDERA_NETWORK, NETWORK_SETTINGS


def main():
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    if not private_key:
        print("FOUT: zet HEDERA_BOT_PRIVATE_KEY als environment variable.")
        sys.exit(1)

    settings = NETWORK_SETTINGS[HEDERA_NETWORK]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])

    print(f"=== Verificatie op {HEDERA_NETWORK} ===\n")

    # 1. Verbinding
    client = HederaRpcClient(network, private_key)
    connected = client.is_connected()
    print(f"[1/4] RPC-verbinding: {'OK' if connected else 'MISLUKT'}")
    if not connected:
        sys.exit(1)

    # 2. Account & balance
    print(f"[2/4] Bot-adres: {client.address}")
    try:
        balance = client.get_hbar_balance()
        print(f"      HBAR-balance: {balance}")
        if balance == 0:
            print("      WAARSCHUWING: 0 HBAR -- haal eerst testnet-HBAR op via de Hedera Portal faucet.")
    except Exception as e:
        print(f"      FOUT bij ophalen balance: {e}")
        sys.exit(1)

    # 3. WHBAR-adres verifiëren tegen de Router zelf
    config = build_swap_config(HEDERA_NETWORK)
    executor = SwapExecutor(client, config)
    try:
        whbar_ok = executor.verify_whbar_address()
        print(f"[3/4] WHBAR-adres komt overeen met Router: {'OK' if whbar_ok else 'MISMATCH -- STOP'}")
        if not whbar_ok:
            sys.exit(1)
    except Exception as e:
        print(f"[3/4] FOUT bij WHBAR-verificatie: {e}")
        sys.exit(1)

    # 4. Quote ophalen (bewijst dat de pool bestaat en liquide is)
    try:
        quote = executor.quote_hbar_to_usdc(1.0)
        print(f"[4/4] Quote voor 1 HBAR -> USDC: {quote:.6f} USDC")
        print("\nAlles OK. Config is correct en de pool is bereikbaar.")
    except Exception as e:
        print(f"[4/4] FOUT bij ophalen quote: {e}")
        print("      Mogelijke oorzaken: geen liquiditeit in deze testnet-pool,")
        print("      of het pad HBAR->USDC bestaat niet als directe pair.")
        sys.exit(1)


if __name__ == "__main__":
    main()
