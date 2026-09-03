import requests

tx_hash = "0xe90048b08103f08873ce634386d91a52925b421b6c5deebc5c81021fa8e1981a"
resp = requests.get(f"https://testnet.mirrornode.hedera.com/api/v1/contracts/results/{tx_hash}")
data = resp.json()

print(f"Status: {data.get('status')}")
print(f"Amount (msg.value, in tinybar): {data.get('amount')}")
print(f"Gas gebruikt: {data.get('gas_used')}")
print(f"Result: {data.get('result')}")
