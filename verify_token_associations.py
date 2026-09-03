"""
verify_token_associations.py

Controleert via de mirror-node REST API (geen RPC-call nodig) welke van
de vereiste tokens al geassocieerd zijn met het bot-account. Bijgewerkte
lijst uit de documentatie-ronde van 23 aug 2026:

1. WHBAR (bevestigd verplicht: TOKEN_NOT_ASSOCIATED_TO_ACCOUNT zonder dit)
2. SAUCE (de bevestigde, daadwerkelijk liquide testnet-pool-partner --
   vervangt USDC, dat geen testnet-liquiditeit bleek te hebben)
3. SaucerSwapV2 LP-NFT-token (nodig voor elke mint())

Het bot-account wordt via zijn EVM-adres opgezocht bij de mirror-node.
"""

import os
import requests

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS


REQUIRED_TOKENS_TESTNET = {
    "WHBAR": "0.0.15058",
    "SAUCE": "0.0.1183558",
    "LP-NFT (SaucerSwapV2)": "0.0.1310436",
}

REQUIRED_TOKENS_MAINNET = {
    "WHBAR": "0.0.1456986",
    "SAUCE": "0.0.731861",
    "LP-NFT (SaucerSwapV2)": "0.0.4054027",
}


def main():
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    network_name = os.environ.get("HEDERA_NETWORK", "testnet")
    if not private_key:
        print("Geen HEDERA_BOT_PRIVATE_KEY gezet.")
        return

    settings = NETWORK_SETTINGS[network_name]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, private_key)

    print(f"Netwerk: {network_name}")
    print(f"Bot EVM-adres: {client.address}")

    account_url = f"{settings['mirror_node_url']}/api/v1/accounts/{client.address}"
    response = requests.get(account_url, timeout=10)
    if response.status_code != 200:
        print(f"Kon account niet vinden bij de mirror-node (status {response.status_code}). "
              f"Bestaat dit account al on-chain? Heeft het al een keer een transactie gedaan?")
        return

    account_data = response.json()
    hedera_account_id = account_data.get("account")
    print(f"Bot Hedera-account-ID: {hedera_account_id}")

    tokens_url = f"{settings['mirror_node_url']}/api/v1/accounts/{hedera_account_id}/tokens"
    tokens_response = requests.get(tokens_url, timeout=10)
    tokens_response.raise_for_status()
    associated_token_ids = {t["token_id"] for t in tokens_response.json().get("tokens", [])}

    print(f"\n{len(associated_token_ids)} tokens momenteel geassocieerd met dit account.\n")

    required = REQUIRED_TOKENS_TESTNET if network_name == "testnet" else REQUIRED_TOKENS_MAINNET
    all_associated = True

    for label, token_id in required.items():
        is_associated = token_id in associated_token_ids
        status = "OK -- geassocieerd" if is_associated else "ONTBREEKT -- moet nog geassocieerd worden"
        print(f"  {label} ({token_id}): {status}")
        if not is_associated:
            all_associated = False

    print()
    if all_associated:
        print("Alle vereiste tokens zijn geassocieerd -- dit blokkeert een live-gang niet meer.")
    else:
        print("Niet alle vereiste tokens zijn geassocieerd. Gebruik de Hedera SDK's "
              "TokenAssociateTransaction (of een wallet als HashPack) om de "
              "ontbrekende tokens te associeren voordat je uit DRY_RUN gaat.")


if __name__ == "__main__":
    main()
