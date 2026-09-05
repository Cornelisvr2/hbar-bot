for bestandsnaam in ["bot_data.py", "daily_status_report.py"]:
    pad = f"/root/hbar_bot/{bestandsnaam}"
    with open(pad, "r") as f:
        regels = f.readlines()

    aantal = 0
    i = 0
    while i < len(regels):
        if regels[i].strip() == 'prijs_onder = tick_to_price(positie["tick_lower"], 8, 6)':
            inspringing = regels[i][:len(regels[i]) - len(regels[i].lstrip())]
            volgende_regel = regels[i + 1] if i + 1 < len(regels) else ""
            if volgende_regel.strip() == 'prijs_boven = tick_to_price(positie["tick_upper"], 8, 6)':
                nieuwe_regels = [
                    f"{inspringing}# Canonieke token0/token1-decimalen bepalen (5 sep 2026, "
                    "systematische audit -- zelfde detectie als _setup_lp_manager()\n",
                    f"{inspringing}# in regime_orchestrator.py): ticks in de database zijn ALTIJD "
                    "canoniek opgeslagen, ongeacht netwerk.\n",
                    f"{inspringing}if int(base.whbar_token, 16) < int(base.usdc, 16):\n",
                    f"{inspringing}    _t0_dec, _t1_dec = 8, base.usdc_decimals\n",
                    f"{inspringing}else:\n",
                    f"{inspringing}    _t0_dec, _t1_dec = base.usdc_decimals, 8\n",
                    f'{inspringing}prijs_onder = tick_to_price(positie["tick_lower"], _t0_dec, _t1_dec)\n',
                    f'{inspringing}prijs_boven = tick_to_price(positie["tick_upper"], _t0_dec, _t1_dec)\n',
                ]
                regels[i:i+2] = nieuwe_regels
                aantal += 1
                i += len(nieuwe_regels)
                continue
        i += 1

    print(f"{bestandsnaam}: {aantal} vervangen (verwacht: 1)")
    with open(pad, "w") as f:
        f.writelines(regels)
