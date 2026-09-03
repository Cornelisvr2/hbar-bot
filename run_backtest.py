"""
run_backtest.py

Eerste, direct uitvoerbare Fase 1-backtest. Eerlijke kanttekening
vooraf: RSS-feeds geven realistisch gezien een archief van ~7-14 dagen,
geen diep jaar-archief. Binance's koershistorie is wel volledig -- de
beperkende factor is dus de nieuwsdiepte, niet de prijsdata.

Dit is een BESCHEIDEN eerste steekproef, geen jaar-brede validatie.
"""

import json
from datetime import datetime

from rss_news_client import RssNewsClient
from binance_klines_client import BinanceKlinesClient
from llm_sentiment_engine import LlmSentimentEngine
from backtest_pipeline import (
    BacktestPipeline, HistoricalNewsItem, get_price_strictly_at_or_before,
)


def run(asset: str, lookback_days: int = 14):
    print(f"\n=== Backtest voor {asset}, laatste {lookback_days} dagen ===")

    rss = RssNewsClient()
    news_items = rss.fetch_news(asset, max_age_hours=lookback_days * 24)
    print(f"{len(news_items)} nieuwsitems gevonden")

    if not news_items:
        print("Geen nieuws gevonden, backtest overgeslagen voor dit asset.")
        return []

    binance = BinanceKlinesClient()
    oldest_ts = min(item.published_at for item in news_items)
    newest_ts = datetime.now().timestamp()

    print("Historische koersen ophalen van Binance...")
    klines = binance.fetch_range(
        asset, start_time=oldest_ts - 3600, end_time=newest_ts, interval="1m",
    )
    print(f"{len(klines)} candles opgehaald")

    price_lookup_fn = binance.build_price_lookup_fn(asset, klines)

    historical_items = [
        HistoricalNewsItem(
            asset=asset,
            headline=item.title,
            published_at=datetime.fromtimestamp(item.published_at),
            price_at_publish=0.0,
        )
        for item in news_items
    ]

    valid_items = []
    for item in historical_items:
        price = get_price_strictly_at_or_before(
            asset, item.published_at, price_lookup_fn, max_staleness_minutes=10,
        )
        if price is not None:
            item.price_at_publish = price
            valid_items.append(item)

    print(f"{len(valid_items)} items met geldige prijsdata (rest overgeslagen)")

    engine = LlmSentimentEngine()
    pipeline = BacktestPipeline(engine)

    def wrapped_lookup(a, ts):
        result = price_lookup_fn(a, ts)
        return result[0] if result else None

    print(f"LLM-analyse starten voor {len(valid_items)} items (dit kan even duren, ~1-2s per item)...")
    results = []
    for i, item in enumerate(valid_items, 1):
        result = pipeline.run_single(item, wrapped_lookup)
        results.append(result)
        print(f"  [{i}/{len(valid_items)}] score={result.llm_result.sentiment_score:+.2f} -- {item.headline[:60]}")
    return results


if __name__ == "__main__":
    results_by_asset = {}
    for asset in ("BTC", "HBAR"):
        results_by_asset[asset] = run(asset, lookback_days=14)

    all_results = [r for results in results_by_asset.values() for r in results]

    if not all_results:
        print("\nGeen resultaten om te evalueren.")
    else:
        for asset, results in results_by_asset.items():
            if not results:
                continue
            print(f"\n=== Evaluatie {asset} alleen (n={len(results)}) ===")
            for horizon in ("1h", "4h", "24h"):
                stats = BacktestPipeline.evaluate_predictive_value(
                    results, score_threshold=0.5, horizon=horizon,
                )
                print(json.dumps(stats, indent=2))

        print(f"\n=== Evaluatie gecombineerd BTC+HBAR (n={len(all_results)}) ===")
        for horizon in ("1h", "4h", "24h"):
            stats = BacktestPipeline.evaluate_predictive_value(
                all_results, score_threshold=0.5, horizon=horizon,
            )
            print(json.dumps(stats, indent=2))
