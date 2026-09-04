with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    inhoud = f.read()

oud = "    MIN_GAS_RESERVE_HBAR = 50.0"
nieuw = """    # HERZIEN (4 sep 2026, EMPIRISCH BEVESTIGD na twee losse, live
    # "Insufficient funds for transfer"-fouten -- de eerste keer werd dit
    # ten onrechte toegeschreven aan een verouderde balans-cache
    # (teruggedraaid op verzoek); die fix loste het echter NIET op bij
    # een tweede, herhaalde test, wat de ECHTE oorzaak blootlegde:
    #
    # Dit is GEEN kwestie van "de reserve gebruiken voor de pool-
    # inhoud" (die zorg blijft terecht en onveranderd) -- het gaat om
    # wat het NETWERK vooraf blokkeert als garantie (gas_limit x
    # max_fee_per_gas, bij open_position()'s gas_limit_override van
    # 1.200.000) VOORDAT een transactie uberhaupt wordt uitgevoerd, ook
    # al wordt er uiteindelijk maar een fractie daarvan daadwerkelijk in
    # rekening gebracht. 50 HBAR bleek deze gereserveerde marge niet
    # altijd te dekken. Verdubbeld naar 100 HBAR, AANNAME, geen
    # empirisch exact geijkte waarde -- de reserve zelf wordt nog steeds
    # NOOIT bewust ingezet als positie-kapitaal (dat principe blijft
    # onveranderd), dit vergroot alleen de marge voor wat het netwerk
    # vooraf kan blokkeren.
    MIN_GAS_RESERVE_HBAR = 100.0"""

aantal = inhoud.count(oud)
print(f"Aantal gevonden matches: {aantal}")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
        f.write(inhoud)
    print("Correct bijgewerkt naar 100 HBAR, met de herziene onderbouwing.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
