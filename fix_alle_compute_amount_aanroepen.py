"""
Vervangt alle 8 (4 paren) compute_amount1_for_amount0/
compute_amount0_for_amount1-aanroepen door de nieuwe, veilige
LpManager-hulpmethoden die zelf de juiste richting kiezen op basis
van welk token daadwerkelijk canoniek token0/token1 is (6 sep 2026,
structurele fix).
"""
import re

with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    inhoud = f.read()

# Patroon 1: compute_amount1_for_amount0(<hbar_var>, <price_var>, tick_lower, tick_upper, self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,)
patroon1 = re.compile(
    r"compute_amount1_for_amount0\(\s*\n"
    r"(\s*)(\w+), (\w+), tick_lower, tick_upper,\s*\n"
    r"\s*self\.lp_manager\.config\.token0_decimals, self\.lp_manager\.config\.token1_decimals,\s*\n"
    r"(\s*)\)"
)

def vervang1(m):
    inspringing_binnen, hbar_var, price_var, inspringing_sluit = m.groups()
    return (f"self.lp_manager.compute_needed_usdc_for_hbar(\n"
            f"{inspringing_binnen}{hbar_var}, {price_var}, tick_lower, tick_upper,\n"
            f"{inspringing_sluit})")

nieuwe_inhoud, aantal1 = patroon1.subn(vervang1, inhoud)
print(f"Patroon 1 (compute_amount1_for_amount0): {aantal1} vervangen (verwacht: 4)")

# Patroon 2: compute_amount0_for_amount1(<usdc_var>, <price_var>, tick_lower, tick_upper, self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,)
patroon2 = re.compile(
    r"compute_amount0_for_amount1\(\s*\n"
    r"(\s*)(\w+), (\w+), tick_lower, tick_upper,\s*\n"
    r"\s*self\.lp_manager\.config\.token0_decimals, self\.lp_manager\.config\.token1_decimals,\s*\n"
    r"(\s*)\)"
)

def vervang2(m):
    inspringing_binnen, usdc_var, price_var, inspringing_sluit = m.groups()
    return (f"self.lp_manager.compute_needed_hbar_for_usdc(\n"
            f"{inspringing_binnen}{usdc_var}, {price_var}, tick_lower, tick_upper,\n"
            f"{inspringing_sluit})")

nieuwe_inhoud, aantal2 = patroon2.subn(vervang2, nieuwe_inhoud)
print(f"Patroon 2 (compute_amount0_for_amount1): {aantal2} vervangen (verwacht: 4)")

print(f"TOTAAL: {aantal1 + aantal2} (verwacht: 8)")

with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
    f.write(nieuwe_inhoud)
print("Weggeschreven.")
