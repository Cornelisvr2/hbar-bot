from config import NETWORK_SETTINGS
import requests
import os
from web3 import Web3

SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
ONS_TESTNET_POOL_CONTRACT_ID = "0.0.2661057"
mirror_node_url = NETWORK_SETTINGS[os.environ.get("HEDERA_NETWORK", "testnet")]["mirror_node_url"]

alle_swap_logs = []
volgende_url = f"{mirror_node_url}/api/v1/contracts/{ONS_TESTNET_POOL_CONTRACT_ID}/results/logs?order=desc&limit=100"
pagina_teller = 0

import datetime
grens = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)

while volgende_url and pagina_teller < 20:
    resp = requests.get(volgende_url, timeout=15)
    data = resp.json()
    logs = data.get("logs", [])
    if not logs:
        break

    gestopt = False
    for log in logs:
        tijd = datetime.datetime.fromtimestamp(float(log["timestamp"]), tz=datetime.timezone.utc)
        if tijd < grens:
            gestopt = True
            break
        if log.get("topics") and log["topics"][0] == SWAP_TOPIC:
            alle_swap_logs.append(log)

    if gestopt:
        break

    volgende_link = data.get("links", {}).get("next")
    volgende_url = f"{mirror_node_url}{volgende_link}" if volgende_link else None
    pagina_teller += 1

print(f"Aantal Swap-events in de laatste 24 uur: {len(alle_swap_logs)}")

# amount0/amount1 uit de data-payload decoderen (int256, int256 -- de eerste
# twee velden na de niet-indexed data, sqrtPriceX96/liquidity/tick negeren we hier)
from eth_abi import decode as abi_decode

totaal_hbar_volume = 0
totaal_sauce_volume = 0
for log in alle_swap_logs:
    data_bytes = bytes.fromhex(log["data"][2:])
    amount0, amount1, sqrt_price_x96, liquidity, tick = abi_decode(
        ["int256", "int256", "uint160", "uint128", "int24"], data_bytes
    )
    totaal_hbar_volume += abs(amount0) / (10 ** 8)
    totaal_sauce_volume += abs(amount1) / (10 ** 6)

print(f"Totaal, daadwerkelijk HBAR-volume (24u): {totaal_hbar_volume:.4f} HBAR")
print(f"Totaal, daadwerkelijk SAUCE-volume (24u): {totaal_sauce_volume:.4f} SAUCE")
