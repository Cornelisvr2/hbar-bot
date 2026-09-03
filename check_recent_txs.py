import requests
import os

account_id = "0.0.10194038"  # bot-account
resp = requests.get(
    f"https://testnet.mirrornode.hedera.com/api/v1/accounts/{account_id}",
    params={"limit": 1}
)
data = resp.json()
print(f"Huidige HBAR-balans (mirror node): {data.get('balance', {}).get('balance')} tinybar")

resp2 = requests.get(
    f"https://testnet.mirrornode.hedera.com/api/v1/transactions",
    params={"account.id": account_id, "limit": 10, "order": "desc"}
)
data2 = resp2.json()
print("\nMeest recente 10 transacties:")
for tx in data2.get("transactions", []):
    print(f"  {tx.get('consensus_timestamp')} | {tx.get('name')} | "
          f"resultaat={tx.get('result')} | charged_fee={tx.get('charged_tx_fee')}")
