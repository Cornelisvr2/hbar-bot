"""
fase_signaal.py -- trage trend-fasebepaling voor de HBAR-bot (V4).

De enige actieve strategie die in de backtests op 2 jaar HBAR-data standhield
(DCA-fase +19% vs pool +8%; momentum en nieuws verloren). Bepaalt op de
200-daags trend met hysterese welk regime gewenst is:
  BULL     -> BULLISH_REFLEX (100% HBAR): koers > MA200 * (1+band), 7 dagen
              op rij bevestigd. De hele stijging in muntjes behouden.
  anders   -> LP_MODE (pool): muntjes sparen via fees in de zijwaartse
              bodem. NOOIT USDC -- de eigenaar ziet dips als koopkans en
              koopt handmatig bij.

Onderbouwing (11 sep 2026, muntjes-backtests op 2 jaar HBAR):
- pool wint van vasthouden in de zijwaartse bodem (+7% muntjes);
- pool VERLIEST van vasthouden in de bull (pool verkoopt HBAR onderweg
  omhoog) -> daarom 100% HBAR zodra de bull bevestigd is;
- 2-daagse bevestiging kostte muntjes door valse starts -> 7 dagen.
Doel is MAXIMALE muntjes, niet eurowaarde.
Dit is een PURE functie op een prijsreeks -- geen side effects, makkelijk te
testen en te backtesten met exact dezelfde code als live draait.
"""
from dataclasses import dataclass
from typing import Optional

BAND = 0.08              # hysterese-band rond MA200
BEVESTIGING_DAGEN = 7    # dagen op rij bevestigd BULL voor we naar HBAR gaan
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

    # BULL alleen als de koers `bevestiging` dagen OP RIJ boven MA200*(1+band)
    # stond. Al het andere = SIDEWAYS -> pool (nooit USDC).
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
        else:
            sigs.append("GEEN")

    is_bull = (len(sigs) == bevestiging and all(x == "BULL" for x in sigs))
    fase = "BULL" if is_bull else "SIDEWAYS"

    onderbouwing = (f"koers {koers:.5f} vs MA200 {ma:.5f} ({afstand:+.1f}%), "
                    f"laatste {bevestiging}d {'allemaal' if is_bull else 'niet allemaal'} boven "
                    f"MA200+{band*100:.0f}% -> {fase} ({'100% HBAR' if is_bull else 'pool'})")
    return FaseResultaat(fase, ma, koers, afstand, onderbouwing)


# mapping naar het bestaande Regime-systeem in regime_orchestrator.py
FASE_NAAR_REGIME = {
    "BULL": "BULLISH_REFLEX",     # 100% HBAR
    "SIDEWAYS": "LP_MODE",        # pool -- ook in bear (nooit USDC)
}
