from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio
import traceback

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    if not lp:
        print("FOUT: lp_manager niet opgezet.")
        await db.close()
        return

    huidige_prijs = orchestrator.geckoterminal.get_pool_snapshot().price_usd
    print(f"Huidige GeckoTerminal-prijs: {huidige_prijs}")

    hbar_balans = orchestrator._get_swappable_hbar_balance(huidige_prijs)
    sauce_balans = orchestrator._get_swappable_usdc_balance()
    print(f"Beschikbaar: {hbar_balans} HBAR, {sauce_balans} SAUCE")

    from lp_manager import get_live_pool_price
    fresh_price = get_live_pool_price(
        orchestrator.rpc_client, lp.config.factory_address,
        lp.config.token0, lp.config.token1, lp.config.fee_tier,
        orchestrator._hbar_decimals, orchestrator._usdc_decimals,
    )
    print(f"Pool-eigen prijs: {fresh_price}")

    tick_lower, tick_upper = lp.compute_range_via_gbm(
        fresh_price, 0.10, 0.5, orchestrator._cached_hourly_volatility,
    )
    print(f"Berekende range: tick_lower={tick_lower}, tick_upper={tick_upper}")

    hbar_raw = int(hbar_balans * 0.9 * (10 ** 8))
    sauce_raw = int(sauce_balans * 0.9 * (10 ** 6))
    print(f"Poging tot openen met: {hbar_raw} HBAR-raw, {sauce_raw} SAUCE-raw")

    try:
        lp.open_position(
            hbar_raw, sauce_raw, fresh_price, slippage_tolerance=0.15,
            gas_limit_override=1_200_000,
            precomputed_tick_range=(tick_lower, tick_upper),
        )
        print("GELUKT!")
    except Exception as e:
        print(f"\n=== VOLLEDIGE FOUTMELDING ===")
        traceback.print_exc()

    await db.close()

asyncio.run(main())
