from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import compute_amount1_for_amount0, compute_amount0_for_amount1, get_live_pool_price, tick_to_price
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    huidige_prijs = orchestrator.geckoterminal.get_pool_snapshot().price_usd
    hbar_balans = orchestrator._get_swappable_hbar_balance(huidige_prijs)
    sauce_balans = orchestrator._get_swappable_usdc_balance()
    print(f"Beschikbaar: {hbar_balans} HBAR, {sauce_balans} SAUCE")

    fresh_price = get_live_pool_price(
        orchestrator.rpc_client, lp.config.factory_address,
        lp.config.token0, lp.config.token1, lp.config.fee_tier,
        orchestrator._hbar_decimals, orchestrator._usdc_decimals,
    )
    print(f"Pool-eigen prijs: {fresh_price}")

    from safety_override import compute_fixed_combined_score, compute_combined_volatility_sigma
    from gbm_range_model import apply_regime_bias
    combined_score_now = compute_fixed_combined_score(orchestrator._cached_btc_score, orchestrator._cached_hbar_score)
    combined_volatility_sigma_now = compute_combined_volatility_sigma(
        orchestrator._cached_btc_volatility_sigma, orchestrator._cached_hbar_volatility_sigma
    )
    combined_volatility_sigma_now = min(1.0, combined_volatility_sigma_now * orchestrator._volatility_calibration_factor)
    combined_score_now = apply_regime_bias(combined_score_now, orchestrator._cached_macro_regime)

    tick_lower, tick_upper = lp.compute_range_via_gbm(
        fresh_price, combined_score_now, combined_volatility_sigma_now,
        orchestrator._cached_hourly_volatility,
        macro_regime=orchestrator._cached_macro_regime,
        confidence_level=orchestrator._determine_gbm_confidence_level(combined_score_now),
    )
    print(f"Actuele, live GBM-range: tick_lower={tick_lower}, tick_upper={tick_upper}")

    hbar_raw_available = int(hbar_balans * 0.95 * (10 ** 8))
    sauce_needed_for_all_hbar = compute_amount1_for_amount0(
        hbar_raw_available, fresh_price, tick_lower, tick_upper, 8, 6,
    )

    if sauce_needed_for_all_hbar <= sauce_balans * (10 ** 6):
        hbar_raw = hbar_raw_available
        sauce_raw = sauce_needed_for_all_hbar
    else:
        sauce_raw = int(sauce_balans * 0.95 * (10 ** 6))
        hbar_raw = compute_amount0_for_amount1(
            sauce_raw, fresh_price, tick_lower, tick_upper, 8, 6,
        )

    print(f"Gebalanceerd: {hbar_raw/(10**8):.4f} HBAR, {sauce_raw/(10**6):.4f} SAUCE")
    print("Positie wordt nu geopend...")

    lp.open_position(
        hbar_raw, sauce_raw, fresh_price, slippage_tolerance=0.15,
        gas_limit_override=1_200_000,
        precomputed_tick_range=(tick_lower, tick_upper),
    )
    print(f"GELUKT! token_id={lp.state.token_id}")

    await db.save_active_lp_position(lp.state.token_id, lp.state.tick_lower, lp.state.tick_upper)
    print("Opgeslagen in de database.")

    await db.close()

asyncio.run(main())
