with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    inhoud = f.read()

oud = """    # HERZIEN (4 sep 2026, gevonden na een "Insufficient funds for
    # transfer"-fout op de RPC-node zelf, tijdens het heropenen na een
    # reflex-uitstap): 50 HBAR bleek niet ruim genoeg voor de
    # CUMULATIEVE gaskosten van een volledige reeks transacties achter
    # elkaar (balancerings-swap + wrap + approve + de uiteindelijke
    # mint) -- elke stap consumeert op zichzelf al wat natieve HBAR aan
    # gas, en tegen de tijd dat de LAATSTE stap (de mint zelf, met zijn
    # eigen kleine fee + gas) aan de beurt was, bleek er soms simpelweg
    # te weinig natieve HBAR meer over. Verdubbeld naar 100 HBAR,
    # AANNAME, geen empirisch exact geijkte waarde -- ruim voldoende
    # marge voor zo'n meerstaps-reeks.
    MIN_GAS_RESERVE_HBAR = 100.0"""
nieuw = "    MIN_GAS_RESERVE_HBAR = 50.0"

aantal = inhoud.count(oud)
print(f"Aantal gevonden matches: {aantal}")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
        f.write(inhoud)
    print("Teruggedraaid naar 50 HBAR.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
