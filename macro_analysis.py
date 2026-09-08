"""
macro_analysis.py -- (8 sep 2026, op verzoek) Meerlaagse macro-analyse als
vervanging voor het enkelvoudige 30-daags-momentum. Draait eerst in
SCHADUWMODUS: logt en toont, de bot beslist nog op het oude signaal.

Lagen:
  1. Halving-cyclus (prior): maanden sinds de laatste BTC-halving ->
     cyclusfase. Werkt alleen DEMPEND op bullish uitkomsten, draait nooit
     zelf een regime om.
  2. Marktstatus (BTC en HBAR): prijs t.o.v. 200-daags gemiddelde en de
     richting van dat gemiddelde -> bull / bear / overgang.
  3. Trend per horizon: 6 maanden / 1 maand / 7 dagen / 24 uur, per asset:
     totaalrendement + helling van een lineaire fit op de log-prijs.
  4. Uitlijning: alle horizons dezelfde kant op = sterk; 6m bear + 7d bull
     = bear-market-rally (geen opwaartse scheefheid); 6m bull + 7d bear =
     dip in opgaande trend.
  5. Eindscore (-1..+1) met betrouwbaarheid, regime-label en een
     drift-multiplier voor de range-asymmetrie. BTC is leidend
     (BTC_WEIGHT), HBAR volgt.

Data: Binance dag- en uurcandles (BTCUSDT, HBARUSDT), 1 uur gecachet.
"""

import math
import os
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional

BTC_WEIGHT = float(os.environ.get("MACRO_BTC_WEIGHT", "0.65"))  # BTC leidend, HBAR volgt
HORIZON_WEIGHTS = {"6m": 0.30, "1m": 0.30, "7d": 0.25, "24h": 0.15}
# Drempels (totaalrendement) waarboven/-onder een horizon bull/bear heet
HORIZON_THRESHOLDS = {"6m": 0.15, "1m": 0.08, "7d": 0.04, "24h": 0.02}
HORIZON_DAYS = {"6m": 180, "1m": 30, "7d": 7}

HALVINGS = [
    datetime(2012, 11, 28, tzinfo=timezone.utc),
    datetime(2016, 7, 9, tzinfo=timezone.utc),
    datetime(2020, 5, 11, tzinfo=timezone.utc),
    datetime(2024, 4, 20, tzinfo=timezone.utc),
]
NEXT_HALVING_ESTIMATE = datetime(2028, 4, 1, tzinfo=timezone.utc)

CACHE_TTL = int(os.environ.get("MACRO_CACHE_SECONDS", "3600"))


@dataclass
class HorizonTrend:
    horizon: str
    total_return: float
    slope_per_day: float  # log-prijs helling per dag
    label: str            # bull / bear / sideways


@dataclass
class AssetView:
    asset: str
    price: float
    ma200: Optional[float]
    ma200_slope_20d: Optional[float]     # relatieve verandering van MA200 over 20 dagen
    market_state: str                    # bull / bear / overgang / onbekend
    trends: dict = field(default_factory=dict)  # horizon -> HorizonTrend


@dataclass
class MacroAnalysis:
    computed_at: float
    halving_months_since: float
    halving_phase: str
    halving_bull_damping: float          # 1.0 = geen demping; <1 dempt bullish score
    btc: AssetView
    hbar: AssetView
    alignment: str                       # bv. "uitgelijnd bull", "bear-market-rally", ...
    alignment_note: str
    score: float                         # -1..+1
    confidence: float                    # 0..1
    regime: str                          # bull / bear / sideways
    drift_multiplier: float              # 0..1.5, stuurt range-asymmetrie
    shadow_vs_current: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ----------------------------------------------------------------- helpers
def _label(ret: float, threshold: float) -> str:
    if ret >= threshold:
        return "bull"
    if ret <= -threshold:
        return "bear"
    return "sideways"


def _log_slope(closes: list[float]) -> float:
    """Helling (per candle) van een kleinste-kwadraten-fit op ln(prijs)."""
    n = len(closes)
    if n < 3:
        return 0.0
    xs = list(range(n))
    ys = [math.log(c) for c in closes if c > 0]
    if len(ys) != n:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


