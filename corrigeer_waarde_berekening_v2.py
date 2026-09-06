"""
Verfijning op de correctie van zonet: k zelf is AL correct uitgedrukt
in "USDC (mensvriendelijk) per HBAR (mensvriendelijk)" -- die komt
immers uit de al-canoniek-bewuste compute_needed_usdc_for_hbar(). Die
hoeft dus NIET nogmaals omgekeerd te worden -- alleen de `price`-
parameter zelf (voor de losse waarde-berekening) moet omgekeerd
worden als HBAR niet canoniek token0 is.
"""
with open("/root/hbar_bot/lp_manager.py", "r") as f:
    inhoud = f.read()

oud = """        prijs_semantisch = price if hbar_is_token0 else (1.0 / price)
        k_semantisch = k if hbar_is_token0 else (1.0 / k if k > 0 else 0.0)
        totale_waarde_usdc = hbar_have_h * prijs_semantisch + usdc_have_h
        if (prijs_semantisch + k_semantisch) <= 0 or totale_waarde_usdc <= 0:
            return (None, 0)
        target_hbar_h = totale_waarde_usdc / (prijs_semantisch + k_semantisch)"""

nieuw = """        prijs_semantisch = price if hbar_is_token0 else (1.0 / price)
        totale_waarde_usdc = hbar_have_h * prijs_semantisch + usdc_have_h
        if (prijs_semantisch + k) <= 0 or totale_waarde_usdc <= 0:
            return (None, 0)
        target_hbar_h = totale_waarde_usdc / (prijs_semantisch + k)"""

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/lp_manager.py", "w") as f:
        f.write(inhoud)
    print("Verfijnd.")
else:
    print("WAARSCHUWING: geen unieke match.")
