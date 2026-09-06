"""
KRITIEKE BUGFIX (6 sep 2026, empirisch bevestigd -- veroorzaakte een
grote, vastgezeten WHBAR-hoeveelheid): _ensure_balanced_liquidity_ratio()
controleerde niet of _run_swap_and_log() daadwerkelijk slaagde --
retourneerde ALTIJD True, ook als de swap zelf mislukte (bv. door een
tijdelijke RPC-storing, zoals meermaals waargenomen vanavond). Bij een
mislukte swap wordt de balans-cache NIET ongeldig gemaakt (terecht,
er is niets veranderd), maar de aanroepende code (kapitaal bijstorten)
ging vervolgens toch door met de VEROUDERDE balans -- resulterend in
een veel te groot, verkeerd-berekend stortingsbedrag.
"""
with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

aantal = 0
for i, regel in enumerate(regels):
    if regel.strip() == 'await self._run_swap_and_log("HBAR_TO_USDC", hbar_to_swap, None)':
        inspringing = regel[:len(regel) - len(regel.lstrip())]
        regels[i] = f"{inspringing}swap_gelukt = await self._run_swap_and_log(\"HBAR_TO_USDC\", hbar_to_swap, None)\n"
        # Voeg een check toe direct NA deze regel (met dezelfde inspringing).
        regels.insert(i + 1, f"{inspringing}if not swap_gelukt:\n")
        regels.insert(i + 2, f"{inspringing}    return False  # swap mislukt -- NIET doorgaan met een verouderde balans-aanname\n")
        aantal += 1
        break  # opnieuw itereren na de invoeging, indices zijn nu verschoven

with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
    f.writelines(regels)
print(f"Eerste vervanging (HBAR_TO_USDC): {aantal}")
