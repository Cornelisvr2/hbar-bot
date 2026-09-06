"""
Structurele bugfix (6 sep 2026): de kern-oorzaak van de mainnet-
"Sent zero hbar"/absurde-bedragen-fout. compute_amount1_for_amount0()
behandelt het eerste bedrag altijd als "canoniek token0" -- onze code
gaf hier altijd het HBAR-bedrag aan mee, wat op testnet toevallig
klopte (WHBAR=token0 daar) maar niet op mainnet (USDC=token0 daar).

Twee nieuwe, centrale hulpmethoden op LpManager kiezen zelf de juiste
onderliggende functie + parametervolgorde, ongeacht welk token
canoniek token0/token1 is.
"""
with open("/root/hbar_bot/lp_manager.py", "r") as f:
    inhoud = f.read()

zoek_anker = "    def is_price_out_of_range(self, current_price: float) -> bool:"
aantal = inhoud.count(zoek_anker)
print(f"Anker gevonden: {aantal} keer (verwacht: 1)")

nieuwe_methoden = '''    def compute_needed_usdc_for_hbar(self, hbar_raw: int, price: float,
                                       tick_lower: int, tick_upper: int) -> int:
        """
        Berekent hoeveel USDC-raw nodig is om hbar_raw in deze range te
        matchen -- ongeacht welk token canoniek token0/token1 is (6 sep
        2026, structurele fix na de mainnet-migratie-bugs). price/
        tick_lower/tick_upper zijn ALTIJD in de canonieke, pool-eigen
        schaal (zoals get_live_pool_price()/compute_range_via_gbm() ze
        teruggeven).
        """
        from lp_manager import compute_amount0_for_amount1, compute_amount1_for_amount0
        hbar_is_token0 = (
            self.config.whbar_address is not None
            and int(self.config.token0, 16) == int(self.config.whbar_address, 16)
        )
        if hbar_is_token0:
            return compute_amount1_for_amount0(
                hbar_raw, price, tick_lower, tick_upper,
                self.config.token0_decimals, self.config.token1_decimals,
            )
        else:
            return compute_amount0_for_amount1(
                hbar_raw, price, tick_lower, tick_upper,
                self.config.token1_decimals, self.config.token0_decimals,
            )
    def compute_needed_hbar_for_usdc(self, usdc_raw: int, price: float,
                                       tick_lower: int, tick_upper: int) -> int:
        """Spiegelbeeld van compute_needed_usdc_for_hbar()."""
        from lp_manager import compute_amount0_for_amount1, compute_amount1_for_amount0
        hbar_is_token0 = (
            self.config.whbar_address is not None
            and int(self.config.token0, 16) == int(self.config.whbar_address, 16)
        )
        if hbar_is_token0:
            return compute_amount0_for_amount1(
                usdc_raw, price, tick_lower, tick_upper,
                self.config.token0_decimals, self.config.token1_decimals,
            )
        else:
            return compute_amount1_for_amount0(
                usdc_raw, price, tick_lower, tick_upper,
                self.config.token1_decimals, self.config.token0_decimals,
            )
'''

if aantal == 1:
    inhoud = inhoud.replace(zoek_anker, nieuwe_methoden + zoek_anker)
    with open("/root/hbar_bot/lp_manager.py", "w") as f:
        f.write(inhoud)
    print("Nieuwe methoden toegevoegd aan lp_manager.py.")
else:
    print("WAARSCHUWING: anker niet uniek gevonden -- NIET aangepast.")
