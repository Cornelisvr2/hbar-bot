"""
BUGFIX (6 sep 2026): "Totale kosten (30d)" telde alleen gas van
swap-transacties uit onze eigen trades-tabel -- miste mint-, wrap-,
unwrap-, en bijstort-transacties, die vandaag juist het merendeel van
het gasverbruik vormden. Nieuwe, uitgebreide berekening die ALLE
eigen transactiekosten via de mirror node optelt (zelfde detectie-
methode als get_total_deposits_hbar: onderscheid via de
transaction_id-prefix -- hier juist het OMGEKEERDE doel, WEL onze
eigen/relay-geinitieerde transacties meetellen, aangezien dat precies
de kosten zijn die WIJ droegen).
"""
with open("/root/hbar_bot/dashboard_server.py", "r") as f:
    inhoud = f.read()

oud = "        # Transactiegeschiedenis (laatste 30, uit de trades-tabel).\n        trades = await db.get_recent_trades(limit=30)"

nieuw = '''        # BUGFIX (6 sep 2026): omvattende gaskosten-berekening via de
        # mirror node -- de oude berekening (verderop, uit de trades-
        # tabel) telde alleen swap-gas, miste mint/wrap/unwrap/bijstort.
        async def _bereken_omvattende_gaskosten_30d():
            import requests
            mirror_node_url = NETWORK_SETTINGS[HEDERA_NETWORK]["mirror_node_url"]
            resp = requests.get(
                f"{mirror_node_url}/api/v1/accounts/{data[\'wallet_address\']}", timeout=15
            )
            resp.raise_for_status()
            hedera_account_id = resp.json().get("account")
            if not hedera_account_id:
                return 0.0
            dertig_dagen_geleden_ts = time.time() - 30 * 86400
            bekende_relay_accounts = {"0.0.7314364", "0.0.995584"}
            totaal_tinybar = 0
            volgende_url = (
                f"{mirror_node_url}/api/v1/transactions"
                f"?account.id={hedera_account_id}&order=desc&limit=100"
                f"&timestamp=gte:{dertig_dagen_geleden_ts:.0f}"
            )
            pagina_teller = 0
            while volgende_url and pagina_teller < 20:  # veiligheidsgrens
                resp = requests.get(f"{mirror_node_url}{volgende_url}" if volgende_url.startswith("/") else volgende_url, timeout=15)
                resp.raise_for_status()
                pagina = resp.json()
                for tx in pagina.get("transactions", []):
                    tx_id = tx.get("transaction_id", "")
                    initiator = tx_id.split("-")[0] if tx_id else ""
                    if initiator == hedera_account_id or initiator in bekende_relay_accounts:
                        totaal_tinybar += tx.get("charged_tx_fee", 0) or 0
                volgende_link = pagina.get("links", {}).get("next")
                volgende_url = volgende_link
                pagina_teller += 1
            return totaal_tinybar / (10 ** 8)

        try:
            totale_kosten_30d_omvattend = await _bereken_omvattende_gaskosten_30d()
        except Exception as e:
            print(f"[waarschuwing] Kon omvattende gaskosten niet berekenen: {e}")
            totale_kosten_30d_omvattend = None

        # Transactiegeschiedenis (laatste 30, uit de trades-tabel).
        trades = await db.get_recent_trades(limit=30)'''

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
else:
    print("WAARSCHUWING: geen unieke match voor deel 1 -- NIET aangepast.")
    exit()

# Tweede deel: de UITEINDELIJKE totale_kosten_30d-waarde vervangen
# door de omvattende versie, ALS die beschikbaar is.
oud2 = '"total_costs_30d": totale_kosten_30d,'
nieuw2 = '"total_costs_30d": totale_kosten_30d_omvattend if totale_kosten_30d_omvattend is not None else totale_kosten_30d,'
aantal2 = inhoud.count(oud2)
print(f"Aantal gevonden (deel 2): {aantal2} (verwacht: 1)")
if aantal2 == 1:
    inhoud = inhoud.replace(oud2, nieuw2)
    with open("/root/hbar_bot/dashboard_server.py", "w") as f:
        f.write(inhoud)
    print("Beide delen bijgewerkt.")
else:
    print("WAARSCHUWING: geen unieke match voor deel 2 -- NIET aangepast.")
