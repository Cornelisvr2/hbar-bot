from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import compute_amount1_for_amount0, compute_amount0_for_amount1
import asyncio
import traceback

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    huidige_prijs = orchestrator.geckoterminal.get_pool_snapshot().price_usd
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

    hbar_raw_available = int(hbar_balans * 0.95 * (10 ** 8))
    sauce_needed_for_all_hbar = compute_amount1_for_amount0(
        hbar_raw_available, fresh_price, tick_lower, tick_upper, 8, 6,
    )
    print(f"Voor {hbar_balans*0.95:.4f} HBAR is {sauce_needed_for_all_hbar/(10**6):.4f} SAUCE nodig")

    if sauce_needed_for_all_hbar <= sauce_balans * (10 ** 6):
        hbar_raw = hbar_raw_available
        sauce_raw = sauce_needed_for_all_hbar
    else:
        sauce_raw = int(sauce_balans * 0.95 * (10 ** 6))
        hbar_raw = compute_amount0_for_amount1(
            sauce_raw, fresh_price, tick_lower, tick_upper, 8, 6,
        )

    print(f"Correct gebalanceerd: {hbar_raw} HBAR-raw ({hbar_raw/(10**8):.4f} HBAR), {sauce_raw} SAUCE-raw ({sauce_raw/(10**6):.4f} SAUCE)")

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
