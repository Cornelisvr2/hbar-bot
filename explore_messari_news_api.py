import requests
import os
import json

api_key = os.environ.get("MESSARI_API_KEY")
headers = {"X-Messari-API-Key": api_key}

print("=== Stap 1: assets opvragen, zoeken naar bitcoin/hedera ===")
resp = requests.get(
    "https://api.messari.io/news/v1/news/assets",
    headers=headers,
    params={"limit": 100},
    timeout=10,
)
print(f"Statuscode: {resp.status_code}")
data = resp.json()
assets = data.get("data", [])
print(f"Aantal assets in deze pagina: {len(assets)}")

for asset in assets:
    name_lower = str(asset).lower()
    if "bitcoin" in name_lower or "hedera" in name_lower:
        print(json.dumps(asset, indent=2))

if assets:
    print("\nVoorbeeld van EEN asset-object (structuur):")
    print(json.dumps(assets[0], indent=2))

print("\n=== Stap 2: nieuwsfeed opvragen (zonder assetIds-filter, gewoon recent nieuws) ===")
resp2 = requests.get(
    "https://api.messari.io/news/v1/news/feed",
    headers=headers,
    params={"limit": 3},
    timeout=10,
)
print(f"Statuscode: {resp2.status_code}")
data2 = resp2.json()
print(json.dumps(data2, indent=2)[:3000])
