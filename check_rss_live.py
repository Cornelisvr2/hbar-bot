from rss_news_client import RssNewsClient
import datetime

def main():
    client = RssNewsClient()
    for asset in ["BTC", "HBAR"]:
        print(f"\n=== {asset}: alle items binnen 24 uur (ongefilterd op 'al verwerkt') ===")
        items = client.fetch_news(asset, max_age_hours=24.0)
        print(f"Aantal gevonden items: {len(items)}")
        for i in sorted(items, key=lambda x: x.published_at, reverse=True)[:15]:
            tijd = datetime.datetime.fromtimestamp(i.published_at, tz=datetime.timezone.utc)
            print(f"{tijd.strftime('%Y-%m-%d %H:%M')} UTC | id={i.id[:20]}... | {i.title[:70]}")

main()
