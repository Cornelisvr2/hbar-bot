import feedparser

url = "https://cointelegraph.com/rss/tag/bitcoin"
print(f"=== CoinTelegraph, Bitcoin-tag ===")
parsed = feedparser.parse(url)
print(f"Status: {parsed.get('status', 'onbekend')}, aantal items: {len(parsed.entries)}")
if parsed.bozo:
    print(f"WAARSCHUWING (bozo -- parseerfout): {parsed.bozo_exception}")
for entry in parsed.entries[:5]:
    print(f"  - {entry.get('title', '(geen titel)')[:80]}")
