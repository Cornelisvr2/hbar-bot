from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from config import NETWORK_SETTINGS
import asyncio
import requests
import os
import datetime

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    adres = orchestrator.rpc_client.address

    mirror_node_url = NETWORK_SETTINGS[os.environ.get("HEDERA_NETWORK", "testnet")]["mirror_node_url"]
    resp = requests.get(f"{mirror_node_url}/api/v1/accounts/{adres}", timeout=15)
    hedera_account_id = resp.json().get("account")
    print(f"Hedera-account: {hedera_account_id}\n")

    totaal_tinybar = 0
    volgende_url = (
        f"{mirror_node_url}/api/v1/transactions"
        f"?account.id={hedera_account_id}&order=asc&limit=100"
    )
    pagina_teller = 0

    while volgende_url and pagina_teller < 50:
        resp = requests.get(volgende_url, timeout=15)
        data = resp.json()

        for tx in data.get("transactions", []):
            transaction_id = tx.get("transaction_id", "")
            initiator = transaction_id.split("-")[0] if transaction_id else ""
            if initiator == hedera_account_id or initiator == "0.0.7314364":
                continue

            for overdracht in tx.get("transfers", []):
                if overdracht.get("account") == hedera_account_id and overdracht.get("amount", 0) > 0:
                    bedrag_hbar = overdracht["amount"] / (10 ** 8)
                    totaal_tinybar += overdracht["amount"]
                    tijd = datetime.datetime.fromtimestamp(
                        float(tx["consensus_timestamp"]), tz=datetime.timezone.utc
                    )
                    print(f"{tijd.strftime('%Y-%m-%d %H:%M:%S')} UTC | +{bedrag_hbar:>12.4f} HBAR | "
                          f"initiator={initiator} | type={tx.get('name')} | tx_id={transaction_id}")

        volgende_link = data.get("links", {}).get("next")
        volgende_url = f"{mirror_node_url}{volgende_link}" if volgende_link else None
        pagina_teller += 1

    print(f"\nTotaal: {totaal_tinybar / (10**8):.4f} HBAR")
    await db.close()

asyncio.run(main())
