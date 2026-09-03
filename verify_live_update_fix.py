import feedparser
import datetime
from rss_news_client import RssNewsClient

url = "https://www.coindesk.com/arc/outboundfeeds/rss/"
parsed = feedparser.parse(url)

for entry in parsed.entries:
    if "live updates" in entry.get("title", "").lower() and "jump" in entry.get("title", "").lower():
        print(f"Titel: {entry.title}")
        print(f"published_parsed: {entry.get('published_parsed')}")
        print(f"updated_parsed: {entry.get('updated_parsed')}")
        ts = RssNewsClient._parse_published(entry)
        tijd = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        print(f"Door onze functie bepaalde tijd: {tijd.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        break
else:
    print("Dat specifieke artikel staat nu niet meer in de live feed (verwacht, het is uren geleden) -- "
          "toon in plaats daarvan het eerste artikel als voorbeeld:")
    entry = parsed.entries[0]
    print(f"Titel: {entry.title}")
    print(f"published_parsed: {entry.get('published_parsed')}")
    print(f"updated_parsed: {entry.get('updated_parsed')}")
