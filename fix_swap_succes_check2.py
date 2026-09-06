with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

aantal = 0
for i, regel in enumerate(regels):
    if regel.strip() == 'await self._run_swap_and_log("USDC_TO_HBAR", usdc_to_swap, None)':
        inspringing = regel[:len(regel) - len(regel.lstrip())]
        regels[i] = f"{inspringing}swap_gelukt = await self._run_swap_and_log(\"USDC_TO_HBAR\", usdc_to_swap, None)\n"
        regels.insert(i + 1, f"{inspringing}if not swap_gelukt:\n")
        regels.insert(i + 2, f"{inspringing}    return False  # swap mislukt -- NIET doorgaan met een verouderde balans-aanname\n")
        aantal += 1
        break

with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
    f.writelines(regels)
print(f"Tweede vervanging (USDC_TO_HBAR): {aantal}")
