from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import compute_amount1_for_amount0, compute_amount0_for_amount1, get_live_pool_price, tick_to_price
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    print("=" * 60)
    print("STAP 1: Uitgangssituatie")
    print("=" * 60)
    huidige_prijs = orchestrator.geckoterminal.get_pool_snapshot().price_usd
    wallet_hbar_voor = orchestrator._get_swappable_hbar_balance(huidige_prijs)
    wallet_sauce_voor = orchestrator._get_swappable_usdc_balance()
    totaal_hbar_raw = float(orchestrator.rpc_client.get_hbar_balance())
    print(f"Totale, werkelijke HBAR-balans (incl. reserve): {totaal_hbar_raw:.4f}")
    print(f"Beschikbaar voor inzet (na 50 HBAR-reserve): {wallet_hbar_voor:.4f} HBAR + {wallet_sauce_voor:.4f} SAUCE")

    if lp.state.is_open:
        print("WAARSCHUWING: er staat al een actieve positie -- dit script is bedoeld voor de situatie zonder positie. Gestopt.")
        await db.close()
        return

    fresh_price = get_live_pool_price(
        orchestrator.rpc_client, lp.config.factory_address,
        lp.config.token0, lp.config.token1, lp.config.fee_tier,
        orchestrator._hbar_decimals, orchestrator._usdc_decimals,
    )

    print("\n" + "=" * 60)
    print("STAP 2: Verse, symmetrische range berekenen")
    print("=" * 60)
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
    print(f"Range: {prijs_onder:.4f} -- {prijs_boven:.4f}")
    print(f"Huidige prijs staat op {positie_pct:.1f}% in deze range")

    if positie_pct < 20 or positie_pct > 80:
        print(f"\nWAARSCHUWING: {positie_pct:.1f}% is behoorlijk scheef -- dit zou opnieuw een groot deel "
              f"van het kapitaal ongebruikt kunnen laten. NIET automatisch doorgegaan -- eerst overleggen.")
        await db.close()
        return

    print("\nRange ziet er goed uit (redelijk gecentreerd) -- doorgaan met de daadwerkelijke test.")

    print("\n" + "=" * 60)
    print("STAP 3: Balanceren (echte swap)")
    print("=" * 60)
    balanceren_gelukt = await orchestrator._ensure_balanced_liquidity_ratio(fresh_price, tick_lower, tick_upper)
    print(f"Balanceren gelukt: {balanceren_gelukt}")
    if not balanceren_gelukt:
        print("GESTOPT -- balanceren mislukte.")
        await db.close()
        return

    print("\n" + "=" * 60)
    print("STAP 4: Positie openen (echte mint)")
    print("=" * 60)
    hbar_balance = orchestrator._get_swappable_hbar_balance(fresh_price)
    usdc_balance = orchestrator._get_swappable_usdc_balance()
    hbar_raw_final = int(hbar_balance * (10 ** 8))
    usdc_raw_final = int(usdc_balance * (10 ** 6))
    print(f"Poging met: {hbar_raw_final/(10**8):.4f} HBAR, {usdc_raw_final/(10**6):.4f} SAUCE")

    lp.open_position(
        hbar_raw_final, usdc_raw_final, fresh_price, slippage_tolerance=0.15,
        gas_limit_override=1_200_000,
        precomputed_tick_range=(tick_lower, tick_upper),
    )
    print(f"GELUKT! Nieuwe positie: token_id={lp.state.token_id}")
    await db.save_active_lp_position(lp.state.token_id, lp.state.tick_lower, lp.state.tick_upper)
    print("Opgeslagen in de database.")

    print("\n" + "=" * 60)
    print("STAP 5: VERIFICATIE -- hoeveel HBAR bleef onbenut over?")
    print("=" * 60)
    totaal_hbar_raw_na = float(orchestrator.rpc_client.get_hbar_balance())
    print(f"Totale, werkelijke HBAR-balans NA het openen: {totaal_hbar_raw_na:.4f}")
    print(f"Verwachte reserve: ~50 HBAR")
    verschil = totaal_hbar_raw_na - 50.0
    if abs(verschil) < 100:
        print(f"BEVESTIGD: dicht bij de verwachte 50 HBAR-reserve (verschil: {verschil:+.2f} HBAR) -- "
              f"vrijwel al het kapitaal is correct ingezet.")
    else:
        print(f"LET OP: {verschil:+.2f} HBAR MEER dan de verwachte reserve -- er bleef significant "
              f"kapitaal onbenut. De directe restkapitaal-bijstorting (van eerder vandaag) zou dit "
              f"nu automatisch moeten oppikken -- laten we een aparte check draaien om te bevestigen.")

    await db.close()

asyncio.run(main())
