"""
Vervangt de volledige inhoud van _ensure_balanced_liquidity_ratio()
door een versie die de nieuwe, wiskundig exacte
compute_optimal_swap_for_position() gebruikt (6 sep 2026, op verzoek
na het inzicht dat de oude "helft van het tekort, geef anders op"-
aanpak een 100% eenzijdige positie NOOIT kon balanceren).
"""
with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    inhoud = f.read()

oud = '''        from lp_manager import compute_amount1_for_amount0, compute_amount0_for_amount1

        hbar_balance = self._get_swappable_hbar_balance(current_price)
        if max_hbar_to_use is not None:
            hbar_balance = min(hbar_balance, max_hbar_to_use)
        usdc_balance = self._get_swappable_usdc_balance()
        hbar_raw = int(hbar_balance * (10 ** self._hbar_decimals))
        usdc_raw = int(usdc_balance * (10 ** self._usdc_decimals))

        if hbar_raw <= 0 and usdc_raw <= 0:
            return True  # BEIDE kanten zijn leeg -- er valt niets te swappen, geen fout

        # BUGFIX (27 aug 2026): was voorheen "or" i.p.v. "and" hierboven --
        # dat liet deze functie stilzwijgend NIETS doen zodra een van beide
        # kanten compleet op 0 stond (bv. net overgekomen vanuit
        # BULLISH_REFLEX, waar per definitie 0 SAUCE aanwezig is). Daardoor
        # bleef open_position() vervolgens EVEN vals uitgaan van een reeds
        # uitgevoerde swap, en probeerde met usdc_raw_available=0 een
        # positie te minten -- wat via de proportionele berekening ook
        # hbar_raw=0 opleverde, resulterend in de "Sent zero hbar to this
        # contract"-fout. Empirisch bevestigd (27 aug 2026, tijdens de
        # overgang bullish_reflex -> lp_mode): SAUCE-balans bleef op 0.00
        # staan, exact zoals deze bug voorspelt.

        needed_usdc_for_full_hbar = self.lp_manager.compute_needed_usdc_for_hbar(
            hbar_raw, current_price, tick_lower, tick_upper,
        )

        # Diagnostische logging (30 aug 2026, op verzoek: na een
        # onverklaarde herhaal-loop in de bijstort-functie waarvan de
        # exacte oorzaak niet meer te reproduceren bleek) -- print elke
        # tussenwaarde, zodat een eventuele volgende, vergelijkbare
        # storing WEL volledig te herleiden is, i.p.v. alleen het
        # einde-swap-bedrag te zien zoals nu.
        print(f"[balans-diagnose] hbar_raw={hbar_raw} ({hbar_balance:.4f} HBAR), "
              f"usdc_raw={usdc_raw} ({usdc_balance:.4f} SAUCE), "
              f"current_price={current_price}, tick_lower={tick_lower}, tick_upper={tick_upper}, "
              f"needed_usdc_for_full_hbar={needed_usdc_for_full_hbar}")

        if needed_usdc_for_full_hbar > usdc_raw:
            # SAUCE is de beperkende kant -- swap de helft van het
            # HBAR-overschot naar SAUCE.
            excess_usdc_needed = (needed_usdc_for_full_hbar - usdc_raw) / (10 ** self._usdc_decimals)
            hbar_to_swap = (excess_usdc_needed / current_price) / 2

            # VEILIGHEIDSKLEM (30 aug 2026, HERZIEN na nazoeken) -- nooit
            # meer swappen dan daadwerkelijk in bezit. GEEN bug: bleek
            # empirisch een normaal, verwacht gevolg van geconcentreerde
            # liquiditeit dicht bij de rand van een smalle range (op dat
            # moment stond de prijs op 7,33% in de range -- vlak bij de
            # onderkant), waar de benodigde token-verhouding voor
            # NIEUWE, proportionele liquiditeit extreem kan worden. Geen
            # bug, dus GEEN alarmerende Telegram-melding meer -- alleen
            # een stille logregel. Het overtollige kapitaal wacht dan
            # gewoon op de eerstvolgende, natuurlijke herbalancering
            # (die een beter gecentreerde range kiest).
            if hbar_to_swap > hbar_balance:
                print(f"[balans-diagnose] Balanceringsklem: berekend swap-bedrag "
                      f"({hbar_to_swap:.4f} HBAR) overschrijdt de balans ({hbar_balance:.4f} HBAR) "
                      f"-- waarschijnlijk omdat de prijs dicht bij de rand van de huidige, "
                      f"smalle range staat. Wacht op de eerstvolgende herbalancering.")
                return False
            hbar_to_swap = min(hbar_to_swap, hbar_balance * 0.95)

            print(f"[balans-diagnose] SAUCE is beperkend -- excess_usdc_needed={excess_usdc_needed:.4f}, "
                  f"hbar_to_swap={hbar_to_swap:.4f}")
            if hbar_to_swap > 0.01:  # ondergrens om micro-swaps met alleen gaskosten te voorkomen
                await self._run_swap_and_log("HBAR_TO_USDC", hbar_to_swap, None)
            return True

        needed_hbar_for_full_usdc = self.lp_manager.compute_needed_hbar_for_usdc(
            usdc_raw, current_price, tick_lower, tick_upper,
        )
        print(f"[balans-diagnose] needed_hbar_for_full_usdc={needed_hbar_for_full_usdc}")
        if needed_hbar_for_full_usdc > hbar_raw:
            # HBAR is de beperkende kant -- swap de helft van het
            # SAUCE-overschot naar HBAR.
            excess_hbar_needed = (needed_hbar_for_full_usdc - hbar_raw) / (10 ** self._hbar_decimals)
            usdc_to_swap = (excess_hbar_needed * current_price) / 2

            # VEILIGHEIDSKLEM (30 aug 2026, na de eerdere, onverklaarde
            # herhaal-loop, HERZIEN na nazoeken) -- ongeacht welke
            # berekening tot dit bedrag leidde, NOOIT proberen meer te
            # swappen dan daadwerkelijk in bezit. GEEN bug (zie
            # toelichting bij de andere richting hierboven) -- daarom
            # GEEN alarmerende Telegram-melding meer, alleen stil loggen.
            if usdc_to_swap > usdc_balance:
                print(f"[balans-diagnose] Balanceringsklem: berekend swap-bedrag "
                      f"({usdc_to_swap:.4f} SAUCE) overschrijdt de balans ({usdc_balance:.4f} SAUCE) "
                      f"-- waarschijnlijk omdat de prijs dicht bij de rand van de huidige, "
                      f"smalle range staat. Wacht op de eerstvolgende herbalancering.")
                return False
            usdc_to_swap = min(usdc_to_swap, usdc_balance * 0.95)  # extra marge voor afronding/gas

            print(f"[balans-diagnose] HBAR is beperkend -- excess_hbar_needed={excess_hbar_needed:.4f}, "
                  f"usdc_to_swap={usdc_to_swap:.4f}")
            if usdc_to_swap > 1.0:  # ondergrens
                await self._run_swap_and_log("USDC_TO_HBAR", usdc_to_swap, None)
        # Anders: verhouding is al voldoende in balans, geen swap nodig.
        return True'''

