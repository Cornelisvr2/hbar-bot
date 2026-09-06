"""
BUGFIX (6 sep 2026, gevonden na SaucerSwap's eigen developer-
documentatie te raadplegen): de officiele referentie-implementatie
haalt de prijs ÉÉN keer op en gebruikt DIE meteen voor zowel de
bedragen als de minimum-bedragen -- zonder een aparte, tijdrovende
transactie ertussen. Onze flow doet WEL een aparte swap-transactie
(met wachten op bevestiging) tussen het ophalen van fresh_price en
het daadwerkelijke mint()-moment, waardoor de prijs die aan
open_position() wordt meegegeven inmiddels verouderd kan zijn --
een aannemelijke verklaring voor de herhaalde "Price slippage
check"-fouten ondanks een royale marge. Fix: prijs opnieuw ophalen,
vlak vóór open_position() zelf.
"""
with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    inhoud = f.read()

oud = """                    hbar_to_deploy = hbar_raw / (10 ** self._hbar_decimals)
                    usdc_to_deploy = usdc_raw / (10 ** self._usdc_decimals)
                    try:
                        self.lp_manager.open_position(
                            hbar_raw, usdc_raw, fresh_price, slippage_tolerance=0.25,
                            gas_limit_override=1_200_000,
                            precomputed_tick_range=(tick_lower, tick_upper),
                        )"""

nieuw = """                    hbar_to_deploy = hbar_raw / (10 ** self._hbar_decimals)
                    usdc_to_deploy = usdc_raw / (10 ** self._usdc_decimals)
                    # BUGFIX (6 sep 2026): prijs NOGMAALS verversen, vlak
                    # vóór open_position() zelf -- de swap hierboven (met
                    # wachten op bevestiging) kost echte tijd, waarin de
                    # eerder opgehaalde fresh_price kan zijn verouderd.
                    # SaucerSwap's eigen developer-documentatie (new-
                    # liquidity-position.md) haalt de prijs ÉÉN keer op en
                    # gebruikt die DIRECT, zonder een tijdrovende stap
                    # ertussen -- onze flow moet dat patroon zo dicht
                    # mogelijk benaderen door hier opnieuw te verversen.
                    from lp_manager import get_live_pool_price as _get_live_pool_price_voor_mint
                    try:
                        mint_price = _get_live_pool_price_voor_mint(
                            self.rpc_client, self.lp_manager.config.factory_address,
                            self.lp_manager.config.token0, self.lp_manager.config.token1,
                            self.lp_manager.config.fee_tier,
                            self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,
                        )
                    except Exception:
                        mint_price = fresh_price
                    try:
                        self.lp_manager.open_position(
                            hbar_raw, usdc_raw, mint_price, slippage_tolerance=0.25,
                            gas_limit_override=1_200_000,
                            precomputed_tick_range=(tick_lower, tick_upper),
                        )"""

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
        f.write(inhoud)
    print("Bijgewerkt.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
