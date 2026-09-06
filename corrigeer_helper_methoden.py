"""
Correctie op de structurele fix van zonet: de canonieke decimalen
(self.config.token0_decimals, self.config.token1_decimals) moeten
ALTIJD in die volgorde blijven staan -- alleen de KEUZE van welke
onderliggende functie wordt aangeroepen hangt af van hbar_is_token0,
niet de decimalen-volgorde zelf. De rekentest van zonet ontdekte deze
fout (scenario 2 gaf 0 i.p.v. een redelijk bedrag).
"""
with open("/root/hbar_bot/lp_manager.py", "r") as f:
    inhoud = f.read()

oud1 = '''        if hbar_is_token0:
            return compute_amount1_for_amount0(
                hbar_raw, price, tick_lower, tick_upper,
                self.config.token0_decimals, self.config.token1_decimals,
            )
        else:
            return compute_amount0_for_amount1(
                hbar_raw, price, tick_lower, tick_upper,
                self.config.token1_decimals, self.config.token0_decimals,
            )'''
nieuw1 = '''        if hbar_is_token0:
            return compute_amount1_for_amount0(
                hbar_raw, price, tick_lower, tick_upper,
                self.config.token0_decimals, self.config.token1_decimals,
            )
        else:
            return compute_amount0_for_amount1(
                hbar_raw, price, tick_lower, tick_upper,
                self.config.token0_decimals, self.config.token1_decimals,
            )'''

aantal1 = inhoud.count(oud1)
print(f"compute_needed_usdc_for_hbar -- gevonden: {aantal1} (verwacht: 1)")

oud2 = '''        if hbar_is_token0:
            return compute_amount0_for_amount1(
                usdc_raw, price, tick_lower, tick_upper,
                self.config.token0_decimals, self.config.token1_decimals,
            )
        else:
            return compute_amount1_for_amount0(
                usdc_raw, price, tick_lower, tick_upper,
                self.config.token1_decimals, self.config.token0_decimals,
            )'''
nieuw2 = '''        if hbar_is_token0:
            return compute_amount0_for_amount1(
                usdc_raw, price, tick_lower, tick_upper,
                self.config.token0_decimals, self.config.token1_decimals,
            )
        else:
            return compute_amount1_for_amount0(
                usdc_raw, price, tick_lower, tick_upper,
                self.config.token0_decimals, self.config.token1_decimals,
            )'''

aantal2 = inhoud.count(oud2)
print(f"compute_needed_hbar_for_usdc -- gevonden: {aantal2} (verwacht: 1)")

if aantal1 == 1 and aantal2 == 1:
    inhoud = inhoud.replace(oud1, nieuw1)
    inhoud = inhoud.replace(oud2, nieuw2)
    with open("/root/hbar_bot/lp_manager.py", "w") as f:
        f.write(inhoud)
    print("Beide gecorrigeerd.")
else:
    print("WAARSCHUWING: niet beide uniek gevonden -- NIET aangepast.")
