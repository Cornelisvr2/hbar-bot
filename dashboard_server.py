# --- bot_data.py: STRATEGIE_NAMEN ---
with open("/root/hbar_bot/bot_data.py", "r") as f:
    inhoud = f.read()

oud1 = '    "bearish_reflex": "BEARISH_REFLEX (volledig uitgestapt, alles in SAUCE)",'
nieuw1 = '''    # LET OP (4 sep 2026): dit label toont letterlijk "SAUCE" -- op
    # mainnet is dit USDC. STRATEGIE_NAMEN is een module-niveau
    # constante (geen toegang tot HEDERA_NETWORK op het moment van
    # definitie zonder herstructurering) -- als tijdelijke, eenvoudige
    # oplossing wordt dit specifieke label pas bij gebruik (in
    # fetch_dashboard_data hieronder) overschreven indien nodig.
    "bearish_reflex": "BEARISH_REFLEX (volledig uitgestapt, alles in SAUCE)",'''

aantal1 = inhoud.count(oud1)
print(f"bot_data.py STRATEGIE_NAMEN -- aantal matches: {aantal1}")
if aantal1 == 1:
    inhoud = inhoud.replace(oud1, nieuw1)
    print("Toegevoegd (toelichting).")

with open("/root/hbar_bot/bot_data.py", "w") as f:
    f.write(inhoud)

# --- dashboard_server.py: transactiegeschiedenis-labels ---
with open("/root/hbar_bot/dashboard_server.py", "r") as f:
    inhoud2 = f.read()

oud2 = '''            richting_label = "Swap HBAR → SAUCE" if t["direction"] == "HBAR_TO_USDC" else "Swap SAUCE → HBAR"
            eenheid = "HBAR" if t["direction"] == "HBAR_TO_USDC" else "SAUCE"'''
nieuw2 = '''            # BUGFIX (4 sep 2026, gevonden tijdens de mainnet-migratie):
            # dit toonde altijd "SAUCE", ongeacht het netwerk -- op
            # mainnet is dit USDC.
            _kwartaal_naam = "SAUCE" if os.environ.get("HEDERA_NETWORK", "testnet") == "testnet" else "USDC"
            richting_label = f"Swap HBAR → {_kwartaal_naam}" if t["direction"] == "HBAR_TO_USDC" else f"Swap {_kwartaal_naam} → HBAR"
            eenheid = "HBAR" if t["direction"] == "HBAR_TO_USDC" else _kwartaal_naam'''

aantal2 = inhoud2.count(oud2)
print(f"dashboard_server.py labels -- aantal matches: {aantal2}")
if aantal2 == 1:
    inhoud2 = inhoud2.replace(oud2, nieuw2)
    with open("/root/hbar_bot/dashboard_server.py", "w") as f:
        f.write(inhoud2)
    print("Correct bijgewerkt.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
