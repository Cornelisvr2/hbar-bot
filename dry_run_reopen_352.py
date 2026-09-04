from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import compute_amount1_for_amount0, compute_amount0_for_amount1, get_live_pool_price, tick_to_price
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    # Huidige positie 352's eigen HBAR/SAUCE (komt terug bij sluiten)
    from bot_data import V2_POSITION_MANAGER_ABI
    position_manager = orchestrator.rpc_client.w3.eth.contract(
        address=lp.config.position_manager_address, abi=V2_POSITION_MANAGER_ABI
    )
    on_chain = position_manager.functions.positions(352).call()
    print(f"Positie 352 on-chain, liquidity={on_chain[5]}")

    huidige_prijs = orchestrator.geckoterminal.get_pool_snapshot().price_usd
    wallet_hbar = orchestrator._get_swappable_hbar_balance(huidige_prijs)
    wallet_sauce = orchestrator._get_swappable_usdc_balance()
    print(f"Huidig, los in de wallet: {wallet_hbar:.4f} HBAR + {wallet_sauce:.4f} SAUCE")

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
        apply_fat_tail_buffer=False,
    )
    prijs_onder = tick_to_price(tick_lower, 8, 6)
    prijs_boven = tick_to_price(tick_upper, 8, 6)
    positie_pct = (fresh_price - prijs_onder) / (prijs_boven - prijs_onder) * 100
    print(f"\nVerse, symmetrische range: {prijs_onder:.4f} -- {prijs_boven:.4f}")
    print(f"Huidige prijs staat op {positie_pct:.1f}% in deze range")

    # NB: dit berekent uitsluitend met het HUIDIGE, LOSSE wallet-saldo --
    # het bedrag dat terugkomt bij het sluiten van 352 is nog niet
    # meegenomen (dat weten we pas na het daadwerkelijk sluiten).
    hbar_raw_beschikbaar = int(wallet_hbar * 0.95 * (10 ** 8))
    sauce_nodig_voor_alle_hbar = compute_amount1_for_amount0(
        hbar_raw_beschikbaar, fresh_price, tick_lower, tick_upper, 8, 6,
    )
    print(f"\nVoor {wallet_hbar*0.95:.4f} HBAR (alleen het huidige, losse deel) is "
          f"{sauce_nodig_voor_alle_hbar/(10**6):.4f} SAUCE nodig")
    print("(Na het sluiten van 352 komt daar nog HBAR + SAUCE bovenop uit de oude positie zelf --")
    print(" dit dry-run-script rekent nog niet met dat extra bedrag, dat gebeurt in het echte script.)")

    await db.close()

asyncio.run(main())
