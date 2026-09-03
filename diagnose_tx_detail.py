"""
diagnose_tx_detail.py

Vraagt de gedetailleerde transactie-record op bij de mirror-node --
geeft een specifiekere Hedera-statuscode (bv. TOKEN_ALREADY_ASSOCIATED,
INSUFFICIENT_GAS, INVALID_TOKEN_ID) dan de kale "success"/"failed" van
een receipt via de JSON-RPC-relay.
"""

import os
import time
import requests

from config import NETWORK_SETTINGS


def main():
    tx_hash = os.environ.get("TX_HASH_TO_CHECK")
    if not tx_hash:
        tx_hash = input("Transactiehash: ").strip()

    settings = NETWORK_SETTINGS["testnet"]
    url = f"{settings['mirror_node_url']}/api/v1/contracts/results/{tx_hash}"

    print(f"Opvragen bij: {url}")
    for attempt in range(5):
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            break
        time.sleep(2)
    else:
        print(f"Kon geen detail vinden na 5 pogingen (laatste status: {response.status_code})")
        return

    data = response.json()
    print(f"\nStatus: {data.get('status')}")
    print(f"Result: {data.get('result')}")
    print(f"Error message: {data.get('error_message')}")
    print(f"Gas used: {data.get('gas_used')}")
    print(f"Gas limit: {data.get('gas_limit')}")


if __name__ == "__main__":
    main()
