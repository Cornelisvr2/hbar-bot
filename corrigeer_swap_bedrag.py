with open("/root/hbar_bot/lp_manager.py", "r") as f:
    inhoud = f.read()

oud = """        else:
            usdc_swap_h = abs(verschil_hbar_h) * price
            swap_raw = int(usdc_swap_h * (10 ** usdc_decimals))
            return ("USDC_TO_HBAR", swap_raw)"""

nieuw = """        else:
            usdc_swap_h = abs(verschil_hbar_h) * prijs_semantisch
            swap_raw = int(usdc_swap_h * (10 ** usdc_decimals))
            return ("USDC_TO_HBAR", swap_raw)"""

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/lp_manager.py", "w") as f:
        f.write(inhoud)
    print("Gecorrigeerd.")
else:
    print("WAARSCHUWING: geen unieke match.")
