with open("/root/hbar_bot/lp_manager.py", "r") as f:
    regels = f.readlines()

doelregel = "    return raw_price * (10 ** (token0_decimals - token1_decimals))\n"
gevonden_op = [i for i, regel in enumerate(regels) if regel == doelregel]
print(f"Aantal exacte matches: {len(gevonden_op)}")

if len(gevonden_op) == 1:
    i = gevonden_op[0]
    nieuwe_regels = [
        "    # KRITIEKE BUGFIX (4 sep 2026, gevonden tijdens de mainnet-\n",
        "    # migratie): Uniswap V3-achtige pools ordenen token0/token1 ALTIJD\n",
        "    # op numeriek adres (kleinste eerst) -- de tick-afgeleide prijs is\n",
        "    # ALTIJD \"canoniek-token1 per canoniek-token0\", ongeacht in welke\n",
        "    # volgorde DEZE FUNCTIE aangeroepen is. Op testnet was WHBAR\n",
        "    # toevallig altijd numeriek kleiner (dus canoniek token0) -- op\n",
        "    # mainnet is USDC numeriek kleiner dan WHBAR, dus omgedraaid.\n",
        "    # Empirisch bevestigd: zonder correctie gaf dit op mainnet 129263.98\n",
        "    # i.p.v. de correcte 0.0774 HBAR/USD.\n",
        "    if int(token0, 16) < int(token1, 16):\n",
        "        return raw_price * (10 ** (token0_decimals - token1_decimals))\n",
        "    else:\n",
        "        return (1.0 / raw_price) * (10 ** (token0_decimals - token1_decimals))\n",
    ]
    regels[i:i+1] = nieuwe_regels
    with open("/root/hbar_bot/lp_manager.py", "w") as f:
        f.writelines(regels)
    print("Correct bijgewerkt.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
    for i, regel in enumerate(regels):
        if "token0_decimals - token1_decimals" in regel:
            print(f"Regel {i}: {repr(regel)}")
