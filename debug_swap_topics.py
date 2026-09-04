from config import NETWORK_SETTINGS
import requests
import os
from web3 import Web3
from collections import Counter

ONS_TESTNET_POOL_CONTRACT_ID = "0.0.2661057"
mirror_node_url = NETWORK_SETTINGS[os.environ.get("HEDERA_NETWORK", "testnet")]["mirror_node_url"]

url = f"{mirror_node_url}/api/v1/contracts/{ONS_TESTNET_POOL_CONTRACT_ID}/results/logs?order=desc&limit=100"
resp = requests.get(url, timeout=15)
data = resp.json()
logs = data.get("logs", [])
print(f"Aantal logs: {len(logs)}")

topics_gezien = Counter()
for log in logs:
    if log.get("topics"):
        topics_gezien[log["topics"][0]] += 1

print("\n=== Alle unieke topics[0]-waarden in deze logs, met aantal ===")
for topic, aantal in topics_gezien.most_common():
    print(f"{aantal:>4}x  {topic}")

w3 = Web3()
print("\n=== Diverse mogelijke Swap-signaturen, ter vergelijking ===")
kandidaten = [
    "Swap(address,address,int256,int256,uint160,uint128,int24)",
    "Swap(address,address,address,uint256,uint256,uint256,uint256)",
    "Swap(address,uint256,uint256,uint256,uint256,address)",
]
for sig in kandidaten:
    print(f"{w3.keccak(text=sig).hex()}  <-  {sig}")
