"""
Correctie (6 sep 2026): compute_optimal_swap_for_position() gebruikte
de canonieke prijs (bv. WHBAR per USDC op mainnet) rechtstreeks om
een waarde in USDC te berekenen -- dat klopt alleen als HBAR toevallig
canoniek token0 is (testnet). Op mainnet moet de prijs eerst
omgekeerd worden voor deze specifieke, mensvriendelijke
waarde-berekening (de tick-gebaseerde delen van de functie blijven
WEL de canonieke prijs gebruiken, die zijn al correct).
"""
with open("/root/hbar_bot/lp_manager.py", "r") as f:
    inhoud = f.read()

oud = """        hbar_have_h = hbar_raw / (10 ** hbar_decimals)
        usdc_have_h = usdc_raw / (10 ** usdc_decimals)
        totale_waarde_usdc = hbar_have_h * price + usdc_have_h
        if (price + k) <= 0 or totale_waarde_usdc <= 0:
            return (None, 0)
        target_hbar_h = totale_waarde_usdc / (price + k)"""

nieuw = """        hbar_have_h = hbar_raw / (10 ** hbar_decimals)
        usdc_have_h = usdc_raw / (10 ** usdc_decimals)
        # BUGFIX: voor de WAARDE-berekening (HBAR -> USDC-equivalent)
        # is de MENSVRIENDELIJKE prijs (USDC per HBAR) nodig, niet de
        # canonieke `price`-parameter (die op mainnet WHBAR-per-USDC
        # is). k zelf blijft in dezelfde eenheid als price/(price+k)
        # hieronder -- daarom wordt k HIER ook omgerekend.
        prijs_semantisch = price if hbar_is_token0 else (1.0 / price)
        k_semantisch = k if hbar_is_token0 else (1.0 / k if k > 0 else 0.0)
        totale_waarde_usdc = hbar_have_h * prijs_semantisch + usdc_have_h
        if (prijs_semantisch + k_semantisch) <= 0 or totale_waarde_usdc <= 0:
            return (None, 0)
        target_hbar_h = totale_waarde_usdc / (prijs_semantisch + k_semantisch)"""

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/lp_manager.py", "w") as f:
        f.write(inhoud)
    print("Gecorrigeerd.")
else:
    print("WAARSCHUWING: geen unieke match.")
