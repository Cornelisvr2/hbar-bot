from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import get_twap_tick, get_live_pool_price, price_to_tick
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    fresh_price = get_live_pool_price(
        orchestrator.rpc_client, lp.config.factory_address,
        lp.config.token0, lp.config.token1, lp.config.fee_tier,
        orchestrator._hbar_decimals, orchestrator._usdc_decimals,
    )
    huidige_tick = price_to_tick(fresh_price, orchestrator._hbar_decimals, orchestrator._usdc_decimals)
    print(f'Huidige prijs: {fresh_price}, huidige tick: {huidige_tick}')

    twap_tick = get_twap_tick(
        orchestrator.rpc_client, lp.config.factory_address,
        lp.config.token0, lp.config.token1, lp.config.fee_tier, seconds_ago=300,
    )
    print(f'5-minuten-TWAP-tick: {twap_tick}')
    print(f'Afwijking: {abs(huidige_tick - twap_tick)} ticks (drempel: 50)')

    resultaat = orchestrator._check_price_oracle_divergence(huidige_tick)
    print(f"_check_price_oracle_divergence(): {resultaat} (moet True zijn bij normale marktomstandigheden)")

    await db.close()

asyncio.run(main())
