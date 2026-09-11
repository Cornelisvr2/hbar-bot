"""
fase_signaal.py -- trage trend-fasebepaling voor de HBAR-bot (V4).

De enige actieve strategie die in de backtests op 2 jaar HBAR-data standhield
(DCA-fase +19% vs pool +8%; momentum en nieuws verloren). Bepaalt op de
200-daags trend met hysterese welk regime gewenst is:
  BULL     -> BULLISH_REFLEX (100% HBAR): koers > MA200 * (1+band), bevestigd
  BEAR     -> BEARISH_REFLEX (100% USDC): koers < MA200 * (1-band), bevestigd
  SIDEWAYS -> LP_MODE (pool): daartussen

Robuuste parameters uit de grid-backtest: band 8%, bevestiging 2 dagen.
Dit is een PURE functie op een prijsreeks -- geen side effects, makkelijk te
testen en te backtesten met exact dezelfde code als live draait.
"""
from dataclasses import dataclass
from typing import Optional

BAND = 0.08              # hysterese-band rond MA200
BEVESTIGING_DAGEN = 2    # opeenvolgende dagen aan dezelfde kant
MA_DAGEN = 200


@dataclass
class FaseResultaat:
    fase: str            # "BULL" | "BEAR" | "SIDEWAYS"
    ma200: float
    koers: float
    afstand_pct: float   # (koers - ma200) / ma200 * 100
    onderbouwing: str


def bepaal_fase(dagprijzen: list[float], vorige_fase: Optional[str] = None,
                band: float = BAND, bevestiging: int = BEVESTIGING_DAGEN) -> FaseResultaat:
    """
    dagprijzen: chronologische dagelijkse closes (laatste = vandaag).
    vorige_fase: de fase van gisteren, voor hysterese (bevestiging).
    Geeft de gewenste fase terug; None-veilig bij te weinig historie.
    """
    n = len(dagprijzen)
    if n < 30:
        return FaseResultaat("SIDEWAYS", 0.0, dagprijzen[-1] if n else 0.0, 0.0,
                             "te weinig historie -- standaard SIDEWAYS")
    venster = dagprijzen[-MA_DAGEN:] if n >= MA_DAGEN else dagprijzen
    ma = sum(venster) / len(venster)
    koers = dagprijzen[-1]
    afstand = (koers - ma) / ma * 100 if ma > 0 else 0.0

    # ruw signaal per dag over de laatste `bevestiging` dagen
    sigs = []
    for k in range(bevestiging):
        idx = n - 1 - k
        if idx < 0:
            break
        v = dagprijzen[max(0, idx - MA_DAGEN + 1):idx + 1]
        m = sum(v) / len(v)
        p = dagprijzen[idx]
        if p > m * (1 + band):
            sigs.append("BULL")
        elif p < m * (1 - band):
            sigs.append("BEAR")
        else:
            sigs.append("SIDEWAYS")

    bevestigd = sigs[0] if (len(sigs) == bevestiging and len(set(sigs)) == 1) else None
    fase = bevestigd if bevestigd is not None else (vorige_fase or "SIDEWAYS")

    onderbouwing = (f"koers {koers:.5f} vs MA200 {ma:.5f} ({afstand:+.1f}%), "
                    f"laatste {bevestiging}d: {'/'.join(sigs)} -> {fase}"
                    + ("" if bevestigd else " (niet bevestigd, fase behouden)"))
    return FaseResultaat(fase, ma, koers, afstand, onderbouwing)


# mapping naar het bestaande Regime-systeem in regime_orchestrator.py
FASE_NAAR_REGIME = {
    "BULL": "BULLISH_REFLEX",     # 100% HBAR
    "BEAR": "BEARISH_REFLEX",     # 100% USDC
    "SIDEWAYS": "LP_MODE",        # pool
}
