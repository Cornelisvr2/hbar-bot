with open("/root/hbar_bot/bot_data.py", "r") as f:
    inhoud = f.read()

oud = '    BEKENDE_RELAY_ACCOUNTS = {"0.0.7314364"}'
nieuw = ('    # BUGFIX (6 sep 2026): mainnet-relay-account toegevoegd -- 0.0.995584\n'
         '    # geverifieerd als de consequente initiator van al onze\n'
         '    # ETHEREUMTRANSACTION-aanroepen op mainnet (via de mirror-node-\n'
         '    # transactiegeschiedenis, zelfde detectiemethode als de testnet-\n'
         '    # ontdekking hiervoor).\n'
         '    BEKENDE_RELAY_ACCOUNTS = {"0.0.7314364", "0.0.995584"}')

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/bot_data.py", "w") as f:
        f.write(inhoud)
    print("Bijgewerkt.")
else:
    print("WAARSCHUWING: geen unieke match.")
