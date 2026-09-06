with open("/root/hbar_bot/lp_manager.py", "r") as f:
    inhoud = f.read()

oud = '''        APPROVAL_SAFETY_MARGIN = 1.005
        self._ensure_token_approval(self.config.token0, int(amount0_desired * APPROVAL_SAFETY_MARGIN))
        self._ensure_token_approval(self.config.token1, int(amount1_desired * APPROVAL_SAFETY_MARGIN))
        if precomputed_tick_range is not None:
            tick_lower, tick_upper = precomputed_tick_range
        else:
            tick_lower, tick_upper = self.compute_range(current_price, volatility_regime, sentiment_direction)
        params = (
            self.config.token0,
            self.config.token1,
            self.config.fee_tier,
            tick_lower,
            tick_upper,
            amount0_desired,
            amount1_desired,
            int(amount0_desired * (1 - slippage_tolerance)),
            int(amount1_desired * (1 - slippage_tolerance)),
            self.rpc_client.address,
            self._deadline(),
        )'''

nieuw = '''        APPROVAL_SAFETY_MARGIN = 1.005
        self._ensure_token_approval(self.config.token0, int(canonical_amount0_desired * APPROVAL_SAFETY_MARGIN))
        self._ensure_token_approval(self.config.token1, int(canonical_amount1_desired * APPROVAL_SAFETY_MARGIN))
        if precomputed_tick_range is not None:
            tick_lower, tick_upper = precomputed_tick_range
        else:
            tick_lower, tick_upper = self.compute_range(current_price, volatility_regime, sentiment_direction)
        params = (
            self.config.token0,
            self.config.token1,
            self.config.fee_tier,
            tick_lower,
            tick_upper,
            canonical_amount0_desired,
            canonical_amount1_desired,
            int(canonical_amount0_desired * (1 - slippage_tolerance)),
            int(canonical_amount1_desired * (1 - slippage_tolerance)),
            self.rpc_client.address,
            self._deadline(),
        )'''

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/lp_manager.py", "w") as f:
        f.write(inhoud)
    print("Gecorrigeerd.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
