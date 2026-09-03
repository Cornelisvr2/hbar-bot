# hourly_snapshot.py
#
# Elk uur een portefeuille-waarde-snapshot opslaan (1 sep 2026, op
# verzoek: fijnmaziger grafiek op het dashboard dan de 1x-per-dag-
# snapshot van daily_status_report.py). Bewust GEEN Telegram-bericht --
# dat zou elk uur spam geven. Hergebruikt fetch_dashboard_data() (dus
# exact dezelfde, al-geverifieerde berekening als het Telegram-rapport
# en het dashboard zelf).

import asyncio

from bot_data import fetch_dashboard_data
from postgres_client import PostgresClient


async def main():
    db = PostgresClient()
    await db.connect()
    try:
        data = await fetch_dashboard_data(db)
        await db.save_portfolio_value_snapshot(
            data["total_value_usd"], data["wallet"]["value_usd"],
            data["position"]["value_usd"] if data["position"] else 0.0,
        )
        print(f"Snapshot opgeslagen: ${data['total_value_usd']:.2f}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
