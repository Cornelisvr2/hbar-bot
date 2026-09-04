with open("/root/hbar_bot/lp_manager.py", "r") as f:
    regels = f.readlines()

# Zoek beide voorkomens van het patroon: een regel met "payable_value = tokens_owed0_raw * ("
# en een regel met "payable_value = amount0_desired * (" (BUITEN open_position(), die al gefixed is)
gevonden_blokken = []
for i, regel in enumerate(regels):
    if "payable_value = tokens_owed0_raw * (10 ** (18" in regel:
        gevonden_blokken.append(("claim_and_compound", i))
    if "payable_value = amount0_desired * (10 ** (18" in regel:
        gevonden_blokken.append(("deploy_additional_capital", i))

print(f"Gevonden blokken: {gevonden_blokken}")

# Verwerk van ACHTER naar VOOR, zodat regelnummers niet verschuiven tijdens het bewerken
for naam, start_idx in sorted(gevonden_blokken, key=lambda x: -x[1]):
    # De structuur is: "if self.config.whbar_address:" (2 regels eerder),
    # "whbar_lower = ..." (1 regel eerder), dan DEZE regel (token0-tak),
    # dan "elif ... token1 ..." + de token1-regel.
    # We vervangen vanaf "payable_value = 0" (4 regels eerder) t/m de
    # elif-tak (2 regels na start_idx) door de gefixte versie.
    basis_idx = start_idx - 3  # regel met "payable_value = 0"
    assert "payable_value = 0" in regels[basis_idx], f"Onverwachte regel op {basis_idx}: {regels[basis_idx]}"
    eind_idx = start_idx + 2  # laatste regel van de elif-tak (token1-regel)

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
