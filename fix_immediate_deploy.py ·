with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    inhoud = f.read()

# Stap 1: de cooldown-check instelbaar maken
oud1 = """        if self.current_regime != Regime.LP_MODE:
            return
        if not self.lp_manager or not self.lp_manager.state.is_open:
            return
        if (time.time() - self._last_capital_deploy_at) < self.deploy_capital_cooldown_seconds:
            return
        excess_hbar = self._get_swappable_hbar_balance(current_price)"""

nieuw1 = """        if self.current_regime != Regime.LP_MODE:
            return
        if not self.lp_manager or not self.lp_manager.state.is_open:
            return
        if (not bypass_cooldown
                and (time.time() - self._last_capital_deploy_at) < self.deploy_capital_cooldown_seconds):
            return
        excess_hbar = self._get_swappable_hbar_balance(current_price)"""

aantal1 = inhoud.count(oud1)
print(f"Stap 1 -- aantal matches: {aantal1}")
if aantal1 == 1:
    inhoud = inhoud.replace(oud1, nieuw1)
    print("Stap 1 correct bijgewerkt.")
else:
    print("WAARSCHUWING stap 1: geen unieke match.")

# Stap 2: de functiehandtekening zelf uitbreiden met het nieuwe, optionele argument
oud2 = "async def _deploy_excess_capital_if_available(self, current_price: float):"
nieuw2 = ("async def _deploy_excess_capital_if_available(self, current_price: float, "
          "bypass_cooldown: bool = False):")
aantal2 = inhoud.count(oud2)
print(f"Stap 2 -- aantal matches: {aantal2}")
if aantal2 == 1:
    inhoud = inhoud.replace(oud2, nieuw2)
    print("Stap 2 correct bijgewerkt.")
else:
    print("WAARSCHUWING stap 2: geen unieke match.")

with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
    f.write(inhoud)
