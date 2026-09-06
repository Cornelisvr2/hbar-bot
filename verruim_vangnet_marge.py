with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    inhoud = f.read()

oud = "                            hbar_raw, usdc_raw, fresh_price, slippage_tolerance=0.15,"
nieuw = "                            hbar_raw, usdc_raw, fresh_price, slippage_tolerance=0.25,"

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
        f.write(inhoud)
    print("Vangnet-marge verruimd naar 25%.")
else:
    print("WAARSCHUWING: geen unieke match.")
