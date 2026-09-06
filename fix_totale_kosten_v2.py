with open("/root/hbar_bot/dashboard_server.py", "r") as f:
    inhoud = f.read()

oud = '''        async def _bereken_omvattende_gaskosten_30d():
            import requests
            mirror_node_url = NETWORK_SETTINGS[HEDERA_NETWORK]["mirror_node_url"]'''

nieuw = '''        async def _bereken_omvattende_gaskosten_30d():
            import requests
            from config import NETWORK_SETTINGS
            mirror_node_url = NETWORK_SETTINGS[HEDERA_NETWORK]["mirror_node_url"]'''

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/dashboard_server.py", "w") as f:
        f.write(inhoud)
    print("Lokale import toegevoegd.")
else:
    print("WAARSCHUWING: geen unieke match.")
