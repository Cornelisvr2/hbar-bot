"""
BUGFIX (6 sep 2026, empirisch bevestigd): deploy_additional_capital()
mistte de expliciete wrapWhbar()-stap die open_position() WEL heeft --
zonder deze faalt increaseLiquidity() stilzwijgend met een lege
revert-reden zodra er losse, nog-niet-gewrapte HBAR ingezet moet
worden. Zelfde patroon, zelfde oplossing als open_position()'s
"Stap 1".
"""
with open("/root/hbar_bot/lp_manager.py", "r") as f:
    inhoud = f.read()

oud = '''        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() != whbar_lower:
                self._ensure_token_approval(self.config.token0, canonical_amount0_desired)
            if self.config.token1.lower() != whbar_lower:
                self._ensure_token_approval(self.config.token1, canonical_amount1_desired)

        min0 = int(canonical_amount0_desired * (1 - slippage_tolerance))'''

nieuw = '''        # BUGFIX (6 sep 2026, empirisch bevestigd via een live-test):
        # ontbrekende wrapWhbar()-stap -- zonder deze faalt
        # increaseLiquidity() stilzwijgend met een lege revert-reden,
        # zelfde patroon als open_position() vóór zijn "Stap 1"-fix.
        if self.config.whbar_address and self.whbar_helper:
            whbar_lower = self.config.whbar_address.lower()
            whbar_amount_needed = None
            whbar_decimals = None
            if self.config.token0.lower() == whbar_lower:
                whbar_amount_needed = canonical_amount0_desired
                whbar_decimals = self.config.token0_decimals
            elif self.config.token1.lower() == whbar_lower:
                whbar_amount_needed = canonical_amount1_desired
                whbar_decimals = self.config.token1_decimals
            if whbar_amount_needed is not None and whbar_amount_needed > 0:
                wrap_value_wei = whbar_amount_needed * (10 ** (18 - whbar_decimals))
                wrap_fn = self.whbar_helper.functions.wrapWhbar()
                wrap_tx = self.rpc_client.build_and_send_transaction(wrap_fn, value_wei=wrap_value_wei)
                self.rpc_client.wait_for_receipt(wrap_tx)
                time.sleep(2)

        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() != whbar_lower:
                self._ensure_token_approval(self.config.token0, canonical_amount0_desired)
            if self.config.token1.lower() != whbar_lower:
                self._ensure_token_approval(self.config.token1, canonical_amount1_desired)

        min0 = int(canonical_amount0_desired * (1 - slippage_tolerance))'''

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/lp_manager.py", "w") as f:
        f.write(inhoud)
    print("Wrap-stap toegevoegd.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
