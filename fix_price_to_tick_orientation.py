with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

aantal_vervangen = 0
for i, regel in enumerate(regels):
    if regel.strip() == 'huidige_tick = price_to_tick(fresh_price, self._hbar_decimals, self._usdc_decimals)':
        inspringing = regel[:len(regel) - len(regel.lstrip())]
        regels[i] = (f"{inspringing}huidige_tick = price_to_tick(\n"
                     f"{inspringing}    fresh_price, self.lp_manager.config.token0_decimals, "
                     f"self.lp_manager.config.token1_decimals,\n"
                     f"{inspringing})\n")
        aantal_vervangen += 1

print(f"Aantal vervangen: {aantal_vervangen} (verwacht: 2)")

with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
    f.writelines(regels)
print("Klaar.")
