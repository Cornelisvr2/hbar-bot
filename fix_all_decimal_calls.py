with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

aantal_vervangen = 0
for i, regel in enumerate(regels):
    kale_regel = regel.strip()
    if kale_regel == "self._hbar_decimals, self._usdc_decimals,":
        inspringing = regel[:len(regel) - len(regel.lstrip())]
        regels[i] = f"{inspringing}self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,\n"
        aantal_vervangen += 1

print(f"Aantal vervangen regels: {aantal_vervangen} (verwacht: 10)")

with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
    f.writelines(regels)
print("Klaar.")
