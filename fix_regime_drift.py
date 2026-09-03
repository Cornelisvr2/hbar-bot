with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    inhoud = f.read()

oud1 = """        seconds_since_last_lp_rebalance = time.time() - self._last_lp_rebalance_at
        if seconds_since_last_lp_rebalance < self.lp_rebalance_cooldown_seconds:
            return
        from lp_manager import tick_to_price"""
nieuw1 = """        seconds_since_last_lp_rebalance = time.time() - self._last_lp_rebalance_at
        if seconds_since_last_lp_rebalance < self.lp_rebalance_cooldown_seconds:
            return
        from lp_manager import tick_to_price, get_live_pool_price

        try:
            fresh_price = get_live_pool_price(
                self.rpc_client, self.lp_manager.config.factory_address,
                self.lp_manager.config.token0, self.lp_manager.config.token1,
                self.lp_manager.config.fee_tier,
                self._hbar_decimals, self._usdc_decimals,
            )
        except Exception as e:
            telegram_notify.report_error(
                "regime_drift_check: pool-prijs opvragen",
                f"{e} -- geen actie ondernomen.",
            )
            return"""

if oud1 in inhoud:
    inhoud = inhoud.replace(oud1, nieuw1)
    print("Stap 1/4 (fresh_price ophalen) toegevoegd.")
else:
    print("WAARSCHUWING stap 1: exacte tekst niet gevonden.")

oud2 = "nieuwe_tick_lower, nieuwe_tick_upper = self.lp_manager.compute_range_via_gbm(\n            current_price, combined_score_now"
nieuw2 = "nieuwe_tick_lower, nieuwe_tick_upper = self.lp_manager.compute_range_via_gbm(\n            fresh_price, combined_score_now"
if oud2 in inhoud:
    inhoud = inhoud.replace(oud2, nieuw2)
    print("Stap 2/4 (compute_range_via_gbm) gecorrigeerd.")
else:
    print("WAARSCHUWING stap 2: exacte tekst niet gevonden.")

oud3 = "balanceren_gelukt = await self._ensure_balanced_liquidity_ratio(\n            current_price, nieuwe_tick_lower, nieuwe_tick_upper\n        )"
nieuw3 = "balanceren_gelukt = await self._ensure_balanced_liquidity_ratio(\n            fresh_price, nieuwe_tick_lower, nieuwe_tick_upper\n        )"
if oud3 in inhoud:
    inhoud = inhoud.replace(oud3, nieuw3)
    print("Stap 3/4 (_ensure_balanced_liquidity_ratio) gecorrigeerd.")
else:
    print("WAARSCHUWING stap 3: exacte tekst niet gevonden.")

oud4 = "self.lp_manager.open_position(\n                hbar_raw, usdc_raw, current_price,\n                slippage_tolerance=0.15, gas_limit_override=1_200_000,\n                precomputed_tick_range=(nieuwe_tick_lower, nieuwe_tick_upper),\n            )"
nieuw4 = "self.lp_manager.open_position(\n                hbar_raw, usdc_raw, fresh_price,\n                slippage_tolerance=0.15, gas_limit_override=1_200_000,\n                precomputed_tick_range=(nieuwe_tick_lower, nieuwe_tick_upper),\n            )"
if oud4 in inhoud:
    inhoud = inhoud.replace(oud4, nieuw4)
    print("Stap 4/4 (open_position) gecorrigeerd.")
else:
    print("WAARSCHUWING stap 4: exacte tekst niet gevonden.")

with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
    f.write(inhoud)
