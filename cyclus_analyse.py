"""
cyclus_analyse.py -- waar staan we in de meerjarige cyclus?

Haalt de VOLLEDIGE daily-historie van HBAR en BTC op (Binance sinds 2019),
haalt de cyclus-component eruit (het meerjarige golfpatroon, losgemaakt van
de dagelijkse ruis) en bepaalt waar 'vandaag' staat -- zowel in HBAR's eigen
ritme als in BTC's halving-cyclus.

EERLIJK OVER WAT DIT IS: crypto heeft pas ~1,5 echte cyclus achter de rug.
Dit is GEEN voorspelling maar een kompas: "als de markt zich gedraagt zoals
in eerdere cycli, dan zitten we in deze fase en dan deed het patroon
historisch daarna dit." Onzekerheid is groot; gebruik het naast, niet in
plaats van, eigen oordeel.

Output (tekst + optioneel PNG):
  - cyclus-positie: maanden sinds de laatste all-time high en de laatste
    grote bodem; fase-label (accumulatie / vroege bull / late bull /
    distributie / bear).
  - halving-positie: maanden sinds de laatste BTC-halving (apr 2024) en
    hoe HBAR/BTC zich in vorige halving-cycli op dit punt gedroegen.
  - drift-schatting: gemiddelde 90d-forward-beweging vanuit vergelijkbare
    cyclusposities in het verleden, met spreiding -- de "macro-drift" die
    de fase-regelaar nu mist.

    docker compose run --rm -T hbar-bot python3 cyclus_analyse.py
    docker compose run --rm -T hbar-bot python3 cyclus_analyse.py --plot   # schrijft logs/cyclus_hbar.png
"""
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HALVINGS = [datetime(2020, 5, 11, tzinfo=timezone.utc),
            datetime(2024, 4, 20, tzinfo=timezone.utc),
            datetime(2028, 4, 1, tzinfo=timezone.utc)]  # 2028 geschat


def haal_historie(symbool):
    """Volledige daily (ts, close) sinds listing, via Binance."""
    from binance_klines_client import BinanceKlinesClient
    c = BinanceKlinesClient()
    start = datetime(2019, 9, 1, tzinfo=timezone.utc).timestamp()
    kl = c.fetch_range(symbool, start, time.time(), interval="1d", pause_seconds=0.2)
    return [(datetime.fromtimestamp(k.open_time, tz=timezone.utc), k.close) for k in kl]


def sma(v, n):
    out = [None] * len(v)
    som = 0.0
    for i in range(len(v)):
        som += v[i]
        if i >= n:
            som -= v[i - n]
        if i >= n - 1:
            out[i] = som / n
    return out


def cyclus_component(prijs):
    """
    Log-prijs minus 365d-trend = de cyclus-afwijking (waar staan we t.o.v.
    het meerjarige gemiddelde). Positief = boven trend (richting top),
    negatief = onder trend (richting bodem).
    """
    import math
    logp = [math.log(p) for p in prijs]
    trend = sma(logp, 365)
    return [(logp[i] - trend[i]) if trend[i] is not None else None for i in range(len(logp))]


def fase_label(cyc_nu, helling):
    if cyc_nu is None:
        return "onbekend (te weinig historie)"
    if cyc_nu < -0.5:
        return "diep onder trend -- bodem/accumulatie" if helling >= 0 else "diep onder trend -- nog dalend"
    if cyc_nu < 0:
        return "onder trend, herstellend (vroege bull)" if helling >= 0 else "onder trend, verzwakkend"
    if cyc_nu < 0.5:
        return "boven trend, stijgend (bull)" if helling >= 0 else "boven trend, afzwakkend (distributie)"
    return "ver boven trend -- top/distributie" if helling < 0 else "ver boven trend -- late bull"


