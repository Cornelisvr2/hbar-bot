"""
decision_log.py -- (8 sep 2026, op verzoek) Beslissingslog voor het later
strakker of slapper afstellen van de drempels.

Elke beslissing van de bot -- EN elke bijna-beslissing -- gaat als een
JSON-regel naar logs/decisions.jsonl (gedeelde logs-map, overleeft
herstarts, leesbaar met elk tooltje). Per regel: tijd, soort, prijs,
score, de drempel(s) die ertoe deden, regime voor/na en de reden.

Soorten (kind):
  regime_change          bull/bear-reflex in, terug naar LP
  regime_deferred        overgang gewenst maar cooldown actief
  trailing_stop          bullish/bearish trailing-stop getriggerd
  market_confirmed_exit  1%-terugval / zijwaarts + bevestiging
  rebalance / rebalance_skipped
  capital_deploy, swap
  depeg_warning / depeg_halt
  near_miss              drempel NIET gehaald maar dichtbij (score binnen
                         0,10 van de reflex-drempel, prijs binnen 1,5%
                         van een stop) -- gethrottled, 1x per 15 min per
                         soort. Dit zijn de gevallen waar je bij het
                         afstellen naar kijkt.

Analyse: python3 analyse_decisions.py (telt per soort, toont near-misses
en wat er daarna met de prijs gebeurde).
"""

import json
import os
import time

LOG_PATH = os.environ.get("DECISION_LOG_FILE", "/app/logs/decisions.jsonl")
_last_near_miss: dict = {}
NEAR_MISS_THROTTLE_SECONDS = 15 * 60


def log(kind: str, **fields) -> None:
    rec = {"ts": time.time(), "kind": kind}
    rec.update({k: v for k, v in fields.items() if v is not None})
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        print(f"[decision-log] schrijven mislukt: {e}")


def near_miss(subkind: str, **fields) -> None:
    """Zoals log('near_miss') maar hoogstens 1x per 15 min per subkind."""
    now = time.time()
    if now - _last_near_miss.get(subkind, 0.0) < NEAR_MISS_THROTTLE_SECONDS:
        return
    _last_near_miss[subkind] = now
    log("near_miss", subkind=subkind, **fields)


def read_all(path: str = LOG_PATH) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        return []
