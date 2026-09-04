from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import compute_amount0_for_amount1, get_live_pool_price, price_to_tick, nearest_usable_tick
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager

    print("=== Stap 1: uitgangssituatie ===")
    if lp.state.is_open:
        print("Er is al een actieve positie -- gestopt.")
        await db.close()
        return

    # KORREKT: lp.config.token0_decimals/token1_decimals gebruiken,
    # matchend met lp.config.token0/token1 (4 sep 2026, na de dubbele
    # bugfix-ronde van vandaag).
    fresh_price = get_live_pool_price(
        orchestrator.rpc_client, lp.config.factory_address,
        lp.config.token0, lp.config.token1, lp.config.fee_tier,
        lp.config.token0_decimals, lp.config.token1_decimals,
    )
    print(f"Prijs, in token1-per-token0-conventie (token0={lp.config.token0}): {fresh_price}")

    # Voor de HBAR-per-USD-conventie die de rest van dit script gebruikt
    # (amount0=HBAR, amount1=USDC, zoals overal elders in de codebase):
    # als token0 toevallig USDC is (mainnet), moet dit geinverteerd worden.
    if lp.config.token0.lower() == lp.config.whbar_address.lower():
        prijs_usdc_per_hbar = fresh_price
    else:
        prijs_usdc_per_hbar = 1.0 / fresh_price
    print(f"Prijs in USDC per HBAR (mens-conventie): {prijs_usdc_per_hbar:.6f}")

    print("\n=== Stap 2: kleine, symmetrische range rond de huidige prijs ===")
    prijs_onder = prijs_usdc_per_hbar * 0.95
    prijs_boven = prijs_usdc_per_hbar * 1.05
    tick_lower = nearest_usable_tick(
        price_to_tick(prijs_onder, 8, orchestrator._usdc_decimals), lp.tick_spacing
    )
    tick_upper = nearest_usable_tick(
        price_to_tick(prijs_boven, 8, orchestrator._usdc_decimals), lp.tick_spacing
    )
    print(f"Range: {prijs_onder:.6f} -- {prijs_boven:.6f} (ticks: {tick_lower} -- {tick_upper})")

    print("\n=== Stap 3: beschikbare, kleine bedragen ===")
    usdc_balance = orchestrator._get_swappable_usdc_balance()
    print(f"Beschikbare USDC: {usdc_balance:.4f}")
    usdc_raw = int(usdc_balance * 0.95 * (10 ** orchestrator._usdc_decimals))
    hbar_raw = compute_amount0_for_amount1(
        usdc_raw, prijs_usdc_per_hbar, tick_lower, tick_upper, 8, orchestrator._usdc_decimals,
    )
    print(f"Gebruikt: {hbar_raw/(10**8):.4f} HBAR + {usdc_raw/(10**orchestrator._usdc_decimals):.4f} USDC")

    if hbar_raw <= 0:
        print("\nWAARSCHUWING: berekende HBAR-inzet is 0 of negatief -- iets klopt niet. GESTOPT.")
        await db.close()
        return

    print("\n=== Stap 4: positie openen ===")
    lp.open_position(
        hbar_raw, usdc_raw, prijs_usdc_per_hbar, slippage_tolerance=0.05,
        gas_limit_override=1_200_000,
        precomputed_tick_range=(tick_lower, tick_upper),
    )
    print(f"GELUKT! token_id={lp.state.token_id}")
    await db.save_active_lp_position(lp.state.token_id, lp.state.tick_lower, lp.state.tick_upper)

    await db.close()

asyncio.run(main())
