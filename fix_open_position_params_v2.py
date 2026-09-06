with open("/root/hbar_bot/lp_manager.py", "r") as f:
    regels = f.readlines()

vervangingen = {
    "        self._ensure_token_approval(self.config.token0, int(amount0_desired * APPROVAL_SAFETY_MARGIN))\n":
        "        self._ensure_token_approval(self.config.token0, int(canonical_amount0_desired * APPROVAL_SAFETY_MARGIN))\n",
    "        self._ensure_token_approval(self.config.token1, int(amount1_desired * APPROVAL_SAFETY_MARGIN))\n":
        "        self._ensure_token_approval(self.config.token1, int(canonical_amount1_desired * APPROVAL_SAFETY_MARGIN))\n",
}

aantal_totaal = 0
for i, regel in enumerate(regels):
    if regel in vervangingen and i < 1300:  # alleen binnen open_position(), niet deploy_additional_capital()
        regels[i] = vervangingen[regel]
        aantal_totaal += 1
        print(f"Regel {i+1} vervangen: {regel.strip()}")

# De params-tuple-regels (amount0_desired,  /  amount1_desired,  / int(...))
for i, regel in enumerate(regels):
    if i < 1300 and regel.strip() == "amount0_desired,":
        regels[i] = regel.replace("amount0_desired,", "canonical_amount0_desired,")
        aantal_totaal += 1
        print(f"Regel {i+1} vervangen (params amount0): {regel.strip()}")
    elif i < 1300 and regel.strip() == "amount1_desired,":
        regels[i] = regel.replace("amount1_desired,", "canonical_amount1_desired,")
        aantal_totaal += 1
        print(f"Regel {i+1} vervangen (params amount1): {regel.strip()}")
    elif i < 1300 and "int(amount0_desired * (1 - slippage_tolerance))," in regel:
        regels[i] = regel.replace("amount0_desired", "canonical_amount0_desired")
        aantal_totaal += 1
        print(f"Regel {i+1} vervangen (min0): {regel.strip()}")
    elif i < 1300 and "int(amount1_desired * (1 - slippage_tolerance))," in regel:
        regels[i] = regel.replace("amount1_desired", "canonical_amount1_desired")
        aantal_totaal += 1
        print(f"Regel {i+1} vervangen (min1): {regel.strip()}")

print(f"\nTotaal vervangen: {aantal_totaal} (verwacht: 6)")

with open("/root/hbar_bot/lp_manager.py", "w") as f:
    f.writelines(regels)
