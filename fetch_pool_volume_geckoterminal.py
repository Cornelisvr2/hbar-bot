"""
fetch_pool_volume_geckoterminal.py

Haalt het 24u-volume van een pool op via GeckoTerminal's publieke API --
voor gebruik in compute_fees_apr() uit lp_manager.py.

LET OP (26 aug 2026): dit is bedoeld voor MAINNET. GeckoTerminal indexeert
geen testnet-activiteit.

LET OP 2: het exacte GeckoTerminal-API-schema is hier gebaseerd op hun
algemene, gedocumenteerde v2-structuur, maar NIET live geverifieerd
vanuit deze omgeving (geen internettoegang in de sandbox waarin dit is
geschreven). Test dit script eerst op de VPS en controleer de output
voordat je 'm in de bot-loop vertrouwt.
"""

import requests


GECKOTERMINAL_BASE_URL = "https://api.geckoterminal.com/api/v2"
HEDERA_NETWORK_SLUG = "hedera-hashgraph"  # bevestigd via GeckoTerminal's /networks-endpoint (26 aug 2026)


def fetch_pools_for_token(token_address: str) -> list:
    """
    Zoekt alle pools waar een gegeven token in voorkomt -- handig als je
    het exacte pool-adres nog niet weet, alleen het token-adres.

    Geeft een lijst van pools terug met hun adres en (indien beschikbaar)
    volume, zodat je de juiste pool (bv. SAUCE/HBAR) kunt selecteren.
    """
    url = f"{GECKOTERMINAL_BASE_URL}/networks/{HEDERA_NETWORK_SLUG}/tokens/{token_address}/pools"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()

    pools = []
    for entry in data.get("data", []):
        attrs = entry.get("attributes", {})
        pools.append({
            "address": attrs.get("address"),
            "name": attrs.get("name"),
            "volume_24h_usd": attrs.get("volume_usd", {}).get("h24"),
            "reserve_in_usd": attrs.get("reserve_in_usd"),
        })
    return pools


def fetch_pool_volume_24h(pool_address: str) -> float:
    """
    Haalt het 24u-handelsvolume (in USD) op voor een specifieke pool.

    pool_address: het EVM-adres van de pool.

    Geeft het volume in USD terug.
    """
    url = f"{GECKOTERMINAL_BASE_URL}/networks/{HEDERA_NETWORK_SLUG}/pools/{pool_address}"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()

    # Verwacht schema (JSON:API-stijl, NIET live bevestigd):
    # data['data']['attributes']['volume_usd']['h24']
    attributes = data["data"]["attributes"]
    volume_24h_usd = float(attributes["volume_usd"]["h24"])

    return volume_24h_usd


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Gebruik:")
        print("  python3 fetch_pool_volume_geckoterminal.py pool <pool_address>")
        print("  python3 fetch_pool_volume_geckoterminal.py token <token_address>")
        sys.exit(1)

    mode, address = sys.argv[1], sys.argv[2]

    if mode == "token":
        print(f"Pools zoeken voor token {address} op netwerk '{HEDERA_NETWORK_SLUG}'...")
        try:
            pools = fetch_pools_for_token(address)
            if not pools:
                print("Geen pools gevonden.")
            for pool in pools:
                print(f"  {pool['name']}: {pool['address']} "
                      f"(24u-volume: ${pool['volume_24h_usd']}, TVL: ${pool['reserve_in_usd']})")
        except Exception as e:
            print(f"MISLUKT: {e}")
    else:
        print(f"Volume opvragen voor pool {address} op netwerk '{HEDERA_NETWORK_SLUG}'...")
        try:
            volume = fetch_pool_volume_24h(address)
            print(f"24u-volume: ${volume:,.2f}")
        except Exception as e:
            print(f"MISLUKT: {e}")
            print("\nControleer: klopt HEDERA_NETWORK_SLUG? Klopt het pool-adres? "
                  "Is het response-schema nog hetzelfde als hierboven aangenomen?")