def _asset_view(asset: str, daily: list, hourly: list) -> AssetView:
    closes = [k.close for k in daily]
    price = hourly[-1].close if hourly else closes[-1]
    ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
    ma200_prev = sum(closes[-220:-20]) / 200 if len(closes) >= 220 else None
    slope = (ma200 / ma200_prev - 1) if (ma200 and ma200_prev) else None
    if ma200 is None:
        state = "onbekend"
    elif price > ma200 and (slope or 0) >= 0:
        state = "bull"
    elif price < ma200 and (slope or 0) <= 0:
        state = "bear"
    else:
        state = "overgang"

    trends = {}
    for h, days in HORIZON_DAYS.items():
        window = closes[-(days + 1):]
        if len(window) < 2:
            continue
        ret = window[-1] / window[0] - 1
        trends[h] = HorizonTrend(h, ret, _log_slope(window), _label(ret, HORIZON_THRESHOLDS[h]))
    if len(hourly) >= 25:
        w = [k.close for k in hourly[-25:]]
        ret = w[-1] / w[0] - 1
        trends["24h"] = HorizonTrend("24h", ret, _log_slope(w) * 24, _label(ret, HORIZON_THRESHOLDS["24h"]))
    return AssetView(asset, price, ma200, slope, state, trends)


def _halving_phase(now: datetime) -> tuple[float, str, float]:
    last = max(h for h in HALVINGS if h <= now)
    months = (now - last).days / 30.44
    # Historisch gemiddelde (2012/2016/2020): top 12-18 mnd na halving,
    # daarna 12-18 mnd bear, dan accumulatie richting de volgende halving.
    if months < 6:
        return months, "vroege cyclus (accumulatie/expansie)", 1.0
    if months < 12:
        return months, "expansie", 1.0
    if months < 18:
        return months, "late expansie / topvorming", 0.85
    if months < 30:
        return months, "post-top / bearfase (historisch)", 0.65
    if months < 42:
        return months, "late bear / bodemvorming", 0.8
    return months, "pre-halving accumulatie", 0.9


def _alignment(btc: AssetView, hbar: AssetView) -> tuple[str, str]:
    l6 = btc.trends.get("6m").label if "6m" in btc.trends else "onbekend"
    l1 = btc.trends.get("1m").label if "1m" in btc.trends else "onbekend"
    l7 = btc.trends.get("7d").label if "7d" in btc.trends else "onbekend"
    labels = [t.label for t in btc.trends.values()]
    if labels and all(l == "bull" for l in labels):
        return "uitgelijnd bull", "BTC op alle horizons bullish -- scheve range naar boven verantwoord"
    if labels and all(l == "bear" for l in labels):
        return "uitgelijnd bear", "BTC op alle horizons bearish -- geen opwaartse scheefheid, reflex-drempel dichtbij"
    if l6 == "bear" and l7 == "bull":
        return "bear-market-rally", "6m bear, 7d bull: tijdelijke opleving in een dalende markt -- GEEN opwaartse scheefheid"
    if l6 == "bull" and l7 == "bear":
        return "dip in opgaande trend", "6m bull, 7d bear: correctie binnen een stijgende markt -- onderkant iets ruimer, geen bear-reflex"
    if l1 == "bull" and l7 == "bull" and l6 != "bear":
        return "kortetermijn bull", "1m en 7d bullish, 6m neutraal"
    if l1 == "bear" and l7 == "bear" and l6 != "bull":
        return "kortetermijn bear", "1m en 7d bearish, 6m neutraal"
    if "bear" not in labels and l6 == "bull" and l1 == "bull":
        return "overwegend bull", "6m en 1m bullish, korte termijn pauzeert -- gematigde opwaartse scheefheid"
    if "bull" not in labels and l6 == "bear" and l1 == "bear":
        return "overwegend bear", "6m en 1m bearish, korte termijn pauzeert -- geen opwaartse scheefheid"
    return "gemengd", "horizons spreken elkaar tegen -- neutraal, geen scheefheid"


