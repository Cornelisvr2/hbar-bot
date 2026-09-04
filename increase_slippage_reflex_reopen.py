with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

doelregel = "                        slippage_tolerance=0.15,\n"
gevonden_op = [i for i, regel in enumerate(regels) if regel == doelregel]
print(f"Aantal exacte matches: {len(gevonden_op)}")

if len(gevonden_op) == 1:
    i = gevonden_op[0]
    regels[i] = "                        slippage_tolerance=0.30,\n"
    # Toelichting ervoor invoegen
    toelichting = [
        "                        # Verruimd naar 30% (4 sep 2026, op verzoek) --\n",
        "                        # deze dunne testnet-pool blijkt door ONZE EIGEN,\n",
        "                        # relatief grote transacties (bevestigd: onze\n",
        "                        # enkele swap was al een aanzienlijk deel van het\n",
        "                        # TOTALE 24u-volume) meerdere procenten prijsimpact\n",
        "                        # te ondervinden binnen een enkele herbalancerings-\n",
        "                        # reeks -- op mainnet, met veel diepere liquiditeit,\n",
        "                        # zou dezelfde transactiegrootte een verwaarloosbare\n",
        "                        # impact hebben. Puur een testnet-aanpassing.\n",
    ]
    regels[i:i] = toelichting
    with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
        f.writelines(regels)
    print("Correct bijgewerkt naar 30%.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
