with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

# Zoek elke regel die start met "compute_amount0_for_amount1(" of
# "compute_amount1_for_amount0(" (na = teken, ongeacht inspringing), en
# vervang dan de EERSTVOLGENDE regel die exact
# "self._hbar_decimals, self._usdc_decimals," bevat (ongeacht inspringing)
# door de canonieke variant.
aantal_vervangen = 0
i = 0
while i < len(regels):
    regel = regels[i]
    if "compute_amount0_for_amount1(" in regel or "compute_amount1_for_amount0(" in regel:
        # Zoek de eerstvolgende regel (binnen de volgende 5) die de
        # semantische decimalen bevat.
        for j in range(i, min(i + 5, len(regels))):
            if regels[j].strip() == "self._hbar_decimals, self._usdc_decimals,":
                inspringing = regels[j][:len(regels[j]) - len(regels[j].lstrip())]
                regels[j] = (f"{inspringing}self.lp_manager.config.token0_decimals, "
                             f"self.lp_manager.config.token1_decimals,\n")
                aantal_vervangen += 1
                break
    i += 1

print(f"Aantal vervangen: {aantal_vervangen} (verwacht: 8)")

with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
    f.writelines(regels)
print("Klaar.")
