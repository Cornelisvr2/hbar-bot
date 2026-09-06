"""
KRITIEKE BUGFIX (6 sep 2026, zelfde patroon als open_position()):
deploy_additional_capital() ontvangt amount0_desired/amount1_desired
ALTIJD als (hbar_raw, usdc_raw) van zijn enige aanroeper, maar stuurt
deze rechtstreeks door naar increaseLiquidity() zonder rekening te
houden met welk token canoniek token0/token1 IS voor de bestaande
positie. Op mainnet (USDC=token0, WHBAR=token1) worden de bedragen
dus verwisseld -- zelfde onderliggende oorzaak als de net-gerepareerde
open_position()-bug.
"""
with open("/root/hbar_bot/lp_manager.py", "r") as f:
    inhoud = f.read()

oud = '''        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() != whbar_lower:
                self._ensure_token_approval(self.config.token0, amount0_desired)
            if self.config.token1.lower() != whbar_lower:
                self._ensure_token_approval(self.config.token1, amount1_desired)

        min0 = int(amount0_desired * (1 - slippage_tolerance))
        min1 = int(amount1_desired * (1 - slippage_tolerance))
        increase_params = (token_id, amount0_desired, amount1_desired, min0, min1, self._deadline())'''

nieuw = '''        # KRITIEKE BUGFIX (6 sep 2026, zelfde patroon als open_position()):
        # amount0_desired/amount1_desired komen van de aanroeper ALTIJD als
        # (hbar_raw, usdc_raw) -- moeten hier herordend worden naar de
        # canonieke (token0, token1)-volgorde van de bestaande positie.
        hbar_is_token0 = (
            self.config.whbar_address is not None
            and self.config.token0.lower() == self.config.whbar_address.lower()
        )
        if hbar_is_token0:
            canonical_amount0_desired = amount0_desired
            canonical_amount1_desired = amount1_desired
        else:
            canonical_amount0_desired = amount1_desired
            canonical_amount1_desired = amount0_desired

        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() != whbar_lower:
                self._ensure_token_approval(self.config.token0, canonical_amount0_desired)
            if self.config.token1.lower() != whbar_lower:
                self._ensure_token_approval(self.config.token1, canonical_amount1_desired)

        min0 = int(canonical_amount0_desired * (1 - slippage_tolerance))
        min1 = int(canonical_amount1_desired * (1 - slippage_tolerance))
        increase_params = (token_id, canonical_amount0_desired, canonical_amount1_desired, min0, min1, self._deadline())'''

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/lp_manager.py", "w") as f:
        f.write(inhoud)
    print("Gecorrigeerd.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
