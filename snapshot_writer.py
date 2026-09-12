"""
snapshot_writer.py -- fase 1 lees-architectuur (12 sep 2026).

Draait de bestaande, bewezen _build_dashboard_context() (dezelfde berekening
die het dashboard nu bij elke pageload deed) en schrijft het resultaat als
JSON naar dashboard_snapshots. Het dashboard leest voortaan die tabel i.p.v.
zelf live GeckoTerminal/Mirror Node te bevragen -> instant laden.

Hergebruikt de context-functie 1-op-1, dus GEEN afwijkende cijfers.

Draaien:
  # eenmalig (test):
  docker compose run --rm -T dashboard python3 snapshot_writer.py --once
  # als lus (elke N seconden), bv. via een aparte service of nohup:
  docker compose run --rm -T dashboard python3 snapshot_writer.py --loop 300
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BEWAAR_DAGEN = 30


async def schrijf_snapshot():
    from dashboard_server import _build_dashboard_context_live
    from postgres_client import PostgresClient
    ctx = await _build_dashboard_context_live()
    # datetime/Decimal e.d. veilig serialiseren
    payload = json.dumps(ctx, default=str)
    db = PostgresClient()
    await db.connect()
    try:
        async with db._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO dashboard_snapshots (payload) VALUES ($1::jsonb)", payload)
            # opruimen: oude snapshots weg
            await conn.execute(
                "DELETE FROM dashboard_snapshots WHERE ts < now() - ($1 || ' days')::interval",
                str(BEWAAR_DAGEN))
    finally:
        await db.close()
    return len(payload)


async def main():
    a = sys.argv
    if "--loop" in a:
        interval = int(a[a.index("--loop") + 1])
        print(f"[snapshot] lus gestart, elke {interval}s")
        while True:
            try:
                n = await schrijf_snapshot()
                print(f"[snapshot] geschreven ({n} bytes) {time.strftime('%H:%M:%S')}")
            except Exception as e:
                print(f"[snapshot] FOUT: {e}")
            await asyncio.sleep(interval)
    else:
        n = await schrijf_snapshot()
        print(f"[snapshot] eenmalig geschreven ({n} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
