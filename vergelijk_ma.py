"""
vergelijk_ma.py -- MA50 vs MA100 vs MA200 voor de pool<->HBAR-strategie.

Beantwoordt: pakt een SNELLERE trend-trigger de bull vroeger mee (meer
muntjes), of kosten de valse starts dat weer op? Draait de bestaande
muntjes-simulatie (backtest_muntjes.run) met drie MA-vensters, in muntjes,
met EUR 2000 start + EUR 100/maand.

    docker compose run --rm -T hbar-bot python3 vergelijk_ma.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def main():
    from postgres_client import PostgresClient
    from backtest_muntjes import dagreeks, run
    db = PostgresClient()
    await db.connect()
    async with db._pool.acquire() as conn:
        rows = await conn.fetch("SELECT ts, close FROM candles_5m WHERE symbol='HBAR' ORDER BY ts")
    dagen, prijs = dagreeks(rows)
    start, maand, fee, apr = 2000.0, 100.0, 0.008, 22.0

    # referenties
    hold_m, gestort = run(dagen, prijs, start, maand, fee, apr, "hold")
    pool_m, _ = run(dagen, prijs, start, maand, fee, apr, "pool")
    print(f"\nMA-vergelijking (muntjes), {dagen[0]} .. {dagen[-1]}")
    print(f"EUR {start:.0f} + EUR {maand:.0f}/mnd | koers ${prijs[0]:.4f} -> ${prijs[-1]:.4f}\n")
    print(f"  {'aanpak':22s} {'muntjes':>10s} {'vs hold':>9s} {'swaps~':>7s}")
    print(f"  {'HBAR vasthouden':22s} {hold_m:>10.0f} {'  0.0%':>9s} {'-':>7s}")
    print(f"  {'altijd pool':22s} {pool_m:>10.0f} {(pool_m/hold_m-1)*100:+8.1f}% {'-':>7s}")
    for ma in (50, 100, 200):
        for bev in (2, 7):
            munt, _ = run(dagen, prijs, start, maand, fee, apr, "poolhbar", bevestiging=bev, ma_dagen=ma)
            print(f"  pool<->HBAR MA{ma:<3d} bev{bev:<2d}   {munt:>10.0f} {(munt/hold_m-1)*100:+8.1f}%")
    print("\nLees: hoger dan 'altijd pool' = de trend-schakeling voegt muntjes toe.")
    print("Snellere MA (50) pakt de bull eerder maar riskeert valse starts;")
    print("de tabel laat zien of dat per saldo wint. EEN cyclus data.")


if __name__ == "__main__":
    asyncio.run(main())
