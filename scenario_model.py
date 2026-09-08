"""
scenario_model.py -- (8 sep 2026, op verzoek) Scenario-model tot ~2030:
drie HBAR-prijspaden (bear / basis / bull), afgeleid van de twee eerdere
HBAR-cycli en de BTC-halving-cyclus, met per pad de walletwaarde onder
HODL versus de bot-strategie.

DIT IS GEEN VOORSPELLING. Twee HBAR-cycli en drie BTC-cycli zijn te
weinig voor statistiek; dit zijn expliciete, aanpasbare aannames
(SCENARIO_ANCHORS, ook via .env SCENARIO_ANCHORS_JSON) waarmee je de
vraag beantwoordt: "wat doet de strategie als het loopt zoals ik denk,
en wat als ik ongelijk heb?"

Bot-model (bewust eenvoudig, maandstappen):
- LP_MODE: positie wordt maandelijks rond de prijs gehouden. Een
  geconcentreerde, steeds hergecentreerde positie heeft ~50/50-
  blootstelling: waarde ~ sqrt(P1/P0), minus impermanent-loss van de
  range (IL_FACTOR), plus fees+LARI (jaar-APR / 12), minus
  herbalanceerkosten (REBALANCE_COST_PCT per maand).
- BULLISH_REFLEX: als de prijs over de komende 3 maanden > REFLEX_UP
  stijgt, zit de bot 100% in HBAR (volgt HODL, geen fees).
- BEARISH_REFLEX: als de prijs over de komende 3 maanden > REFLEX_DOWN
  daalt, zit de bot 100% in USDC (waarde vlak, geen fees).
De reflexen zijn hier 'vooruitkijkend perfect' -- dat is te gunstig voor
de bot; daarom wordt REFLEX_HIT_RATE toegepast (fractie van de reflex-
maanden die de bot werkelijk goed timet).
"""

import json
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import date

MONTHS = int(os.environ.get("SCENARIO_MONTHS", "48"))

# Ankerpunten: (maand vanaf nu, USD-prijs). Log-lineair geinterpoleerd.
# Basis = jouw scenario: 12-18 mnd sideways 0,06-0,12, dan aanloop naar
# een lagere piek dan 2024/25 (0,40) rond 2029.
DEFAULT_ANCHORS = {
    "bear":  [(0, None), (6, 0.050), (18, 0.055), (30, 0.10), (40, 0.22), (48, 0.12)],
    "basis": [(0, None), (12, 0.09), (24, 0.12), (36, 0.30), (42, 0.25), (48, 0.16)],
    "bull":  [(0, None), (6, 0.12), (12, 0.20), (24, 0.40), (30, 0.32), (48, 0.20)],
}

# APR-factor per scenario: fees volgen het handelsvolume (stort in in een
# bear, stijgt in een bull); LARI-allocaties zijn niet gegarandeerd. De
# huidige, gemeten totaal-APR wordt hiermee vermenigvuldigd.
APR_FACTOR = {"bear": 0.45, "basis": 0.75, "bull": 1.15}
APR_FACTOR.update({k: float(v) for k, v in json.loads(os.environ.get("SCENARIO_APR_FACTOR_JSON", "{}")).items()})

IL_FACTOR = float(os.environ.get("SCENARIO_IL_FACTOR", "0.35"))          # fractie van de theoretische IL die een smalle range extra kost
REBALANCE_COST_PCT = float(os.environ.get("SCENARIO_REBALANCE_COST_PCT", "0.004"))  # 0,4% per maand
REFLEX_UP = float(os.environ.get("SCENARIO_REFLEX_UP", "0.25"))          # +25% over 3 mnd -> bullish reflex
REFLEX_DOWN = float(os.environ.get("SCENARIO_REFLEX_DOWN", "0.20"))      # -20% over 3 mnd -> bearish reflex
REFLEX_HIT_RATE = float(os.environ.get("SCENARIO_REFLEX_HIT_RATE", "0.6"))


def _anchors() -> dict:
    raw = os.environ.get("SCENARIO_ANCHORS_JSON")
    if raw:
        try:
            d = json.loads(raw)
            return {k: [tuple(x) for x in v] for k, v in d.items()}
        except Exception:
            pass
    return DEFAULT_ANCHORS


