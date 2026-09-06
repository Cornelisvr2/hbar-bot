"""
Vervangt de "raad de helft van het tekort, geef anders op"-heuristiek
door een wiskundig exacte, ÉÉN-staps-berekening (6 sep 2026, op
verzoek naar aanleiding van het inzicht dat de oude aanpak een
volledig eenzijdige positie -- bv. na een BEARISH_REFLEX-uitstap --
NOOIT terug de pool in kon krijgen).

Kernidee: bij een gegeven prijs en tick-range is de HBAR:USDC-
verhouding die een positie nodig heeft VAST, ongeacht de hoeveelheid
(Uniswap V3-liquiditeit is lineair). Bereken die verhouding één keer
(via de al-bestaande compute_needed_usdc_for_hbar met een
referentie-eenheid), los daarna algebraisch op hoeveel er in totaal
naar elke kant moet gegeven de TOTALE beschikbare waarde -- en swap
in een enkele stap naar dat doel.
"""
with open("/root/hbar_bot/lp_manager.py", "r") as f:
    inhoud = f.read()

zoek_anker = "    def is_price_out_of_range(self, current_price: float) -> bool:"
aantal = inhoud.count(zoek_anker)
print(f"Anker gevonden: {aantal} keer (verwacht: 1)")

nieuwe_methode = '''    def compute_optimal_swap_for_position(self, hbar_raw: int, usdc_raw: int,
                                            price: float, tick_lower: int, tick_upper: int,
                                            min_swap_fraction: float = 0.005) -> tuple:
        """
        Berekent in EEN, wiskundig exacte stap hoeveel en in welke
        richting geswapt moet worden om de juiste HBAR:USDC-verhouding
        voor deze positie te bereiken -- werkt ook vanuit een volledig
        eenzijdige startpositie (bv. na een reflex-uitstap), i.p.v. de
        oude "raad de helft van het tekort, geef anders op"-heuristiek
        (6 sep 2026: die kon een 100%-eenzijdige positie NOOIT
        balanceren, aangezien het berekende swap-bedrag dan per
        definitie de volledige, eenzijdige balans kon overschrijden).

        Retourneert (richting, bedrag_raw) -- richting is
        "HBAR_TO_USDC", "USDC_TO_HBAR", of None als al voldoende
        gebalanceerd (binnen min_swap_fraction van de HBAR-waarde,
        met een absolute ondergrens van 0.01 HBAR om micro-swaps met
        alleen gaskosten te voorkomen).
        """
        hbar_is_token0 = (
            self.config.whbar_address is not None
            and int(self.config.token0, 16) == int(self.config.whbar_address, 16)
        )
        hbar_decimals = self.config.token0_decimals if hbar_is_token0 else self.config.token1_decimals
        usdc_decimals = self.config.token1_decimals if hbar_is_token0 else self.config.token0_decimals
        referentie_hbar_raw = 10 ** hbar_decimals  # 1 HBAR als referentie-eenheid
        referentie_usdc_needed_raw = self.compute_needed_usdc_for_hbar(
            referentie_hbar_raw, price, tick_lower, tick_upper
        )
        k = referentie_usdc_needed_raw / (10 ** usdc_decimals)  # benodigde USDC per 1 HBAR, voor DEZE prijs/range
        hbar_have_h = hbar_raw / (10 ** hbar_decimals)
        usdc_have_h = usdc_raw / (10 ** usdc_decimals)
        totale_waarde_usdc = hbar_have_h * price + usdc_have_h
        if (price + k) <= 0 or totale_waarde_usdc <= 0:
            return (None, 0)
        target_hbar_h = totale_waarde_usdc / (price + k)
        verschil_hbar_h = hbar_have_h - target_hbar_h
        if abs(verschil_hbar_h) < max(hbar_have_h * min_swap_fraction, 0.01):
            return (None, 0)
        if verschil_hbar_h > 0:
            swap_raw = int(verschil_hbar_h * (10 ** hbar_decimals))
            return ("HBAR_TO_USDC", swap_raw)
        else:
            usdc_swap_h = abs(verschil_hbar_h) * price
            swap_raw = int(usdc_swap_h * (10 ** usdc_decimals))
            return ("USDC_TO_HBAR", swap_raw)
'''

if aantal == 1:
    inhoud = inhoud.replace(zoek_anker, nieuwe_methode + zoek_anker)
    with open("/root/hbar_bot/lp_manager.py", "w") as f:
        f.write(inhoud)
    print("Nieuwe methode toegevoegd.")
else:
    print("WAARSCHUWING: anker niet uniek -- NIET aangepast.")
