"""
rss_news_client.py

Vervangt cryptopanic_client.py als primaire nieuwsbron. Reden: CryptoPanic
heeft (1) geen bruikbare gratis tier meer (goedkoopste betaald plan
~$179-199/maand), en (2) blokkeert verkeer vanaf VPS/datacenter-IP's via
Cloudflare, ongeacht of de token geldig is (bevestigd 22 aug 2026).

RSS-feeds van gevestigde nieuwssites zijn gratis en zitten zelden achter
dit soort bot-bescherming. Nadeel t.o.v. CryptoPanic: geen ingebouwde
community-votes/importance-vlaggen -- puur de ruwe headline + samenvatting,
die we vervolgens aan llm_sentiment_engine.py voeren voor de eigenlijke
sentiment-beoordeling (wat toch al de primaire methode was, CryptoPanic's
votes waren aanvullend).
"""

import time
import hashlib
import re


# RUISFILTER (10 sep 2026, op verzoek): de Google-News-feed voor HBAR trekt
# clickbait en promo mee -- "Price Prediction: ... $0.11?", YouTube-titels,
# presale-advertenties ("$60K+ Raised ... Ignites Demand") -- en de LLM
# scoort promotionele tekst positief. Zulke koppen zeggen niets over de
# markt; ze worden hier weggefilterd VOORDAT ze de LLM bereiken. Patronen
# op kleine letters van titel en link. Bewust conservatief: liever een
# enkele promo doorlaten dan echt nieuws blokkeren.
NOISE_TITLE_PATTERNS = (
    r"\bprice prediction\b", r"\bprice forecast\b", r"\bpredictions?\b.*\b20\d\d\b",
    r"\bpresale\b", r"\bpre-sale\b", r"\btokens? sold\b",
    r"\bignites demand\b", r"\bnext 100x\b", r"\b\d+x\b.*\bgains?\b",
    r"\bbest (crypto|coins?|altcoins?) to buy\b", r"\btop \d+ (crypto|coins?|altcoins?)\b",
    r"\bwhale alert\b", r"\bgiveaway\b", r"\bairdrop\b.*\bclaim\b",
    r"- youtube$", r"\byoutube\b",
)
NOISE_LINK_PATTERNS = (
    r"youtube\.com", r"youtu\.be", r"medium\.com", r"prnewswire\.com", r"globenewswire\.com",
    r"accesswire\.com", r"newsbtc\.com/(?:news/)?press", r"/sponsored/", r"/press-release",
)
_NOISE_TITLE_RE = re.compile("|".join(NOISE_TITLE_PATTERNS))
_NOISE_LINK_RE = re.compile("|".join(NOISE_LINK_PATTERNS))


def is_noise_headline(title: str, link: str = "") -> str | None:
    """Reden (string) als de kop ruis is, anders None."""
    t = (title or "").lower()
    m = _NOISE_TITLE_RE.search(t)
    if m:
        return f"titel: '{m.group(0)}'"
    m = _NOISE_LINK_RE.search((link or "").lower())
    if m:
        return f"bron: '{m.group(0)}'"
    return None


def normalize_headline(title: str) -> str:
    """
    NIEUW (10 sep 2026): sleutel voor ontdubbeling over bronnen en
    herstarts heen. Kleine letters, bron-suffix ("... - CoinDesk") weg,
    alleen letters/cijfers, enkele spaties. "majors' losses" en
    "majors losses" worden zo dezelfde sleutel.
    """
    t = (title or "").lower()
    t = re.sub(r"\s+[-|–—]\s+[a-z0-9 .&']{2,30}$", "", t)  # " - CoinDesk", " | The Block"
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()
import feedparser
from dataclasses import dataclass
from typing import List, Optional


