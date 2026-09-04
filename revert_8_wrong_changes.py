with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

# Deze 8 regels horen bij compute_amount1_for_amount0()/compute_amount0_for_amount1(),
# NIET bij get_live_pool_price() -- daar betekent amount0 altijd "HBAR",
# ongeacht de pool's canonieke token0/token1-volgorde.
aantal_teruggedraaid = 0
for i, regel in enumerate(regels):
    kale_regel = regel.strip()
    if kale_regel == "self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,":
        # Kijk 2-3 regels terug: als daar "compute_amount1_for_amount0(" of
        # "compute_amount0_for_amount1(" staat (i.p.v. get_live_pool_price),
        # dan is dit een van de 8 foutieve wijzigingen -- terugdraaien.
        context_ervoor = "".join(regels[max(0,i-3):i])
        if "compute_amount1_for_amount0(" in context_ervoor or "compute_amount0_for_amount1(" in context_ervoor:
            inspringing = regel[:len(regel) - len(regel.lstrip())]
            regels[i] = f"{inspringing}self._hbar_decimals, self._usdc_decimals,\n"
            aantal_teruggedraaid += 1

print(f"Aantal teruggedraaid: {aantal_teruggedraaid} (verwacht: 8)")

with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
    f.writelines(regels)
print("Klaar.")