nieuw = '''        # HERSCHREVEN (6 sep 2026, op verzoek): gebruikt nu
        # compute_optimal_swap_for_position() -- een wiskundig exacte,
        # ene-staps berekening -- i.p.v. de oude "raad de helft van het
        # tekort, geef anders volledig op"-heuristiek. Die oude aanpak
        # kon een 100% eenzijdige positie (bv. na een reflex-uitstap)
        # STRUCTUREEL nooit balanceren: het berekende swap-bedrag was
        # dan per definitie groter dan de eenzijdige balans, en de
        # functie gaf het simpelweg op i.p.v. het resterende, wel
        # haalbare deel te verdelen. De nieuwe berekening werkt vanuit
        # ELKE startverhouding, inclusief 0%/100%.
        hbar_balance = self._get_swappable_hbar_balance(current_price)
        if max_hbar_to_use is not None:
            hbar_balance = min(hbar_balance, max_hbar_to_use)
        usdc_balance = self._get_swappable_usdc_balance()
        hbar_raw = int(hbar_balance * (10 ** self._hbar_decimals))
        usdc_raw = int(usdc_balance * (10 ** self._usdc_decimals))

        if hbar_raw <= 0 and usdc_raw <= 0:
            return True  # BEIDE kanten zijn leeg -- er valt niets te swappen, geen fout

        richting, bedrag_raw = self.lp_manager.compute_optimal_swap_for_position(
            hbar_raw, usdc_raw, current_price, tick_lower, tick_upper,
        )
        print(f"[balans-diagnose] hbar_raw={hbar_raw} ({hbar_balance:.4f} HBAR), "
              f"usdc_raw={usdc_raw} ({usdc_balance:.4f} SAUCE), "
              f"current_price={current_price}, tick_lower={tick_lower}, tick_upper={tick_upper}, "
              f"richting={richting}, bedrag_raw={bedrag_raw}")

        if richting is None:
            return True  # al voldoende gebalanceerd, geen swap nodig

        if richting == "HBAR_TO_USDC":
            hbar_to_swap = bedrag_raw / (10 ** self._hbar_decimals)
            # Deze klem zou met de exacte berekening praktisch nooit meer
            # mogen triggeren (het berekende bedrag komt per constructie
            # nooit boven de totale, beschikbare waarde uit) -- blijft
            # als pure defensieve marge staan, en klemt nu naar 95% i.p.v.
            # volledig op te geven.
            if hbar_to_swap > hbar_balance:
                print(f"[balans-diagnose] Onverwacht: berekend swap-bedrag "
                      f"({hbar_to_swap:.4f} HBAR) overschrijdt de balans "
                      f"({hbar_balance:.4f} HBAR) -- geklemd naar 95%.")
                hbar_to_swap = hbar_balance * 0.95
            if hbar_to_swap > 0.01:  # ondergrens om micro-swaps met alleen gaskosten te voorkomen
                await self._run_swap_and_log("HBAR_TO_USDC", hbar_to_swap, None)
            return True
        else:  # richting == "USDC_TO_HBAR"
            usdc_to_swap = bedrag_raw / (10 ** self._usdc_decimals)
            if usdc_to_swap > usdc_balance:
                print(f"[balans-diagnose] Onverwacht: berekend swap-bedrag "
                      f"({usdc_to_swap:.4f} SAUCE) overschrijdt de balans "
                      f"({usdc_balance:.4f} SAUCE) -- geklemd naar 95%.")
                usdc_to_swap = usdc_balance * 0.95
            if usdc_to_swap > 1.0:  # ondergrens
                await self._run_swap_and_log("USDC_TO_HBAR", usdc_to_swap, None)
            return True'''

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
        f.write(inhoud)
    print("Vervangen.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
