"""
analyze_trades.py

Overzicht van alle geloogde trades in de trades-tabel: succespercentage,
volume per richting, en gekoppelde regime-overgangen. Dit is de eerste
stap richting analyse -- ECHTE winst/verlies-berekening vereist nog
steeds prijsdata rond elk trade-moment (zie de aantekening onderaan).
"""

import asyncio
from postgres_client import PostgresClient


async def main():
    db = PostgresClient()
    await db.connect()

    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT direction, engine, network, amount_in, estimated_amount_out, "
            "tx_hash, status, created_at FROM trades ORDER BY created_at"
        )

    if not rows:
        print("Nog geen trades gelogd.")
        await db.close()
        return

    total = len(rows)
    successful = sum(1 for r in rows if r["status"] == "success")
    failed = total - successful

    print(f"=== Trade-overzicht ({total} totaal) ===")
    print(f"Succesvol: {successful} ({successful/total*100:.1f}%)")
    print(f"Mislukt: {failed} ({failed/total*100:.1f}%)")

    volume_by_direction = {}
    for r in rows:
        d = r["direction"]
        volume_by_direction.setdefault(d, {"count": 0, "amount_in_sum": 0.0})
        volume_by_direction[d]["count"] += 1
        volume_by_direction[d]["amount_in_sum"] += float(r["amount_in"] or 0)

    print("\n=== Volume per richting ===")
    for direction, stats in volume_by_direction.items():
        print(f"{direction}: {stats['count']}x, totaal amount_in={stats['amount_in_sum']:.4f}")

    print("\n=== Meest recente 10 trades ===")
    for r in rows[-10:]:
        est_out = f"{r['estimated_amount_out']:.4f}" if r["estimated_amount_out"] else "onbekend"
        tx = r["tx_hash"][:12] + "..." if r["tx_hash"] else "geen tx_hash"
        print(f"  [{r['created_at']}] {r['status'].upper():8} {r['direction']:15} "
              f"in={r['amount_in']:.4f} geschat_uit={est_out} tx={tx}")

    print(
        "\nLET OP: dit is nog geen echte winst/verlies-analyse -- daarvoor is "
        "prijsdata nodig rond elk trade-moment (vergelijkbaar met "
        "recalibrate_from_live_history.py's Binance-koers-opzoeking), om de "
        "waarde bij instap te vergelijken met de waarde bij exit. Dat is een "
        "logische vervolgstap zodra er genoeg trades zijn om iets zinnigs "
        "te berekenen."
    )

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
