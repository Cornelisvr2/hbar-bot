"""
KRITIEKE STRUCTURELE BUGFIX (6 sep 2026): open_position() ontvangt
amount0_desired/amount1_desired ALTIJD als (hbar_raw, usdc_raw) van
ALLE 4 aanroepers in regime_orchestrator.py -- maar gebruikt
self.config.token0/token1 (de CANONIEKE volgorde) om te bepalen welk
bedrag WHBAR is (voor de wrap-stap) EN om de MintParams-struct te
bouwen. Op testnet klopt dit toevallig (WHBAR=token0 daar), maar op
mainnet is USDC canoniek token0 -- waardoor de functie het USDC-bedrag
verwisselt met het HBAR-bedrag. Dit verklaart zowel de herhaalde,
terugkerende "0.2317 WHBAR vastzittend"-meldingen (het USDC-bedrag
werd gewrapt als HBAR) als de aanhoudende "Price slippage check"-
fouten (het contract kreeg de bedragen aan de verkeerde kant
toegewezen).

Fix: bij binnenkomst van de functie ÉÉN keer herordenen naar de
canonieke volgorde, en DAARNA consistent die canonieke variabelen
gebruiken -- de functie-PARAMETERS blijven ongewijzigd (amount0_
desired/amount1_desired, zoals alle aanroepers ze al doorgeven, altijd
HBAR eerst), alleen de INTERNE verwerking wordt canoniek-bewust.
"""
with open("/root/hbar_bot/lp_manager.py", "r") as f:
    inhoud = f.read()

oud = '''        # Stap 1: HBAR EXPLICIET inwikkelen tot echte WHBAR-ERC20-tokens
        # (26 aug 2026 -- zie uitgebreide toelichting hierboven).
        if self.config.whbar_address and self.whbar_helper:
            whbar_lower = self.config.whbar_address.lower()
            whbar_amount_needed = None
            if self.config.token0.lower() == whbar_lower:
                whbar_amount_needed = amount0_desired
                whbar_decimals = self.config.token0_decimals
            elif self.config.token1.lower() == whbar_lower:
                whbar_amount_needed = amount1_desired
                whbar_decimals = self.config.token1_decimals

            if whbar_amount_needed is not None:
                wrap_value_wei = whbar_amount_needed * (10 ** (18 - whbar_decimals))
                wrap_fn = self.whbar_helper.functions.wrapWhbar()
                wrap_tx = self.rpc_client.build_and_send_transaction(wrap_fn, value_wei=wrap_value_wei)
                self.rpc_client.wait_for_receipt(wrap_tx)
                time.sleep(2)  # zelfde nonce-timing-marge als elders in dit bestand'''

nieuw = '''        # KRITIEKE STRUCTURELE BUGFIX (6 sep 2026): amount0_desired/
        # amount1_desired komen van de aanroeper ALTIJD als (hbar_raw,
        # usdc_raw) -- maar deze functie moet ze in CANONIEKE
        # (token0, token1)-volgorde gebruiken voor de wrap-stap en de
        # MintParams-struct. Op mainnet (USDC=token0, WHBAR=token1)
        # werden deze eerder verwisseld -- verklaart zowel de
        # herhaaldelijk terugkerende "0.2317 WHBAR vastzittend"-
        # meldingen (USDC-bedrag gewrapt als HBAR) als de aanhoudende
        # "Price slippage check"-fouten (bedragen aan de verkeerde
        # token toegewezen in de MintParams-struct).
        hbar_is_token0 = (
            self.config.whbar_address is not None
            and self.config.token0.lower() == self.config.whbar_address.lower()
        )
        if hbar_is_token0:
            canonical_amount0_desired = amount0_desired  # HBAR
            canonical_amount1_desired = amount1_desired  # USDC
        else:
            canonical_amount0_desired = amount1_desired  # USDC (canoniek token0 op mainnet)
            canonical_amount1_desired = amount0_desired  # HBAR (canoniek token1 op mainnet)

        # Stap 1: HBAR EXPLICIET inwikkelen tot echte WHBAR-ERC20-tokens
        # (26 aug 2026 -- zie uitgebreide toelichting hierboven).
        if self.config.whbar_address and self.whbar_helper:
            whbar_lower = self.config.whbar_address.lower()
            whbar_amount_needed = None
            if self.config.token0.lower() == whbar_lower:
                whbar_amount_needed = canonical_amount0_desired
                whbar_decimals = self.config.token0_decimals
            elif self.config.token1.lower() == whbar_lower:
                whbar_amount_needed = canonical_amount1_desired
                whbar_decimals = self.config.token1_decimals

            if whbar_amount_needed is not None:
                wrap_value_wei = whbar_amount_needed * (10 ** (18 - whbar_decimals))
                wrap_fn = self.whbar_helper.functions.wrapWhbar()
                wrap_tx = self.rpc_client.build_and_send_transaction(wrap_fn, value_wei=wrap_value_wei)
                self.rpc_client.wait_for_receipt(wrap_tx)
                time.sleep(2)  # zelfde nonce-timing-marge als elders in dit bestand'''

aantal = inhoud.count(oud)
print(f"Aantal gevonden (wrap-logica): {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/lp_manager.py", "w") as f:
        f.write(inhoud)
    print("Wrap-logica gecorrigeerd.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
