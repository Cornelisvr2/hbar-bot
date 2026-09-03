"""
generate_calibration_examples.py

Sluit de kalibratie-cirkel: doorzoekt backtest-resultaten op headlines
waar de sentiment-score en het daadwerkelijke koersverloop OVEREENKWAMEN
(bevestigde signalen), en schrijft de sterkste voorbeelden naar
calibration_examples.json. llm_sentiment_engine.py laadt dat bestand
automatisch bij de volgende herstart en gebruikt het als echte few-shot-
context, in plaats van de illustratieve placeholders.

Belangrijk onderscheid (zie ook de eerdere discussie hierover): dit is
GEEN training van het LLM. Het is het samenstellen van een klein aantal
concrete, geverifieerde ijkpunten die bij elke API-call worden
meegestuurd als context. Het model "onthoudt" niets tussen calls --
elke afzonderlijke aanroep krijgt deze voorbeelden opnieuw te zien.

Selectiecriteria voor een "bevestigd signaal":
- |sentiment_score| >= 0.5 (een duidelijke, geen twijfelachtige score)
- De richting van het daadwerkelijke rendement (24u-horizon) komt
  overeen met de richting van de score
- De magnitude van het rendement is substantieel (>1%), niet ruis

Gebruik: draai dit NA run_backtest.py, met dezelfde resultaten.
"""

import json
from typing import List

from backtest_pipeline import BacktestResult


MIN_SCORE_THRESHOLD = 0.5
MIN_RETURN_MAGNITUDE_PCT = 1.0
# Sanity-bovengrens (Gemini-feedback, 23 aug 2026): een "zwarte zwaan"-
# gebeurtenis (flash crash, data-fout) kan een absurd groot rendement
# opleveren dat als kalibratie-voorbeeld het model juist zou vergiftigen
# i.p.v. verbeteren. Zulke uitschieters worden bewust NIET als ijkpunt
# gebruikt, ook al voldoen ze aan de score/richting-criteria.
MAX_SANE_RETURN_MAGNITUDE_PCT = 20.0
MAX_EXAMPLES = 6  # niet te veel -- elke voorbeeld kost tokens bij elke live call


def select_confirmed_examples(results: List[BacktestResult],
                                horizon: str = "24h") -> List[dict]:
    """
    Filtert backtest-resultaten op bevestigde signalen: score en
    werkelijk rendement wijzen dezelfde kant op, en de beweging is groot
    genoeg om geen ruis te zijn.
    """
    return_field = f"return_{horizon}_pct"
    confirmed = []

    for r in results:
        score = r.llm_result.sentiment_score
        actual_return = getattr(r, return_field)

        if actual_return is None or abs(score) < MIN_SCORE_THRESHOLD:
            continue
        if abs(actual_return) < MIN_RETURN_MAGNITUDE_PCT:
            continue
        if abs(actual_return) > MAX_SANE_RETURN_MAGNITUDE_PCT:
            # Vermoedelijke uitschieter (flash crash, data-artefact) --
            # bewust niet gebruiken als kalibratie-ijkpunt.
            continue

        # Richting moet overeenkomen: positieve score + positief rendement,
        # of negatieve score + negatief rendement.
        same_direction = (score > 0) == (actual_return > 0)
        if not same_direction:
            continue

        confirmed.append({
            "headline": r.news_item.headline,
            "asset": r.news_item.asset,
            "sentiment_score": score,
            "return_pct": actual_return,
            "horizon": horizon,
            # Sorteersleutel: sterkste, duidelijkste voorbeelden eerst
            "_strength": abs(score) * abs(actual_return),
        })

    confirmed.sort(key=lambda x: x["_strength"], reverse=True)
    top_examples = confirmed[:MAX_EXAMPLES]

    for ex in top_examples:
        del ex["_strength"]  # puur intern, hoeft niet in het opgeslagen bestand

    return top_examples


def write_calibration_file(examples: List[dict], path: str = "calibration_examples.json"):
    with open(path, "w") as f:
        json.dump(examples, f, indent=2, ensure_ascii=False)
    print(f"{len(examples)} kalibratie-voorbeelden geschreven naar {path}")


if __name__ == "__main__":
    import sys
    from run_backtest import run

    all_results = []
    for asset in ("BTC", "HBAR"):
        results = run(asset, lookback_days=14)
        all_results.extend(results)

    if not all_results:
        print("Geen backtest-resultaten beschikbaar -- draai eerst run_backtest.py.")
        sys.exit(1)

    examples = select_confirmed_examples(all_results, horizon="24h")

    if not examples:
        print(
            "Geen bevestigde signalen gevonden binnen de huidige criteria "
            f"(|score|>={MIN_SCORE_THRESHOLD}, |rendement|>={MIN_RETURN_MAGNITUDE_PCT}%). "
            "calibration_examples.json wordt NIET overschreven -- de fallback-"
            "placeholders in llm_sentiment_engine.py blijven actief. Dit is een "
            "eerlijk resultaat gezien de kleine steekproef (zie PLAN.md), geen fout."
        )
        sys.exit(0)

    print("\nGeselecteerde voorbeelden:")
    for ex in examples:
        print(f"  [{ex['asset']}] score={ex['sentiment_score']:+.2f}, "
              f"rendement={ex['return_pct']:+.1f}% -- {ex['headline'][:60]}")

    write_calibration_file(examples)
