"""
Regel-gebaseerde versie van de eerdere fix (block-tekst-matching
mislukte door een onzichtbaar verschil). Vervangt regels 115 t/m 143
(1-geindexeerd) -- van "positie_hbar, positie_sauce = ..." t/m
"positie_in_range_pct = 50.0" -- door de canoniek-bewuste versie.
"""
with open("/root/hbar_bot/bot_data.py", "r") as f:
    regels = f.readlines()

start_idx = None
for i, regel in enumerate(regels):
    if regel.strip().startswith("positie_hbar, positie_sauce = compute_position_amounts"):
        start_idx = i
        break

if start_idx is None:
    print("WAARSCHUWING: startregel niet gevonden.")
else:
    eind_idx = None
    for j in range(start_idx, start_idx + 40):
        if regels[j].strip() == "positie_in_range_pct = 50.0":
            eind_idx = j
            break
    print(f"start_idx={start_idx} (regel {start_idx+1}), eind_idx={eind_idx} (regel {eind_idx+1 if eind_idx else None})")

    if eind_idx is None:
        print("WAARSCHUWING: eindregel niet gevonden -- NIET aangepast.")
    else:
        nieuwe_regels = [
            "        # KRITIEKE BUGFIX (6 sep 2026, ontdekt bij de EERSTE echte positie):\n",
            "        # canonieke token0/token1-decimalen ÉÉN keer bepalen, VOOR gebruik --\n",
            "        # ticks in de database zijn ALTIJD canoniek opgeslagen (zelfde\n",
            "        # detectie als _setup_lp_manager() in regime_orchestrator.py).\n",
            "        _hbar_is_token0 = int(base.whbar_token, 16) < int(base.usdc, 16)\n",
            "        if _hbar_is_token0:\n",
            "            _t0_dec, _t1_dec = 8, base.usdc_decimals\n",
            "        else:\n",
            "            _t0_dec, _t1_dec = base.usdc_decimals, 8\n",
            "        # Canonieke prijs: pool_price_sauce_per_hbar is SEMANTISCH (USDC\n",
            "        # per HBAR) -- omkeren als HBAR niet canoniek token0 is (mainnet).\n",
            "        _prijs_canoniek = pool_price_sauce_per_hbar if _hbar_is_token0 else (\n",
            "            1.0 / pool_price_sauce_per_hbar if pool_price_sauce_per_hbar > 0 else 0.0\n",
            "        )\n",
            "        positie_hbar, positie_sauce = compute_position_amounts(\n",
            "            liquidity, positie[\"tick_lower\"], positie[\"tick_upper\"],\n",
            "            _prijs_canoniek, token0_decimals=_t0_dec, token1_decimals=_t1_dec,\n",
            "        )\n",
            "        # compute_position_amounts() geeft terug in CANONIEKE volgorde --\n",
            "        # HBAR kan dus amount0 OF amount1 zijn, afhankelijk van het netwerk.\n",
            "        if not _hbar_is_token0:\n",
            "            positie_hbar, positie_sauce = positie_sauce, positie_hbar\n",
            "        positie_waarde_usd = positie_hbar * hbar_price_usd + positie_sauce * sauce_price_usd\n",
            "        UINT128_MAX = (2 ** 128) - 1\n",
            "        try:\n",
            "            fee_amount0_raw, fee_amount1_raw = position_manager.functions.collect(\n",
            "                (positie[\"token_id\"], client.address, UINT128_MAX, UINT128_MAX)\n",
            "            ).call({\"from\": client.address})\n",
            "            if _hbar_is_token0:\n",
            "                fee_hbar = fee_amount0_raw / (10 ** 8)\n",
            "                fee_sauce = fee_amount1_raw / (10 ** base.usdc_decimals)\n",
            "            else:\n",
            "                fee_sauce = fee_amount0_raw / (10 ** base.usdc_decimals)\n",
            "                fee_hbar = fee_amount1_raw / (10 ** 8)\n",
            "        except Exception as e:\n",
            "            print(f\"[waarschuwing] Kon opgebouwde fees niet opvragen: {e}\")\n",
            "            fee_hbar, fee_sauce = 0.0, 0.0\n",
            "        fee_waarde_usd = fee_hbar * hbar_price_usd + fee_sauce * sauce_price_usd\n",
            "        # Canonieke prijsgrenzen berekenen (consistent met de canonieke\n",
            "        # ticks), pas daarna terugrekenen naar mensvriendelijke schaal --\n",
            "        # omkeren wisselt ook welke grens \"onder\" en welke \"boven\" is.\n",
            "        _prijs_onder_canoniek = tick_to_price(positie[\"tick_lower\"], _t0_dec, _t1_dec)\n",
            "        _prijs_boven_canoniek = tick_to_price(positie[\"tick_upper\"], _t0_dec, _t1_dec)\n",
            "        if _prijs_boven_canoniek > _prijs_onder_canoniek:\n",
            "            positie_in_range_pct = (\n",
            "                (_prijs_canoniek - _prijs_onder_canoniek) / (_prijs_boven_canoniek - _prijs_onder_canoniek) * 100\n",
            "            )\n",
            "        else:\n",
            "            positie_in_range_pct = 50.0\n",
            "        if _hbar_is_token0:\n",
            "            prijs_onder, prijs_boven = _prijs_onder_canoniek, _prijs_boven_canoniek\n",
            "        else:\n",
            "            prijs_onder = 1.0 / _prijs_boven_canoniek if _prijs_boven_canoniek > 0 else 0.0\n",
            "            prijs_boven = 1.0 / _prijs_onder_canoniek if _prijs_onder_canoniek > 0 else 0.0\n",
        ]
        regels[start_idx:eind_idx+1] = nieuwe_regels
        with open("/root/hbar_bot/bot_data.py", "w") as f:
            f.writelines(regels)
        print("Correct bijgewerkt.")
