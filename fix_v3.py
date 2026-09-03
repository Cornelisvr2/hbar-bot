with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

# Zoek de EXACTE regel "        from lp_manager import tick_to_price" (zonder
# de latere toevoeging), binnen _regime_drift_check(). Regel-gebaseerd,
# dus ongevoelig voor subtiele verschillen in de omliggende tekst.
doelregel = "        from lp_manager import tick_to_price\n"
gevonden_op = [i for i, regel in enumerate(regels) if regel == doelregel]
print(f"Aantal exacte matches van de doelregel: {len(gevonden_op)}")

if len(gevonden_op) == 1:
    i = gevonden_op[0]
    nieuwe_regels = [
        "        from lp_manager import tick_to_price, get_live_pool_price\n",
        "\n",
        "        try:\n",
        "            fresh_price = get_live_pool_price(\n",
        "                self.rpc_client, self.lp_manager.config.factory_address,\n",
        "                self.lp_manager.config.token0, self.lp_manager.config.token1,\n",
        "                self.lp_manager.config.fee_tier,\n",
        "                self._hbar_decimals, self._usdc_decimals,\n",
        "            )\n",
        "        except Exception as e:\n",
        "            telegram_notify.report_error(\n",
        "                \"regime_drift_check: pool-prijs opvragen\",\n",
        "                f\"{e} -- geen actie ondernomen.\",\n",
        "            )\n",
        "            return\n",
    ]
    regels[i:i+1] = nieuwe_regels
    with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
        f.writelines(regels)
    print("Correct toegevoegd, regel-gebaseerd.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
    for i, regel in enumerate(regels):
        if "from lp_manager import tick_to_price" in regel:
            print(f"Regel {i}: {repr(regel)}")
