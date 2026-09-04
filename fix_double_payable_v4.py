with open("/root/hbar_bot/lp_manager.py", "r") as f:
    regels = f.readlines()

gevonden_blokken = []
for i, regel in enumerate(regels):
    if "payable_value = tokens_owed0_raw * (10 ** (18" in regel:
        gevonden_blokken.append(("claim_and_compound", i))
    if "payable_value = amount0_desired * (10 ** (18" in regel:
        gevonden_blokken.append(("deploy_additional_capital", i))

print(f"Gevonden blokken: {gevonden_blokken}")

for naam, token0_idx in sorted(gevonden_blokken, key=lambda x: -x[1]):
    # Zoek TERUG naar "payable_value = 0"
    basis_idx = None
    for j in range(token0_idx, max(0, token0_idx - 10), -1):
        if "payable_value = 0" in regels[j]:
            basis_idx = j
            break
    assert basis_idx is not None, f"payable_value = 0 niet gevonden vóór regel {token0_idx}"

    # Zoek VOORUIT naar de laatste regel van de elif-tak (de token1-regel,
    # herkenbaar aan dezelfde structuur maar met '1' i.p.v. '0')
    eind_idx = None
    for j in range(token0_idx, token0_idx + 6):
        if ("payable_value = tokens_owed1_raw" in regels[j]
                or "payable_value = amount1_desired" in regels[j]):
            eind_idx = j
            break
    assert eind_idx is not None, f"token1-regel niet gevonden na regel {token0_idx}"

    nieuwe_regels = [
        f"        # BUGFIX (4 sep 2026, zelfde patroon als de eerder gevonden en\n",
        f"        # opgeloste dubbele-msg.value-bug in open_position()): payable_value\n",
        f"        # stuurde voorheen het volledige, al-beschikbare bedrag NOGMAALS als\n",
        f"        # native msg.value. Nu een klein, symbolisch bedrag i.p.v. het\n",
        f"        # volledige bedrag nogmaals ({naam}).\n",
        f"        WHBAR_SYMBOLIC_MSG_VALUE_TINYBAR = 10 ** 8  # 1 HBAR, in tinybar\n",
        f"        payable_value = 0\n",
        f"        if self.config.whbar_address:\n",
        f"            whbar_lower = self.config.whbar_address.lower()\n",
        f"            if self.config.token0.lower() == whbar_lower or self.config.token1.lower() == whbar_lower:\n",
        f"                payable_value = WHBAR_SYMBOLIC_MSG_VALUE_TINYBAR * (10 ** 10)\n",
    ]
    regels[basis_idx:eind_idx+1] = nieuwe_regels
    print(f"{naam}: regels {basis_idx}-{eind_idx} vervangen.")

with open("/root/hbar_bot/lp_manager.py", "w") as f:
    f.writelines(regels)
print("Klaar.")
