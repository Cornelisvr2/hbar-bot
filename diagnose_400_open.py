from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import compute_amount1_for_amount0, compute_amount0_for_amount1, get_live_pool_price, tick_to_price
import asyncio
import requests

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    huidige_prijs = orchestrator.geckoterminal.get_pool_snapshot().price_usd
    wallet_hbar = orchestrator._get_swappable_hbar_balance(huidige_prijs)
    wallet_sauce = orchestrator._get_swappable_usdc_balance()
    print(f"Beschikbaar: {wallet_hbar:.4f} HBAR + {wallet_sauce:.4f} SAUCE")

    fresh_price = get_live_pool_price(
        orchestrator.rpc_client, lp.config.factory_address,
        lp.config.token0, lp.config.token1, lp.config.fee_tier,
        orchestrator._hbar_decimals, orchestrator._usdc_decimals,
    )

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
        apply_fat_tail_buffer=False,
    )
    print(f"Range: tick_lower={tick_lower}, tick_upper={tick_upper} "
          f"(breedte: {tick_upper-tick_lower} ticks)")

    balanceren_gelukt = await orchestrator._ensure_balanced_liquidity_ratio(fresh_price, tick_lower, tick_upper)
    print(f"Balanceren gelukt: {balanceren_gelukt}")
    if not balanceren_gelukt:
        print("GESTOPT -- balanceren mislukte.")
        await db.close()
        return

    hbar_balance = orchestrator._get_swappable_hbar_balance(fresh_price)
    usdc_balance = orchestrator._get_swappable_usdc_balance()
    hbar_raw_final = int(hbar_balance * (10 ** 8))
    usdc_raw_final = int(usdc_balance * (10 ** 6))
    print(f"Definitief: {hbar_raw_final/(10**8):.4f} HBAR, {usdc_raw_final/(10**6):.4f} SAUCE")

    try:
        lp.open_position(
            hbar_raw_final, usdc_raw_final, fresh_price, slippage_tolerance=0.15,
            gas_limit_override=1_200_000,
            precomputed_tick_range=(tick_lower, tick_upper),
        )
        print(f"GELUKT! Nieuwe positie: token_id={lp.state.token_id}")
        await db.save_active_lp_position(lp.state.token_id, lp.state.tick_lower, lp.state.tick_upper)
        print("Opgeslagen in de database.")
    except requests.exceptions.HTTPError as e:
        print(f"\n=== VOLLEDIGE FOUTMELDING VAN DE RPC-NODE ===")
        print(f"Statuscode: {e.response.status_code}")
        print(f"Respons-body: {e.response.text}")
    except Exception as e:
        print(f"\n=== ANDERE FOUT ===")
        print(f"{type(e).__name__}: {e}")

    await db.close()

asyncio.run(main())
