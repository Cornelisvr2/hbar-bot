from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import compute_amount1_for_amount0, compute_amount0_for_amount1, get_live_pool_price
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

    # Actuele GBM-range LIVE herberekenen (i.p.v. een verouderde,
    # vastgezette waarde uit eerdere logs) -- zelfde aanpak/parameters
    # als de bot zelf gebruikt.
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

    from lp_manager import tick_to_price
    prijs_onder = tick_to_price(tick_lower, 8, 6)
    prijs_boven = tick_to_price(tick_upper, 8, 6)
    print(f"Range in prijstermen: {prijs_onder:.4f} -- {prijs_boven:.4f} (huidige pool-prijs: {fresh_price:.4f})")
    positie_pct = (fresh_price - prijs_onder) / (prijs_boven - prijs_onder) * 100
    print(f"Huidige prijs staat op {positie_pct:.1f}% in deze range")

    hbar_raw_available = int(hbar_balans * 0.95 * (10 ** 8))
    sauce_needed_for_all_hbar = compute_amount1_for_amount0(
        hbar_raw_available, fresh_price, tick_lower, tick_upper, 8, 6,
    )
    print(f"Voor {hbar_balans*0.95:.4f} HBAR is {sauce_needed_for_all_hbar/(10**6):.4f} SAUCE nodig")

    if sauce_needed_for_all_hbar <= sauce_balans * (10 ** 6):
        hbar_raw = hbar_raw_available
        sauce_raw = sauce_needed_for_all_hbar
        print("HBAR is de beperkende kant.")
    else:
        sauce_raw = int(sauce_balans * 0.95 * (10 ** 6))
        hbar_raw = compute_amount0_for_amount1(
            sauce_raw, fresh_price, tick_lower, tick_upper, 8, 6,
        )
        print("SAUCE is de beperkende kant.")

    print(f"Correct gebalanceerd: {hbar_raw/(10**8):.4f} HBAR, {sauce_raw/(10**6):.4f} SAUCE")
    print("NOG NIET GEOPEND -- alleen berekend.")

    await db.close()

asyncio.run(main())
