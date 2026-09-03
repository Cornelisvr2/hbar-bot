"""
backtest_pipeline.py

Valideert of onze sentiment-regels (LLM + strategy_engine) historisch
gezien voorspellende waarde hadden -- dit is de "backtesting" die we
eerder bespraken als het juiste alternatief voor "het LLM trainen".

BELANGRIJK ONDERSCHEID met live gebruik:
- Dit verandert het LLM zelf niet (geen fine-tuning, geen gewichten-update)
- Dit valideert/kalibreert onze EIGEN drempelwaarden in strategy_engine.py
  en levert de echte voorbeelden voor de few-shot-context in
  llm_sentiment_engine.py's system-prompt
- Cruciaal: elk nieuwsbericht wordt beoordeeld met ALLEEN de marktdata die
  op dat historische moment al bekend was. Een LLM-call met prijsdata van
  ná het nieuwsbericht zou "toekomstkennis" lekken (lookahead bias) en een
  kunstmatig goede backtest-uitkomst geven die live niet houdbaar is.

Werkwijze:
1. Verzamel historisch nieuws (CryptoPanic heeft een archief-endpoint,
   of exporteer handmatig) + historische prijzen (CoinGecko, tot 1 jaar
   terug gratis)
2. Loop chronologisch door het nieuws, roep de LLM aan alsof het nu is
3. Meet de prijsbeweging N uur na elk nieuwsbericht
4. Vergelijk: had een hoge sentiment-score daadwerkelijk voorspellende
   waarde, of was de markt allang gereageerd voordat het nieuws er was?
"""

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from llm_sentiment_engine import LlmSentimentEngine, LlmSentimentResult


class LookaheadBiasError(Exception):
    """
    Wordt opgegooid als een price_lookup_fn een prijs teruggeeft die te
    ver vóór het publicatiemoment ligt (een te oude/stale candle) --
    dat zou een vals gevoel van precisie geven. Beter een item overslaan
    dan een backtest-resultaat baseren op verouderde data.
    """
    pass


def get_price_strictly_at_or_before(
    asset: str,
    timestamp: datetime,
    price_lookup_fn,
    max_staleness_minutes: int = 5,
) -> Optional[float]:
    """
    DE CRUCIALE FUNCTIE tegen lookahead bias, geinspireerd op de
    get_price_strictly_before-aanpak: zoekt de meest recente candle OP
    of VOOR het publicatiemoment, en verwerpt de prijs expliciet als de
    dichtstbijzijnde beschikbare candle te ver in het verleden ligt
    (max_staleness_minutes) -- bijvoorbeeld bij een gat in de dataset.

    price_lookup_fn moet (timestamp) -> (price, candle_timestamp) | None
    teruggeven -- dus ook het daadwerkelijke tijdstip van de candle,
    niet alleen de prijs, zodat we de staleness kunnen controleren.
    """
    result = price_lookup_fn(asset, timestamp)
    if result is None:
        return None

    price, candle_timestamp = result

    if candle_timestamp > timestamp:
        # Een candle van NA het publicatiemoment mag nooit gebruikt worden
        # als T0-prijs -- dat is lookahead bias in zijn puurste vorm.
        raise LookaheadBiasError(
            f"price_lookup_fn gaf een candle van {candle_timestamp} terug voor "
            f"publicatiemoment {timestamp} -- dit ligt IN DE TOEKOMST t.o.v. het "
            f"nieuwsbericht. Controleer de filter-logica in price_lookup_fn."
        )

    staleness = (timestamp - candle_timestamp).total_seconds() / 60
    if staleness > max_staleness_minutes:
        return None  # te oude data, liever overslaan dan gokken

    return price


@dataclass
class HistoricalNewsItem:
    asset: str
    headline: str
    published_at: datetime
    # Marktdata die op DIT moment al bekend was -- nooit data van later
    price_at_publish: float
    volume_24h_at_publish: Optional[float] = None


@dataclass
class BacktestResult:
    news_item: HistoricalNewsItem
    llm_result: LlmSentimentResult
    price_after_1h: Optional[float]
    price_after_4h: Optional[float]
    price_after_24h: Optional[float]
    return_1h_pct: Optional[float]
    return_4h_pct: Optional[float]
    return_24h_pct: Optional[float]


