from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    huidige_prijs = orchestrator.geckoterminal.get_pool_snapshot().price_usd
    print(f'Huidige prijs: {huidige_prijs}')

    orchestrator.lp_manager.state.is_open = True
    orchestrator.lp_manager.state.tick_lower = -8160
    orchestrator.lp_manager.state.tick_upper = -5160

    buiten_bereik = orchestrator.lp_manager.is_price_out_of_range(huidige_prijs)
    print(f'is_price_out_of_range() voor positie 347s range (-8160/-5160): {buiten_bereik}')
    await db.close()

asyncio.run(main())
