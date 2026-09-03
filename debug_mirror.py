from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from config import NETWORK_SETTINGS
import asyncio
import requests
import json
import os

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    adres = orchestrator.rpc_client.address
    print(f"Ons EVM-adres: {adres}")

    mirror_node_url = NETWORK_SETTINGS[os.environ.get("HEDERA_NETWORK", "testnet")]["mirror_node_url"]

    # Eerst het EVM-adres omzetten naar het Hedera-eigen 0.0.X-formaat
    resp = requests.get(f"{mirror_node_url}/api/v1/accounts/{adres}", timeout=15)
    print(f"Account-opzoek-statuscode: {resp.status_code}")
    account_data = resp.json()
    hedera_account_id = account_data.get("account")
    print(f"Hedera-eigen account-ID: {hedera_account_id}")

    # Nu de transacties opvragen MET het juiste formaat
    url = f"{mirror_node_url}/api/v1/transactions?account.id={hedera_account_id}&order=desc&limit=5"
    print(f"Aanroep: {url}")
    resp2 = requests.get(url, timeout=15)
    print(f"Statuscode: {resp2.status_code}")
    data = resp2.json()
    print(json.dumps(data, indent=2)[:3000])

    await db.close()

asyncio.run(main())