class BacktestPipeline:
    def __init__(self, sentiment_engine: LlmSentimentEngine):
        self.engine = sentiment_engine

    def run_single(self, news_item: HistoricalNewsItem,
                    price_lookup_fn) -> BacktestResult:
        """
        price_lookup_fn(asset, timestamp) -> float
        Een functie die de historische prijs op een specifiek moment
        teruggeeft (bv. uit een lokaal opgeslagen CoinGecko-dataset).
        Wordt hier als parameter meegegeven i.p.v. hardcoded, zodat deze
        pipeline niet zelf hoeft te weten waar de data vandaan komt.
        """
        price_context = f"Prijs op moment van publicatie: {news_item.price_at_publish:.4f} USDC"
        if news_item.volume_24h_at_publish:
            price_context += f", 24u volume: {news_item.volume_24h_at_publish:.0f}"

        # Dit is de kern van lookahead-bias-preventie: alleen price_context
        # van VOOR of OP het publicatiemoment gaat naar het LLM.
        llm_result = self.engine.analyze_headline(
            asset=news_item.asset,
            headline=news_item.headline,
            price_context=price_context,
        )

        price_1h = price_lookup_fn(news_item.asset, news_item.published_at + timedelta(hours=1))
        price_4h = price_lookup_fn(news_item.asset, news_item.published_at + timedelta(hours=4))
        price_24h = price_lookup_fn(news_item.asset, news_item.published_at + timedelta(hours=24))

        def pct_return(later_price):
            if later_price is None:
                return None
            return round((later_price - news_item.price_at_publish) / news_item.price_at_publish * 100, 3)

        return BacktestResult(
            news_item=news_item,
            llm_result=llm_result,
            price_after_1h=price_1h,
            price_after_4h=price_4h,
            price_after_24h=price_24h,
            return_1h_pct=pct_return(price_1h),
            return_4h_pct=pct_return(price_4h),
            return_24h_pct=pct_return(price_24h),
        )

    def run_batch(self, news_items: List[HistoricalNewsItem],
                   price_lookup_fn, delay_seconds: float = 0.5) -> List[BacktestResult]:
        """
        delay_seconds: pauze tussen LLM-calls om rate limits te respecteren.
        Bij honderden historische items over te draaien: overweeg dit te
        asynchroniseren, maar voor een eerste validatie is sequentieel
        prima -- dit hoeft niet snel te zijn, het draait offline.
        """
        results = []
        for item in news_items:
            result = self.run_single(item, price_lookup_fn)
            results.append(result)
            time.sleep(delay_seconds)
        return results

    @staticmethod
    def evaluate_predictive_value(results: List[BacktestResult],
                                    score_threshold: float = 0.5,
                                    horizon: str = "4h") -> dict:
        """
        De kernvraag: had een sentiment-score boven de drempel
        daadwerkelijk gemiddeld een positief rendement tot gevolg?
        Zo niet -- dan heeft dit signaal geen aantoonbare voorspellende
        waarde en moet de drempel (of het hele idee) heroverwogen worden.
        """
        return_field = f"return_{horizon}_pct"

        high_sentiment_returns = [
            getattr(r, return_field) for r in results
            if r.llm_result.sentiment_score >= score_threshold
            and getattr(r, return_field) is not None
        ]
        low_sentiment_returns = [
            getattr(r, return_field) for r in results
            if r.llm_result.sentiment_score <= -score_threshold
            and getattr(r, return_field) is not None
        ]
        neutral_returns = [
            getattr(r, return_field) for r in results
            if abs(r.llm_result.sentiment_score) < score_threshold
            and getattr(r, return_field) is not None
        ]

        def avg(lst):
            return round(sum(lst) / len(lst), 3) if lst else None

        return {
            "horizon": horizon,
            "score_threshold": score_threshold,
            "n_high_sentiment": len(high_sentiment_returns),
            "avg_return_after_high_sentiment_pct": avg(high_sentiment_returns),
            "n_low_sentiment": len(low_sentiment_returns),
            "avg_return_after_low_sentiment_pct": avg(low_sentiment_returns),
            "n_neutral": len(neutral_returns),
            "avg_return_after_neutral_pct": avg(neutral_returns),
        }


if __name__ == "__main__":
    # Gesimuleerde demo -- toont de mechaniek zonder live API-calls of
    # echte historische data. In productie vervang je dit door een
    # echte LlmSentimentEngine + een price_lookup_fn die uit een lokaal
    # opgeslagen CoinGecko-dataset leest.

    class FakeSentimentEngine:
        def analyze_headline(self, asset, headline, price_context=None):
            from llm_sentiment_engine import LlmSentimentResult
            # Simpele nep-logica puur om de pipeline-mechaniek te tonen
            score = 0.7 if "partnership" in headline.lower() else -0.1
            return LlmSentimentResult(
                asset=asset, sentiment_score=score, confidence=0.8,
                rationale="demo", is_idiosyncratic=True, headline=headline,
            )

    fake_prices = {
        0: 0.065, 1: 0.068, 4: 0.071, 24: 0.069,
    }

    def fake_price_lookup(asset, timestamp):
        hours_offset = int((timestamp - base_time).total_seconds() / 3600)
        return fake_prices.get(hours_offset)

    base_time = datetime(2026, 1, 1, 12, 0)
    news_items = [
        HistoricalNewsItem(
            asset="HBAR", headline="Hedera announces new enterprise partnership",
            published_at=base_time, price_at_publish=0.065,
        ),
    ]

    pipeline = BacktestPipeline(FakeSentimentEngine())
    results = pipeline.run_batch(news_items, fake_price_lookup, delay_seconds=0)

    for r in results:
        print(f"Score: {r.llm_result.sentiment_score}, "
              f"rendement 1u: {r.return_1h_pct}%, 4u: {r.return_4h_pct}%, 24u: {r.return_24h_pct}%")

    stats = BacktestPipeline.evaluate_predictive_value(results, score_threshold=0.5, horizon="4h")
    print(f"\nEvaluatie: {stats}")
