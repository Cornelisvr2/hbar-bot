from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import get_live_pool_price
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    await orchestrator._reconcile_lp_position_on_startup()
    lp = orchestrator.lp_manager

    if not lp.state.is_open:
        print('Geen open positie gevonden.')
        await db.close()
        return

    print(f'Open positie: token_id={lp.state.token_id}, tick_lower={lp.state.tick_lower}, tick_upper={lp.state.tick_upper}')

    huidige_prijs = orchestrator.geckoterminal.get_pool_snapshot().price_usd
    hbar_balance = orchestrator._get_swappable_hbar_balance(huidige_prijs)
    usdc_balance = orchestrator._get_swappable_usdc_balance()
    print(f'Direct vóór balanceren: {hbar_balance} HBAR beschikbaar, {usdc_balance} SAUCE beschikbaar')

    await db.close()

asyncio.run(main())