def _price_path(anchors: list, p0: float, months: int) -> list[float]:
    pts = [(m, (p if p is not None else p0)) for m, p in anchors]
    out = []
    for m in range(months + 1):
        for (m1, p1), (m2, p2) in zip(pts, pts[1:]):
            if m1 <= m <= m2:
                t = (m - m1) / (m2 - m1) if m2 > m1 else 0
                out.append(p1 * (p2 / p1) ** t)
                break
        else:
            out.append(pts[-1][1])
    return out


@dataclass
class ScenarioResult:
    name: str
    months: list[int]
    labels: list[str]
    price: list[float]
    hodl: list[float]
    bot: list[float]
    regime: list[str]
    peak_price: float
    peak_month: int
    end_hodl: float
    end_bot: float
    peak_hodl: float
    peak_bot: float
    bot_wins_months: int
    fees_earned_usd: float


def simulate(name: str, anchors: list, p0: float, start_value_usd: float, total_apr: float,
             months: int = MONTHS, start: date = None) -> ScenarioResult:
    start = start or date.today()
    price = _price_path(anchors, p0, months)
    hbar_units = start_value_usd / p0
    hodl = [hbar_units * p for p in price]
    bot = [start_value_usd]
    regimes = ["lp"]
    fees_total = 0.0
    monthly_apr = total_apr / 12
    for m in range(1, months + 1):
        p_prev, p_now = price[m - 1], price[m]
        # Regime op basis van de 3 maanden VOORUIT (perfecte timing, daarna afgezwakt)
        look = price[min(m - 1 + 3, months)] / p_prev - 1
        if look >= REFLEX_UP:
            reg = "bull_reflex"
        elif look <= -REFLEX_DOWN:
            reg = "bear_reflex"
        else:
            reg = "lp"
        v = bot[-1]
        ratio = p_now / p_prev
        lp_value = v * math.sqrt(ratio)
        # IL t.o.v. 50/50-HODL, versterkt voor een smalle range
        il = (2 * math.sqrt(ratio) / (1 + ratio)) - 1
        lp_value *= (1 + il * IL_FACTOR)
        fees = v * monthly_apr
        lp_value += fees
        lp_value *= (1 - REBALANCE_COST_PCT)
        if reg == "bull_reflex":
            v_new = REFLEX_HIT_RATE * (v * ratio) + (1 - REFLEX_HIT_RATE) * lp_value
            fees_total += (1 - REFLEX_HIT_RATE) * fees
        elif reg == "bear_reflex":
            v_new = REFLEX_HIT_RATE * v + (1 - REFLEX_HIT_RATE) * lp_value
            fees_total += (1 - REFLEX_HIT_RATE) * fees
        else:
            v_new = lp_value
            fees_total += fees
        bot.append(v_new)
        regimes.append(reg)

    labels = []
    for m in range(months + 1):
        y = start.year + (start.month - 1 + m) // 12
        mo = (start.month - 1 + m) % 12 + 1
        labels.append(f"{mo:02d}/{y}")
    peak_m = max(range(months + 1), key=lambda i: price[i])
    wins = sum(1 for i in range(1, months + 1) if bot[i] > hodl[i])
    return ScenarioResult(name, list(range(months + 1)), labels, price, hodl, bot, regimes,
                          price[peak_m], peak_m, hodl[-1], bot[-1], max(hodl), max(bot), wins, fees_total)


def run_all(p0: float, start_value_usd: float, total_apr: float) -> dict:
    res = {name: simulate(name, a, p0, start_value_usd, total_apr * APR_FACTOR.get(name, 1.0))
           for name, a in _anchors().items()}
    return {
        "inputs": {"p0": p0, "start_value_usd": start_value_usd, "total_apr_pct": total_apr * 100,
                   "il_factor": IL_FACTOR, "rebalance_cost_pct": REBALANCE_COST_PCT * 100,
                   "reflex_up_pct": REFLEX_UP * 100, "reflex_down_pct": REFLEX_DOWN * 100,
                   "reflex_hit_rate": REFLEX_HIT_RATE, "months": MONTHS,
                   "apr_factor": APR_FACTOR,
                   "effective_apr_pct": {k: total_apr * APR_FACTOR.get(k, 1.0) * 100 for k in res}},
        "scenarios": {k: asdict(v) for k, v in res.items()},
    }
