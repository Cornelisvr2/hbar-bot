with open("/root/hbar_bot/dashboard_server.py", "r") as f:
    inhoud = f.read()

oud = '''            richting_label = "Swap HBAR → SAUCE" if t["direction"] == "HBAR_TO_USDC" else "Swap SAUCE → HBAR"
            eenheid = "HBAR" if t["direction"] == "HBAR_TO_USDC" else "SAUCE"'''

nieuw = '''            # BUGFIX (4 sep 2026, gevonden tijdens de mainnet-migratie):
            # dit toonde altijd "SAUCE", ongeacht het netwerk -- op
            # mainnet is dit USDC.
            _tokennaam = "SAUCE" if os.environ.get("HEDERA_NETWORK", "testnet") == "testnet" else "USDC"
            richting_label = f"Swap HBAR → {_tokennaam}" if t["direction"] == "HBAR_TO_USDC" else f"Swap {_tokennaam} → HBAR"
            eenheid = "HBAR" if t["direction"] == "HBAR_TO_USDC" else _tokennaam'''

aantal = inhoud.count(oud)
print(f"Aantal gevonden matches: {aantal}")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/dashboard_server.py", "w") as f:
        f.write(inhoud)
    print("Correct bijgewerkt.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
