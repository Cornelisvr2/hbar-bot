"""
recalibrate_from_live_history.py

Sluit de daadwerkelijke "leert van zijn eigen ervaring"-cirkel: haalt de
sentiment_log-historie op die de LIVE bot zelf al heeft opgebouwd in
Postgres, zoekt daarbij de daadwerkelijke koersbeweging die er daarna
plaatsvond (via Binance), en herbouwt calibration_examples.json op basis
daarvan.

BELANGRIJK -- dit is nog steeds geen volautomatisch "leren":
1. Dit script moet PERIODIEK gedraaid worden (bv. wekelijks) -- er is
   geen doorlopend proces dat dit vanzelf doet.
2. Na het herschrijven van calibration_examples.json moet de bot
   OPNIEUW OPSTARTEN om de nieuwe kalibratie te laden.
3. Hoe langer de bot draait, hoe meer eigen historie er is -- in de
   eerste dagen/weken levert dit weinig of geen voorbeelden op, simpelweg
   omdat er nog te weinig data is. Dat is verwacht, geen fout.
"""

import asyncio
from datetime import datetime, timedelta

from postgres_client import PostgresClient
from binance_klines_client import BinanceKlinesClient
from backtest_pipeline import BacktestResult, HistoricalNewsItem
from llm_sentiment_engine import LlmSentimentResult
from generate_calibration_examples import select_confirmed_examples, write_calibration_file
import telegram_notify


async def fetch_live_sentiment_history(db: PostgresClient, min_age_hours: float = 24.0):
    cutoff = datetime.now() - timedelta(hours=min_age_hours)
    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT asset, headline, sentiment_score, confidence, "
            "is_idiosyncratic, rationale, volatility_sigma, created_at FROM sentiment_log "
            "WHERE created_at <= $1 ORDER BY created_at",
            cutoff,
        )
    return rows


def build_backtest_results(rows, binance: BinanceKlinesClient) -> list:
    results = []
    by_asset = {}
    for row in rows:
        by_asset.setdefault(row["asset"], []).append(row)

    for asset, asset_rows in by_asset.items():
        if asset not in ("BTC", "HBAR"):
            continue

        oldest = min(r["created_at"] for r in asset_rows)
        klines = binance.fetch_range(
            asset,
            start_time=oldest.timestamp() - 3600,
            end_time=datetime.now().timestamp(),
            interval="1m",
        )
        lookup_fn = binance.build_price_lookup_fn(asset, klines)

        for row in asset_rows:
            published_at = row["created_at"]
            price_at_publish_result = lookup_fn(asset, published_at)
            if price_at_publish_result is None:
                continue
            price_at_publish = price_at_publish_result[0]

            def price_after(hours):
                r = lookup_fn(asset, published_at + timedelta(hours=hours))
                return r[0] if r else None

            price_1h = price_after(1)
            price_4h = price_after(4)
            price_24h = price_after(24)

            def pct_return(later):
                if later is None or price_at_publish == 0:
                    return None
                return round((later - price_at_publish) / price_at_publish * 100, 3)

            news_item = HistoricalNewsItem(
                asset=asset, headline=row["headline"], published_at=published_at,
                price_at_publish=price_at_publish,
            )
            llm_result = LlmSentimentResult(
                asset=asset, sentiment_score=row["sentiment_score"],
                confidence=row["confidence"], rationale=row["rationale"] or "",
                counter_argument="", is_idiosyncratic=row["is_idiosyncratic"],
                headline=row["headline"],
            )

            results.append(BacktestResult(
                news_item=news_item, llm_result=llm_result,
                price_after_1h=price_1h, price_after_4h=price_4h, price_after_24h=price_24h,
                return_1h_pct=pct_return(price_1h), return_4h_pct=pct_return(price_4h),
                return_24h_pct=pct_return(price_24h),
            ))

    return results


def build_volatility_calibration_datapoints(rows, binance: BinanceKlinesClient,
                                              horizon_hours: float = 4.0):
    """
    Bouwt (voorspelde_sigma, gerealiseerde_sigma)-paren voor de
    zelflerende kalibratie (28 aug 2026, zie self_calibration_model.py).

    BELANGRIJKE KANTTEKENING: sentiment_log bevat per-HEADLINE-scores,
    terwijl de bot's daadwerkelijke, live GBM-berekening een
    GEAGGREGEERDE volatility_sigma gebruikt (over meerdere headlines
    binnen een 5-minuten-verversing, tijd-gewogen). Deze functie gebruikt
    de per-headline-score als praktische PROXY voor de geaggregeerde
    voorspelling op dat moment -- een benadering, geen exacte
    reconstructie van wat de bot destijds daadwerkelijk gebruikte.
    """
    from self_calibration_model import CalibrationDataPoint
    import statistics

    datapoints = []
    by_asset = {}
    for row in rows:
        by_asset.setdefault(row["asset"], []).append(row)

    for asset, asset_rows in by_asset.items():
        if asset not in ("BTC", "HBAR"):
            continue

        oldest = min(r["created_at"] for r in asset_rows)
        klines = binance.fetch_range(
            asset,
            start_time=oldest.timestamp() - 3600,
            end_time=datetime.now().timestamp(),
            interval="1h",
        )
        if not klines:
            continue

        for row in asset_rows:
            published_at = row["created_at"]
            window_end = published_at + timedelta(hours=horizon_hours)

            venster_closes = [
                k.close for k in klines
                if published_at.timestamp() <= k.open_time <= window_end.timestamp()
            ]
            if len(venster_closes) < 3:
                continue  # te weinig data in dit venster voor een betrouwbare stdev

            hourly_returns = [
                (venster_closes[i] - venster_closes[i - 1]) / venster_closes[i - 1]
                for i in range(1, len(venster_closes)) if venster_closes[i - 1] != 0
            ]
            if len(hourly_returns) < 2:
                continue

            realized_sigma = statistics.pstdev(hourly_returns)
            # Normaliseren naar dezelfde 0.0-1.0-schaal als de LLM's
            # volatility_sigma -- ruwe aanname: 0.02 (2% per uur) komt
            # overeen met sigma=1.0 (zelfde grootteorde als eerder vandaag
            # empirisch gemeten HBAR-volatiliteit tijdens rustige periodes
            # vs. drukkere periodes).
            realized_sigma_genormaliseerd = min(1.0, realized_sigma / 0.02)

            datapoints.append(CalibrationDataPoint(
                predicted_sigma=row["volatility_sigma"],
                realized_sigma=realized_sigma_genormaliseerd,
                timestamp=published_at.timestamp(),
            ))

    return datapoints


