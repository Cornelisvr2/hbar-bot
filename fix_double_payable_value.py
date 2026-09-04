with open("/root/hbar_bot/lp_manager.py", "r") as f:
    inhoud = f.read()

oud = """        payable_value = 0
        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() == whbar_lower:
                decimal_correction = 10 ** (18 - self.config.token0_decimals)
                payable_value = amount0_desired * decimal_correction
            elif self.config.token1.lower() == whbar_lower:
                decimal_correction = 10 ** (18 - self.config.token1_decimals)
                payable_value = amount1_desired * decimal_correction"""

nieuw = """        # BUGFIX (4 sep 2026, KRITIEK, gevonden na herhaalde live
        # "Insufficient funds for transfer"-fouten): payable_value stuurde
        # voorheen het VOLLEDIGE amount0_desired/amount1_desired NOGMAALS
        # als msg.value -- BOVENOP wat stap 1 (wrapWhbar()) al had
        # omgezet. Na het wrappen is dat bedrag niet meer native
        # beschikbaar (alleen de reserve nog), dus het versturen zelf
        # mislukte al vóór er uberhaupt iets gerefund kon worden --
        # ongeacht dat refundETH() het ongebruikte deel terecht
        # teruggeeft, moet je EERST genoeg native saldo hebben om het te
        # VERSTUREN. Nu een klein, symbolisch bedrag (WHBAR_SYMBOLIC_
        # MSG_VALUE_TINYBAR, standaard 1 HBAR) i.p.v. het volledige
        # positiebedrag -- voldoende om aan mint()'s "msg.value > 0
        # zodra een token WHBAR is"-eis te voldoen, zonder het al-
        # gewrapte bedrag dubbel te versturen. Op verzoek: mag uit de
        # reserve komen (die is er juist voor fees/gas), mag alleen
        # nooit het volledige positiebedrag zijn.
        WHBAR_SYMBOLIC_MSG_VALUE_TINYBAR = 10 ** 8  # 1 HBAR, in tinybar
        payable_value = 0
        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() == whbar_lower or self.config.token1.lower() == whbar_lower:
                payable_value = WHBAR_SYMBOLIC_MSG_VALUE_TINYBAR * (10 ** 10)"""

aantal = inhoud.count(oud)
print(f"Aantal gevonden matches: {aantal}")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/lp_manager.py", "w") as f:
        f.write(inhoud)
    print("Correct bijgewerkt.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