def analyse(naam, serie):
    import math
    dagen = [d for d, _ in serie]
    prijs = [p for _, p in serie]
    n = len(prijs)
    cyc = cyclus_component(prijs)
    # huidige cyclus-waarde en helling (laatste 30d)
    cyc_nu = cyc[-1]
    geldig = [i for i in range(n) if cyc[i] is not None]
    helling = None
    if cyc_nu is not None and len(geldig) > 30 and cyc[-31] is not None:
        helling = cyc_nu - cyc[-31]
    # all-time high en laatste grote bodem
    ath_i = max(range(n), key=lambda i: prijs[i])
    na_ath = [i for i in range(ath_i, n)]
    bodem_i = min(na_ath, key=lambda i: prijs[i]) if na_ath else ath_i
    mnd = lambda i: (dagen[-1] - dagen[i]).days / 30.44

    print(f"\n=== {naam} ===")
    print(f"Historie: {dagen[0].date()} .. {dagen[-1].date()} ({n} dagen)")
    print(f"Nu: ${prijs[-1]:.5f}  |  ATH ${prijs[ath_i]:.5f} ({dagen[ath_i].date()}, {mnd(ath_i):.0f} mnd geleden)")
    print(f"Laagste sinds ATH: ${prijs[bodem_i]:.5f} ({dagen[bodem_i].date()}, {mnd(bodem_i):.0f} mnd geleden)")
    print(f"Vanaf ATH: {(prijs[-1]/prijs[ath_i]-1)*100:+.0f}%  |  vanaf bodem: {(prijs[-1]/prijs[bodem_i]-1)*100:+.0f}%")
    if cyc_nu is not None:
        print(f"Cyclus-positie: {cyc_nu:+.2f} log t.o.v. 365d-trend, helling 30d {helling:+.2f}"
              if helling is not None else f"Cyclus-positie: {cyc_nu:+.2f}")
        print(f"Fase: {fase_label(cyc_nu, helling or 0)}")

    # historische drift: vanuit vergelijkbare cyclus-posities, wat deed de koers +90d?
    if cyc_nu is not None:
        vergelijkbaar = []
        for i in geldig:
            if i + 90 < n and abs(cyc[i] - cyc_nu) < 0.15:
                vergelijkbaar.append(prijs[i + 90] / prijs[i] - 1)
        if len(vergelijkbaar) >= 10:
            vergelijkbaar.sort()
            med = vergelijkbaar[len(vergelijkbaar) // 2]
            p25 = vergelijkbaar[len(vergelijkbaar) // 4]
            p75 = vergelijkbaar[3 * len(vergelijkbaar) // 4]
            print(f"Historisch vanuit deze cyclus-positie, +90 dagen (n={len(vergelijkbaar)}):")
            print(f"  mediaan {med*100:+.0f}%   spreiding [{p25*100:+.0f}% .. {p75*100:+.0f}%]")
        else:
            print(f"Te weinig vergelijkbare historische posities (n={len(vergelijkbaar)}) voor een drift-schatting.")

    # halving-context (BTC-cyclus)
    laatste_halving = max(h for h in HALVINGS if h <= dagen[-1])
    mnd_na_halving = (dagen[-1] - laatste_halving).days / 30.44
    print(f"BTC-halving-cyclus: {mnd_na_halving:.0f} mnd na de halving van {laatste_halving.date()}")
    return dagen, prijs, cyc


def main():
    hbar = haal_historie("HBAR")
    btc = haal_historie("BTC")
    d_h, p_h, c_h = analyse("HBAR", hbar)
    analyse("BTC", btc)

    print("\n" + "=" * 60)
    print("LEES DIT: dit is een kompas op ~1,5 cyclus data, geen voorspelling.")
    print("De halving-context (BTC) leunt op meer cycli dan HBAR's eigen historie.")
    print("Gebruik naast eigen oordeel; de spreiding toont hoe onzeker het is.")

    if "--plot" in sys.argv:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
            ax1.semilogy(d_h, p_h, color="#1D9E75", lw=1)
            ax1.set_title("HBAR koers (log) sinds listing")
            ax1.set_ylabel("USD")
            geldig = [(d_h[i], c_h[i]) for i in range(len(c_h)) if c_h[i] is not None]
            ax2.plot([x for x, _ in geldig], [y for _, y in geldig], color="#7F77DD", lw=1)
            ax2.axhline(0, color="#888", lw=0.5)
            ax2.set_title("Cyclus-component (log-prijs minus 365d-trend) -- boven 0 = boven trend")
            ax2.set_ylabel("afwijking")
            for h in HALVINGS:
                if d_h[0] <= h <= d_h[-1]:
                    ax1.axvline(h, color="#EF9F27", ls=":", lw=1)
                    ax2.axvline(h, color="#EF9F27", ls=":", lw=1)
            pad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "cyclus_hbar.png")
            os.makedirs(os.path.dirname(pad), exist_ok=True)
            plt.tight_layout(); plt.savefig(pad, dpi=110)
            print(f"\n[plot] {pad}")
        except Exception as e:
            print(f"[plot] mislukt: {e}")


if __name__ == "__main__":
    main()