# Bekende, betrouwbare crypto-nieuwsfeeds. Geen enkele vereist een API-key.
RSS_FEEDS_BY_ASSET = {
    "BTC": [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss/tag/bitcoin",
    ],
    "HBAR": [
        "https://cointelegraph.com/rss/tag/hedera-hashgraph",
        # Hedera-specifiek nieuws is dunner gezaaid dan BTC -- de algemene
        # crypto-feed hieronder vangt bredere Hedera-vermeldingen op die
        # niet altijd apart getagd zijn.
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        # Google News RSS -- werkt op elk zoekwoord, geen afhankelijkheid
        # van de exacte tag-URL-structuur van een specifieke nieuwssite.
        "https://news.google.com/rss/search?q=hedera+hbar+when:7d&hl=en-US&gl=US&ceid=US:en",
    ],
    # ALGEMEEN/MACRO-NIEUWS (10 sep 2026, op verzoek): Fed, Treasury
    # (Bessent), tarieven, geopolitiek (Iran, sancties, olie), recessie.
    # Voedt ALLEEN news_events (classificatie + event-study), geen
    # richtingsscore -- het gaat over de hele markt, niet over HBAR.
    # Alle bronnen keyloos. Google-News-query's zijn bewust smal: algemeen
    # nieuws is honderden koppen per dag, alleen het marktrelevante deel
    # mag door.
    "MACRO": [
        "https://feeds.apnews.com/rss/apf-business",
        "https://feeds.apnews.com/rss/apf-topnews",
        "https://www.cnbc.com/id/10000664/device/rss/rss.html",   # CNBC Economy
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",  # CNBC Top News
        "https://feeds.bbci.co.uk/news/business/rss.xml",
        "https://news.google.com/rss/search?q=(Federal+Reserve+OR+Powell+OR+FOMC)+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=(Bessent+OR+Treasury+Secretary)+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=(tariffs+OR+trade+war)+markets+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=(Iran+OR+Israel+OR+Russia+OR+Taiwan)+(strike+OR+attack+OR+sanctions+OR+war)+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=(oil+prices+OR+recession+OR+inflation+data)+when:1d&hl=en-US&gl=US&ceid=US:en",
    ],
}

# Simpele keyword-filter voor de bredere feeds, om te voorkomen dat elk
# BTC-artikel per ongeluk als "HBAR-nieuws" wordt meegeteld als het toevallig
# via dezelfde algemene feed binnenkomt.
ASSET_KEYWORDS = {
    "BTC": ["bitcoin", "btc"],
    "HBAR": ["hedera", "hbar", "hashgraph"],
    # MACRO: trefwoordpoort -- zonder minstens één van deze woorden is een
    # algemene kop (sport, entertainment, lokaal) niet marktrelevant.
    "MACRO": ["fed ", "federal reserve", "powell", "fomc", "rate cut", "rate hike", "interest rate",
              "bessent", "treasury", "tariff", "trade war", "sanction", "iran", "israel", "russia",
              "ukraine", "taiwan", "china", " oil ", "crude", "opec", "inflation", "cpi", "jobs report",
              "payrolls", "recession", "gdp", "stock market", "wall street", "s&p", "nasdaq",
              "dollar", " bond", "yield", "debt ceiling", "shutdown", "trump", "white house",
              "sec ", "regulat", "crypto", "bitcoin", "stablecoin"],
}

# Automatisch gegenereerde valuta-omreken-pagina's (bv. van Bybit) bevatten
# toevallig "HBAR" of "BTC" maar zijn geen nieuws -- expliciet uitsluiten.
JUNK_TITLE_PATTERNS = [
    "convert ",  # "Convert 10 HBAR to OMR - Bybit" e.d.
]


def _is_junk_title(title: str) -> bool:
    lowered = title.lower()
    return any(lowered.startswith(pattern) for pattern in JUNK_TITLE_PATTERNS)


@dataclass
class RssNewsItem:
    id: str            # deterministisch gegenereerd uit de URL (RSS heeft geen stabiele id zoals CryptoPanic)
    title: str
    summary: str
    published_at: float  # unix timestamp
    url: str
    source_feed: str


