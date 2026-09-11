"""
backtest_momentum.py -- meerijden met nieuwsgedreven momentum, via de KOERS.

Idee (11 sep 2026): niet reageren op nieuwskoppen (die lopen achter de koers
aan -- bewezen nul voorspelkracht), maar op het EFFECT ervan: een plotselinge
opwaartse koers+volume-uitbraak. Dat is het moment waarop een echte
nieuwsschok zichtbaar wordt, en het signaal bestaat op het moment dat je
handelt (anders dan een kop die de beweging al beschrijft).

Regel:
  - INSTAP naar HBAR als: rendement over LOOKBACK candles >= INSTAP_PCT
    EN volume >= VOL_FACTOR x het recente gemiddelde (uitbraak, niet drift).
  - VASTHOUDEN zolang de koers boven een meelopende stop (hoogste close sinds
    instap * (1 - TRAIL)) blijft.
  - UITSTAP terug naar de pool als de trailing stop raakt.
Ook NEERWAARTS: scherpe daling + volumepiek -> naar USDC (klap ontwijken),
terug naar de pool zodra de koers stabiliseert. Grondstand = pool (fees).

Vergelijkt met altijd-pool en altijd-HBAR. Toont ook per trade het resultaat,
zodat je ziet of het een paar goede uitbraken pakt of alleen fees verbrandt.

    docker compose run --rm -T hbar-bot python3 backtest_momentum.py
    docker compose run --rm -T hbar-bot python3 backtest_momentum.py --instap 5 --vol 2 --trail 8 --lookback 6
    docker compose run --rm -T hbar-bot python3 backtest_momentum.py --grid
"""
import asyncio
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

INLEG = 2000.0


async def laad():
    from postgres_client import PostgresClient
    db = PostgresClient()
    await db.connect()
    async with db._pool.acquire() as conn:
        rows = await conn.fetch("SELECT ts, close, volume FROM candles_5m WHERE symbol='HBAR' ORDER BY ts")
    # naar uur-candles (12x 5min) voor rustiger signaal
    uur = []
    blok = []
    for r in rows:
        blok.append(r)
        if len(blok) == 12:
            uur.append({"ts": blok[0]["ts"], "close": blok[-1]["close"],
                        "volume": sum(x["volume"] for x in blok)})
            blok = []
    return uur


MIN_USDC_UREN = 12   # minimale afkoeltijd in USDC na een neerwaartse uitbraak


def simuleer(candles, instap_pct, vol_factor, trail, lookback, fee, apr):
    n = len(candles)
    c = [x["close"] for x in candles]
    v = [x["volume"] for x in candles]
    dag_apr = apr / 100 / (365 * 24)   # per uur
    pool = INLEG
    hbar = 0.0
    usdc = 0.0
    stand = "POOL"        # POOL | HBAR | USDC
    top_sinds_instap = 0.0
    instap_prijs = 0.0
    usdc_sinds = 0
    swaps = 0
    trades = []
    for i in range(n):
        if stand == "POOL" and i > 0:
            ret = c[i] / c[i - 1]
            il = 2 * math.sqrt(ret) / (1 + ret)
            pool = pool * il * (1 + dag_apr * 0.70)
        if i < lookback + 24:
            continue
        rendement = c[i] / c[i - lookback] - 1
        vol_gem = sum(v[i - 24:i]) / 24
        vol_piek = v[i] >= vol_factor * vol_gem
        op_uitbraak = rendement >= instap_pct and vol_piek
        neer_uitbraak = rendement <= -instap_pct and vol_piek

        if stand == "POOL":
            if op_uitbraak:
                w = pool * (1 - fee); hbar = w / c[i]; pool = 0.0; stand = "HBAR"
                top_sinds_instap = c[i]; instap_prijs = c[i]; swaps += 1
            elif neer_uitbraak:
                w = pool * (1 - fee); usdc = w; pool = 0.0; stand = "USDC"
                usdc_sinds = i; swaps += 1
        elif stand == "HBAR":
            top_sinds_instap = max(top_sinds_instap, c[i])
            if neer_uitbraak:
                w = hbar * c[i] * (1 - fee); trades.append((c[i] / instap_prijs - 1) * 100)
                usdc = w; hbar = 0.0; stand = "USDC"; usdc_sinds = i; swaps += 1
            elif c[i] <= top_sinds_instap * (1 - trail):
                w = hbar * c[i] * (1 - fee); trades.append((c[i] / instap_prijs - 1) * 100)
                pool = w; hbar = 0.0; stand = "POOL"; swaps += 1
        elif stand == "USDC":
            gestabiliseerd = (i - usdc_sinds) >= MIN_USDC_UREN and c[i] > c[i - 1]
            if gestabiliseerd:
                w = usdc * (1 - fee); pool = w; usdc = 0.0; stand = "POOL"; swaps += 1

    eind = pool + hbar * c[-1] + usdc
    return eind, swaps, trades


