with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

doelregel = '                        f"+ {usdc_raw/(10**self._usdc_decimals):.2f} USDC in de pool."\n'
gevonden_op = [i for i, regel in enumerate(regels) if regel == doelregel]
print(f"Aantal exacte matches: {len(gevonden_op)}")

if len(gevonden_op) == 1:
    i = gevonden_op[0]
    # De regel erna is de sluitende ')' van send_telegram_message(...) --
    # we voegen de nieuwe aanroep DAARNA toe (regel i+2).
    invoegpunt = i + 2
    nieuwe_regels = [
        "                    # NIEUW (4 sep 2026, op verzoek): direct na een\n",
        "                    # geslaagde heropening proberen om eventueel\n",
        "                    # restkapitaal (door balancerings-onnauwkeurigheid\n",
        "                    # of een kleine prijsbeweging tussen berekening en\n",
        "                    # daadwerkelijke mint) METEEN bij te storten, zonder\n",
        "                    # op de normale cooldown te wachten -- voorkomt dat\n",
        "                    # het te lang los blijft staan terwijl de prijs\n",
        "                    # intussen verder wegdrijft.\n",
        "                    await self._deploy_excess_capital_if_available(current_price, bypass_cooldown=True)\n",
    ]
    regels[invoegpunt:invoegpunt] = nieuwe_regels
    with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
        f.writelines(regels)
    print("Correct toegevoegd.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