async def main():
    db = PostgresClient()
    await db.connect()

    rows = await fetch_live_sentiment_history(db)
    print(f"{len(rows)} sentiment_log-items oud genoeg voor herkalibratie (>=24u)")

    if not rows:
        print(
            "Nog geen bruikbare live-historie -- de bot moet eerst langer draaien "
            "voordat dit script iets oplevert. Verwacht in vroege Fase 2, geen fout."
        )
        await db.close()
        return

    binance = BinanceKlinesClient()
    results = build_backtest_results(rows, binance)
    print(f"{len(results)} items met geldige koersdata")

    examples = select_confirmed_examples(results, horizon="24h")

    if not examples:
        print(
            "Geen bevestigde signalen gevonden in de eigen historie -- "
            "calibration_examples.json wordt niet overschreven."
        )
    else:
        print("\nGeselecteerde voorbeelden uit eigen historie:")
        for ex in examples:
            print(f"  [{ex['asset']}] score={ex['sentiment_score']:+.2f}, "
                  f"rendement={ex['return_pct']:+.1f}% -- {ex['headline'][:60]}")
        write_calibration_file(examples)
        print(
            "\nBELANGRIJK: herstart de bot (docker compose up -d --build) om deze "
            "nieuwe kalibratie daadwerkelijk te laten meewegen."
        )
        telegram_notify.send_telegram_message(
            f"HBAR Bot -- Herkalibratie: {len(examples)} nieuwe bevestigde "
            f"voorbeelden gevonden uit {len(rows)} eigen historische items. "
            f"Herstart de bot om dit toe te passen."
        )

    # Volatiliteit-kalibratie (28 aug 2026, op verzoek) -- apart van de
    # sentiment-few-shot-voorbeelden hierboven: meet hoe goed de LLM's
    # volatility_sigma-voorspellingen overeenkwamen met de daadwerkelijk
    # gerealiseerde koersvolatiliteit, en past een kalibratiefactor traag
    # aan (zie self_calibration_model.py voor de wiskunde en
    # veiligheidsmaatregelen).
    import json
    import os
    from self_calibration_model import compute_calibration_factor

    CALIBRATION_FACTOR_PATH = os.path.join(os.path.dirname(__file__), "volatility_calibration.json")

    huidige_factor = 1.0
    if os.path.exists(CALIBRATION_FACTOR_PATH):
        try:
            with open(CALIBRATION_FACTOR_PATH) as f:
                huidige_factor = json.load(f).get("calibration_factor", 1.0)
        except (json.JSONDecodeError, OSError):
            pass  # val terug op 1.0 (ongekalibreerd) bij een corrupt/onleesbaar bestand

    datapoints = build_volatility_calibration_datapoints(rows, binance)
    print(f"\n{len(datapoints)} volatiliteit-kalibratiepunten gevonden.")

    if datapoints:
        kalibratie_resultaat = compute_calibration_factor(datapoints, current_factor=huidige_factor)
        with open(CALIBRATION_FACTOR_PATH, "w") as f:
            json.dump({
                "calibration_factor": kalibratie_resultaat.calibration_factor,
                "mean_squared_error": kalibratie_resultaat.mean_squared_error,
                "n_datapoints": kalibratie_resultaat.n_datapoints,
                "is_calibrated": kalibratie_resultaat.is_calibrated,
                "updated_at": datetime.now().isoformat(),
            }, f, indent=2)

        print(f"Volatiliteit-kalibratiefactor: {kalibratie_resultaat.calibration_factor:.4f} "
              f"(MSE={kalibratie_resultaat.mean_squared_error:.4f}, "
              f"n={kalibratie_resultaat.n_datapoints}, "
              f"gekalibreerd={kalibratie_resultaat.is_calibrated})")

        if kalibratie_resultaat.is_calibrated and abs(kalibratie_resultaat.calibration_factor - huidige_factor) > 0.01:
            telegram_notify.send_telegram_message(
                f"HBAR Bot -- Volatiliteit-kalibratie bijgewerkt: "
                f"{huidige_factor:.3f} -> {kalibratie_resultaat.calibration_factor:.3f} "
                f"(gebaseerd op {kalibratie_resultaat.n_datapoints} datapunten). "
                f"Herstart de bot om dit toe te passen."
            )
    else:
        print("Nog geen bruikbare volatiliteit-kalibratiepunten -- te weinig data of te recent.")

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