async def main():
    a = sys.argv
    instap = float(a[a.index("--instap") + 1]) / 100 if "--instap" in a else 0.05
    vol = float(a[a.index("--vol") + 1]) if "--vol" in a else 2.0
    trail = float(a[a.index("--trail") + 1]) / 100 if "--trail" in a else 0.08
    lookback = int(a[a.index("--lookback") + 1]) if "--lookback" in a else 6
    fee = float(a[a.index("--fee") + 1]) / 100 if "--fee" in a else 0.008
    apr = float(a[a.index("--apr") + 1]) if "--apr" in a else 22.0

    candles = await laad()
    c = [x["close"] for x in candles]
    hold = INLEG * (c[-1] / c[0])
    print(f"\nMomentum-uitbraak op HBAR, {candles[0]['ts'].date()} .. {candles[-1]['ts'].date()} ({len(candles)} uur-candles)")
    print(f"HBAR ${c[0]:.5f} -> ${c[-1]:.5f} ({(c[-1]/c[0]-1)*100:+.0f}%)")
    print(f"Referenties: altijd-HBAR €{hold:.0f} · altijd-pool ~€2577\n")

    if "--grid" in a:
        print(f"  {'instap':>7s} {'vol':>4s} {'trail':>6s} {'look':>5s}   {'eind €':>8s} {'trades':>7s} {'winst%':>7s}")
        beste = None
        for ins in (0.03, 0.05, 0.08):
            for vf in (1.5, 2.0, 3.0):
                for tr in (0.06, 0.10):
                    eind, swaps, trades = simuleer(candles, ins, vf, tr, lookback, fee, apr)
                    win = (sum(1 for t in trades if t > 0) / len(trades) * 100) if trades else 0
                    if beste is None or eind > beste[0]:
                        beste = (eind, ins, vf, tr)
                    print(f"  {ins*100:6.0f}% {vf:4.1f} {tr*100:5.0f}% {lookback:>5d}   €{eind:7.0f} {len(trades):>7d} {win:>6.0f}%")
        print(f"\nBeste: instap {beste[1]*100:.0f}%, vol {beste[2]}x, trail {beste[3]*100:.0f}% -> €{beste[0]:.0f}")
    else:
        eind, swaps, trades = simuleer(candles, instap, vol, trail, lookback, fee, apr)
        win = (sum(1 for t in trades if t > 0) / len(trades) * 100) if trades else 0
        print(f"  Momentum-strategie €{eind:.0f}  ({(eind/INLEG-1)*100:+.0f}%)")
        print(f"  {len(trades)} trades, {win:.0f}% winstgevend, {swaps} swaps")
        print(f"  instap>={instap*100:.0f}% over {lookback}u, volume>={vol}x, trailing {trail*100:.0f}%")
        if trades:
            print(f"  beste trade {max(trades):+.0f}%, slechtste {min(trades):+.0f}%, gemiddeld {sum(trades)/len(trades):+.1f}%")
        print(f"\n  vs kale pool (€2577): {(eind/2577-1)*100:+.0f}%   vs altijd-HBAR: {(eind/hold-1)*100:+.0f}%")


if __name__ == "__main__":
    asyncio.run(main())
