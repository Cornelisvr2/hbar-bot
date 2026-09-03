"""
analyze_trades_with_context.py

Koppelt elke trade aan de strategy_signal (sentiment-score + redenering)
die 'm veroorzaakte -- mogelijk gemaakt door de signal_id-koppeling die
op 26 aug 2026 is toegevoegd (voorheen altijd None, dus nooit gekoppeld).
"""

import asyncio
from postgres_client import PostgresClient


async def main():
    db = PostgresClient()
    await db.connect()

    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                t.created_at, t.direction AS trade_direction, t.amount_in,
                t.estimated_amount_out, t.status, t.tx_hash,
                s.direction AS signal_direction, s.confidence,
                s.btc_score, s.hbar_score, s.reasoning
            FROM trades t
            LEFT JOIN strategy_signals s ON t.strategy_signal_id = s.id
            ORDER BY t.created_at DESC
            LIMIT 20
            """
        )

    if not rows:
        print("Nog geen trades gelogd.")
        await db.close()
        return

    linked = sum(1 for r in rows if r["signal_direction"] is not None)
    print(f"=== Trades met sentiment-context ({len(rows)} recentste, {linked} gekoppeld) ===\n")

    for r in rows:
        print(f"[{r['created_at']}] {r['status'].upper():8} {r['trade_direction']:15} "
              f"in={r['amount_in']:.4f}")
        if r["signal_direction"]:
            print(f"    Veroorzaakt door: {r['signal_direction']} "
                  f"(confidence={r['confidence']:.2f}, btc={r['btc_score']:+.2f}, "
                  f"hbar={r['hbar_score']:+.2f})")
            print(f"    Redenering: {r['reasoning']}")
        else:
            print("    Geen gekoppeld signaal (trade van vóór de signal_id-fix, of "
                  "een niet-regime-gedreven actie zoals LP-herbalancering)")
        print()

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
