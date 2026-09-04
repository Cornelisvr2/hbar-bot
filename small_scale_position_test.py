from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
from lp_manager import compute_amount1_for_amount0, get_live_pool_price, tick_to_price
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

    fresh_price = get_live_pool_price(
        orchestrator.rpc_client, lp.config.factory_address,
        lp.config.token0, lp.config.token1, lp.config.fee_tier,
        8, orchestrator._usdc_decimals,
    )
    print(f"Actuele, on-chain prijs: {fresh_price:.6f}")

    print("\n=== Stap 2: kleine, symmetrische range rond de huidige prijs ===")
    # Simpele, brede range (+-5%) i.p.v. de volledige GBM-berekening --
    # dit is een mechaniek-test, geen strategische positie.
    prijs_onder = fresh_price * 0.95
    prijs_boven = fresh_price * 1.05
    from lp_manager import price_to_tick, nearest_usable_tick
    tick_lower = nearest_usable_tick(price_to_tick(prijs_onder, 8, orchestrator._usdc_decimals), lp.tick_spacing)
    tick_upper = nearest_usable_tick(price_to_tick(prijs_boven, 8, orchestrator._usdc_decimals), lp.tick_spacing)
    print(f"Range: {prijs_onder:.6f} -- {prijs_boven:.6f} (ticks: {tick_lower} -- {tick_upper})")

    print("\n=== Stap 3: beschikbare, kleine bedragen ===")
    usdc_balance = orchestrator._get_swappable_usdc_balance()
    print(f"Beschikbare USDC: {usdc_balance:.4f}")
    # HBAR-kant afgeleid van de USDC-kant (USDC is hier de beperkende,
    # kleine factor) -- klein en bewust begrensd.
    usdc_raw = int(usdc_balance * 0.95 * (10 ** orchestrator._usdc_decimals))
    from lp_manager import compute_amount0_for_amount1
    hbar_raw = compute_amount0_for_amount1(
        usdc_raw, fresh_price, tick_lower, tick_upper, 8, orchestrator._usdc_decimals,
    )
    print(f"Gebruikt: {hbar_raw/(10**8):.4f} HBAR + {usdc_raw/(10**orchestrator._usdc_decimals):.4f} USDC")

    print("\n=== Stap 4: positie openen ===")
    lp.open_position(
        hbar_raw, usdc_raw, fresh_price, slippage_tolerance=0.05,
        gas_limit_override=1_200_000,
        precomputed_tick_range=(tick_lower, tick_upper),
    )
    print(f"GELUKT! token_id={lp.state.token_id}")
    await db.save_active_lp_position(lp.state.token_id, lp.state.tick_lower, lp.state.tick_upper)

    await db.close()

asyncio.run(main())