class RssNewsClient:
    def __init__(self, feeds_by_asset: Optional[dict] = None):
        self.feeds_by_asset = feeds_by_asset or RSS_FEEDS_BY_ASSET

    def fetch_news(self, asset: str, max_age_hours: float = 24.0) -> List[RssNewsItem]:
        """
        Haalt recent nieuws op voor een asset (BTC of HBAR) uit de
        bijbehorende RSS-feeds, gefilterd op keyword-relevantie en leeftijd.
        """
        feeds = self.feeds_by_asset.get(asset, [])
        keywords = [k.lower() for k in ASSET_KEYWORDS.get(asset, [])]
        cutoff = time.time() - max_age_hours * 3600

        items: List[RssNewsItem] = []
        seen_ids = set()

        for feed_url in feeds:
            parsed = feedparser.parse(feed_url)

            for entry in parsed.entries:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                link = entry.get("link", "")

                # Keyword-relevantiefilter (nodig voor de bredere feeds
                # die niet asset-specifiek getagd zijn)
                combined_text = f"{title} {summary}".lower()
                if not any(kw in combined_text for kw in keywords):
                    continue
                if _is_junk_title(title):
                    continue

                published_ts = self._parse_published(entry)
                # AANVULLENDE FIX (3 sep 2026, na de ontdekking dat CoinDesk's
                # feed GEEN apart, vers updated_parsed-veld biedt --
                # published_parsed en updated_parsed bleken identiek):
                # "Live updates"-artikelen behouden hun bevroren, oorspronkelijke
                # tijdstempel terwijl de INHOUD gedurende de dag evolueert.
                # Voor dit specifieke, herkenbare patroon hanteren we een
                # ruimer tijdvenster (24u i.p.v. het normale max_age_hours,
                # meestal 4u) -- AANNAME, geen empirisch geijkte waarde --
                # zodat zo'n artikel niet voortijdig uit de boot valt puur
                # omdat het "publicatietijdstip" verouderd oogt.
                is_live_updates_artikel = title.lower().startswith("live updates")
                effectieve_cutoff = (
                    time.time() - 24 * 3600 if is_live_updates_artikel else cutoff
                )
                if published_ts < effectieve_cutoff:
                    continue

                # BUGFIX (3 sep 2026, gevonden na een gemist, marktbewegend
                # BTC-artikel): het ID was voorheen PUUR op de URL gebaseerd
                # -- "Live updates"-artikelen (precies het type dat grote
                # gebeurtenissen zoals een Fed-aankondiging dekt) behouden
                # vaak dezelfde URL terwijl de kop gedurende de dag
                # ingrijpend verandert. Zodra zo'n artikel EENMAAL is
                # verwerkt (met een vroege, mildere kop), werd elke latere,
                # drastisch bijgewerkte versie van DEZELFDE URL stilzwijgend
                # genegeerd -- de kop wordt nu meegenomen in het ID, zodat
                # een gewijzigde kop op dezelfde URL als NIEUW item geldt.
                item_id = hashlib.sha256(f"{link}|{title}".encode()).hexdigest()[:16]
                if item_id in seen_ids:
                    continue  # zelfde artikel via meerdere feeds
                seen_ids.add(item_id)

                ruis = is_noise_headline(title, link)
                if ruis:
                    print(f"[nieuws] {asset}: ruis overgeslagen ({ruis}): {title[:80]}")
                    continue

                items.append(RssNewsItem(
                    id=item_id, title=title, summary=summary,
                    published_at=published_ts, url=link, source_feed=feed_url,
                ))

        items.sort(key=lambda x: x.published_at, reverse=True)
        return items

    @staticmethod
    def _parse_published(entry) -> float:
        # feedparser geeft published_parsed/updated_parsed als
        # time.struct_time terug.
        #
        # BUGFIX (3 sep 2026, tweede, subtielere laag van dezelfde
        # "live updates"-bug hierboven): updated_parsed wordt nu EERST
        # geprobeerd, published_parsed als terugval -- niet andersom.
        # Een doorlopend-bijgewerkt artikel (bv. "Live updates: Bitcoin
        # jumps above $81,000...") behoudt zijn oorspronkelijke
        # published_parsed-tijdstip terwijl de INHOUD gedurende de dag
        # verandert -- daardoor kon zo'n artikel, ook na de ID-fix
        # hierboven, alsnog buiten het max_age_hours-tijdvenster vallen
        # en genegeerd worden, puur omdat het "publicatietijdstip"
        # verouderd leek terwijl de inhoud actueel was. updated_parsed
        # representeert (per RSS/Atom-specificatie) specifiek de laatste
        # WIJZIGING van een item, en is dus de correctere maatstaf voor
        # "hoe actueel is wat we nu zien" -- voor de meeste, niet-
        # doorlopend-bijgewerkte artikelen (die geen updated_parsed
        # hebben) verandert dit niets, die vallen gewoon terug op
        # published_parsed zoals voorheen.
        parsed_time = entry.get("updated_parsed") or entry.get("published_parsed")
        if parsed_time:
            return time.mktime(parsed_time)
        return time.time()  # fallback als de feed geen datum meegeeft


if __name__ == "__main__":
    client = RssNewsClient()

    for asset in ("BTC", "HBAR"):
        print(f"\n--- {asset} ---")
        try:
            items = client.fetch_news(asset, max_age_hours=48)
            print(f"{len(items)} relevante items gevonden (laatste 48u)")
            for item in items[:3]:
                print(f"  - {item.title[:80]}")
        except Exception as e:
            print(f"Fout bij ophalen: {e}")
