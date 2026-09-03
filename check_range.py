from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import price_to_tick
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    positie = await db.get_active_lp_position()
    huidige_prijs = orchestrator.geckoterminal.get_pool_snapshot().price_usd
    huidige_tick = price_to_tick(huidige_prijs, 8, 6)
    tick_lower = positie['tick_lower']
    tick_upper = positie['tick_upper']
    print(f'Positie: token_id={positie["token_id"]}')
    print(f'tick_lower={tick_lower}, tick_upper={tick_upper}')
    print(f'Huidige prijs: {huidige_prijs}, huidige tick: {huidige_tick}')
    print(f'Prijs BINNEN de range: {tick_lower <= huidige_tick <= tick_upper}')
    await db.close()

asyncio.run(main())