def _score(view: AssetView) -> float:
    s = 0.0
    for h, w in HORIZON_WEIGHTS.items():
        t = view.trends.get(h)
        if not t:
            continue
        # Genormaliseerd: rendement gedeeld door 2x de drempel, geklemd op +-1
        s += w * max(-1.0, min(1.0, t.total_return / (2 * HORIZON_THRESHOLDS[h])))
    # Marktstatus (MA200) als extra duw
    if view.market_state == "bull":
        s += 0.15
    elif view.market_state == "bear":
        s -= 0.15
    return max(-1.0, min(1.0, s))


# ------------------------------------------------------------------ main
_cache: dict = {}


def compute_macro_analysis(binance_client, current_bot_regime: Optional[str] = None,
                           force: bool = False) -> MacroAnalysis:
    hit = _cache.get("ma")
    if hit and not force and time.time() - hit[0] < CACHE_TTL:
        res = hit[1]
    else:
        btc_d = binance_client.get_klines("BTC", interval="1d", limit=230)
        hbar_d = binance_client.get_klines("HBAR", interval="1d", limit=230)
        btc_h = binance_client.get_klines("BTC", interval="1h", limit=30)
        hbar_h = binance_client.get_klines("HBAR", interval="1h", limit=30)
        btc = _asset_view("BTC", btc_d, btc_h)
        hbar = _asset_view("HBAR", hbar_d, hbar_h)

        now = datetime.now(timezone.utc)
        months, phase, damping = _halving_phase(now)
        alignment, note = _alignment(btc, hbar)

        raw = BTC_WEIGHT * _score(btc) + (1 - BTC_WEIGHT) * _score(hbar)
        if alignment == "bear-market-rally":
            raw = min(raw, 0.0)
        if raw > 0:
            raw *= damping
        score = max(-1.0, min(1.0, raw))

        # Betrouwbaarheid: eensgezindheid van de horizons (BTC) + BTC/HBAR-overeenstemming
        btc_labels = [t.label for t in btc.trends.values()]
        agree = max(btc_labels.count("bull"), btc_labels.count("bear")) / len(btc_labels) if btc_labels else 0.0
        same_dir = 1.0 if (_score(btc) * _score(hbar) > 0) else 0.5
        confidence = round(0.7 * agree + 0.3 * same_dir, 2)

        if score >= 0.25:
            regime = "bull"
        elif score <= -0.25:
            regime = "bear"
        else:
            regime = "sideways"
        # Drift-multiplier: 0 = symmetrische range; 1 = huidige bull-versterking; >1 nooit
        drift_mult = 0.0
        if regime == "bull" and alignment in ("uitgelijnd bull", "overwegend bull", "kortetermijn bull", "dip in opgaande trend"):
            drift_mult = round(min(1.0, abs(score) * confidence * 1.5), 2)
        elif regime == "bear":
            drift_mult = round(-min(1.0, abs(score) * confidence * 1.5), 2)

        res = MacroAnalysis(time.time(), round(months, 1), phase, damping, btc, hbar,
                            alignment, note, round(score, 3), confidence, regime, drift_mult)
        _cache["ma"] = (time.time(), res)

    if current_bot_regime:
        res.shadow_vs_current = ("gelijk" if current_bot_regime == res.regime
                                 else f"verschilt: bot={current_bot_regime}, macro={res.regime}")
    return res


def format_log_line(m: MacroAnalysis) -> str:
    def tr(v: AssetView):
        return " ".join(f"{h}:{t.label[:4]}({t.total_return*100:+.1f}%)" for h, t in v.trends.items())
    return (f"[macro] score={m.score:+.2f} conf={m.confidence:.2f} regime={m.regime} drift_mult={m.drift_multiplier:+.2f} | "
            f"{m.alignment} | halving {m.halving_months_since:.0f}mnd ({m.halving_phase}, demping {m.halving_bull_damping}) | "
            f"BTC {m.btc.market_state} [{tr(m.btc)}] | HBAR {m.hbar.market_state} [{tr(m.hbar)}]"
            + (f" | schaduw: {m.shadow_vs_current}" if m.shadow_vs_current else ""))
