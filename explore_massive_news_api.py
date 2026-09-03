"""
Verkennend testscript: probeert Massive's meest waarschijnlijke
nieuws-endpoint (gebaseerd op hun gedocumenteerde patroon, vergelijkbaar
met Polygon.io's structuur) en toont de RUWE respons, zodat we de
daadwerkelijke structuur kunnen bevestigen voordat we de echte client
bouwen.
"""

import requests
import os
import json

api_key = os.environ.get("MASSIVE_API_KEY")
if not api_key:
    print("MASSIVE_API_KEY niet gevonden in de omgeving.")
    exit(1)

# Meest waarschijnlijke endpoint, gebaseerd op het "reference"-patroon
# dat de documentatie toont (v3/reference/dividends als voorbeeld) en
# Polygon.io's bekende structuur (v2/reference/news).
candidate_urls = [
    f"https://api.massive.com/v2/reference/news?ticker=BTC&limit=5&apiKey={api_key}",
    f"https://api.massive.com/v3/reference/news?ticker=BTC&limit=5&apiKey={api_key}",
]

for url in candidate_urls:
    print(f"\n=== Proberen: {url.replace(api_key, 'API_KEY')} ===")
    try:
        resp = requests.get(url, timeout=10)
        print(f"Statuscode: {resp.status_code}")
        try:
            data = resp.json()
            print(json.dumps(data, indent=2)[:2000])
        except ValueError:
            print(f"Geen JSON-respons: {resp.text[:500]}")
    except Exception as e:
        print(f"Fout: {e}")
