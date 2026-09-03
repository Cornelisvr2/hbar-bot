import feedparser

feeds = {
    "CoinTelegraph Hedera-tag": "https://cointelegraph.com/rss/tag/hedera-hashgraph",
    "CoinDesk algemeen": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Google News (hedera hbar)": "https://news.google.com/rss/search?q=hedera+hbar+when:7d&hl=en-US&gl=US&ceid=US:en",
}

for naam, url in feeds.items():
    print(f"\n=== {naam} ===")
    parsed = feedparser.parse(url)
    print(f"Status: {parsed.get('status', 'onbekend')}, aantal items: {len(parsed.entries)}")
    if parsed.bozo:
        print(f"WAARSCHUWING (bozo -- parseerfout): {parsed.bozo_exception}")
    for entry in parsed.entries[:3]:
        print(f"  - {entry.get('title', '(geen titel)')[:80]}")
