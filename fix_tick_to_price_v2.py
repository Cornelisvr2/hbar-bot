# regime_orchestrator.py: 6 tick_to_price-aanroepen die canonieke ticks
# verkeerd met semantische decimalen omzetten.
with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

aantal = 0
for i, regel in enumerate(regels):
    if "tick_to_price(" in regel and "self._hbar_decimals, self._usdc_decimals)" in regel:
        regels[i] = regel.replace(
            "self._hbar_decimals, self._usdc_decimals)",
            "self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals)",
        )
        aantal += 1

print(f"regime_orchestrator.py: {aantal} vervangen (verwacht: 6)")
with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
    f.writelines(regels)

# bot_data.py en daily_status_report.py: hardgecodeerde (8, 6) toegepast
# op canoniek opgeslagen ticks. ResolvedV2Addresses/ResolvedAddresses
# hebben GEEN token0_decimals/token1_decimals-veld -- de canonieke
# volgorde moet zelf bepaald worden (zelfde patroon als
# _setup_lp_manager() in regime_orchestrator.py).
for bestandsnaam in ["bot_data.py", "daily_status_report.py"]:
    pad = f"/root/hbar_bot/{bestandsnaam}"
    with open(pad, "r") as f:
        inhoud = f.read()
    oud = ('prijs_onder = tick_to_price(positie["tick_lower"], 8, 6)\n'
           '            prijs_boven = tick_to_price(positie["tick_upper"], 8, 6)')
    nieuw = (
        '# Canonieke token0/token1-decimalen bepalen (dezelfde detectie als\n'
        '            # _setup_lp_manager() in regime_orchestrator.py) -- ticks in de\n'
        '            # database zijn ALTIJD canoniek opgeslagen, ongeacht netwerk.\n'
        '            if int(base.whbar_token, 16) < int(base.usdc, 16):\n'
        '                _t0_dec, _t1_dec = 8, base.usdc_decimals\n'
        '            else:\n'
        '                _t0_dec, _t1_dec = base.usdc_decimals, 8\n'
        '            prijs_onder = tick_to_price(positie["tick_lower"], _t0_dec, _t1_dec)\n'
        '            prijs_boven = tick_to_price(positie["tick_upper"], _t0_dec, _t1_dec)'
    )
    aantal_bestand = inhoud.count(oud)
    print(f"{bestandsnaam}: {aantal_bestand} gevonden (verwacht: 1)")
    if aantal_bestand == 1:
        inhoud = inhoud.replace(oud, nieuw)
        with open(pad, "w") as f:
            f.write(inhoud)
        print(f"{bestandsnaam}: bijgewerkt.")
    else:
        print(f"{bestandsnaam}: WAARSCHUWING -- geen unieke match, NIET aangepast.")
