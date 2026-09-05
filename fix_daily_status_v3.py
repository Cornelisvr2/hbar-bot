with open("/root/hbar_bot/daily_status_report.py", "r") as f:
    regels = f.readlines()

start_idx = None
for i, regel in enumerate(regels):
    if regel.strip() == "base = resolve_testnet_addresses()":
        start_idx = i
        break

if start_idx is None:
    print("WAARSCHUWING: startregel niet gevonden -- mogelijk al eerder bijgewerkt.")
else:
    eind_idx = None
    for j in range(start_idx, start_idx + 20):
        if "sauce_address, 3000, 8, 6," in regels[j]:
            eind_idx = j
            break
    print(f"start_idx={start_idx}, eind_idx={eind_idx}")

    if eind_idx is None:
        print("WAARSCHUWING: eindregel niet gevonden -- NIET aangepast.")
    else:
        nieuwe_regels = [
            "    # BUGFIX (4 sep 2026, gevonden tijdens de mainnet-migratie, zelfde\n",
            "    # patroon als eerder in bot_data.py gerepareerd): dit was volledig\n",
            "    # hardgecodeerd naar testnet.\n",
            "    if HEDERA_NETWORK == \"mainnet\":\n",
            "        base = resolve_mainnet_addresses()\n",
            "        v2 = resolve_mainnet_v2_addresses()\n",
            "    else:\n",
            "        base = resolve_testnet_addresses()\n",
            "        v2 = resolve_testnet_v2_addresses()\n",
            "    # 1. Wallet-saldo\n",
            "    hbar_balance = float(client.get_hbar_balance())\n",
            "    quote_address = base.usdc  # SAUCE op testnet, echte USDC op mainnet\n",
            "    quote_contract = client.w3.eth.contract(address=quote_address, abi=ERC20_ABI)\n",
            "    sauce_balance = quote_contract.functions.balanceOf(client.address).call() / (10 ** base.usdc_decimals)\n",
            "    whbar_contract = client.w3.eth.contract(address=base.whbar_token, abi=ERC20_ABI)\n",
            "    whbar_stuck = whbar_contract.functions.balanceOf(client.address).call() / (10 ** 8)\n",
            "    # 2. Prijzen: de ECHTE USD-prijs van HBAR (GeckoTerminal), EN de\n",
            "    # pool's eigen, interne SAUCE-per-HBAR-koers (rechtstreeks via\n",
            "    # slot0()) -- zie bestandskop hierboven voor waarom dit TWEE\n",
            "    # verschillende, beide benodigde grootheden zijn.\n",
            "    gecko = GeckoTerminalClient()\n",
            "    hbar_price_usd = gecko.get_pool_snapshot().price_usd\n",
            "    fee_tier = int(os.environ.get(\"LP_FEE_TIER\", \"3000\"))\n",
            "    pool_price_sauce_per_hbar = get_live_pool_price(\n",
            "        client, v2.factory, base.whbar_token, quote_address, fee_tier, 8, base.usdc_decimals,\n",
        ]
        regels[start_idx:eind_idx+1] = nieuwe_regels

        with open("/root/hbar_bot/daily_status_report.py", "w") as f:
            f.writelines(regels)
        print("Correct bijgewerkt.")
