with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    inhoud = f.read()

oud = """            if all_succeeded and self.lp_manager:
                # Balans NA de herbalancerings-swap opvragen, niet vooraf
                # geschat -- dat is de daadwerkelijke inzet voor de LP-positie.
                final_hbar_balance = self._get_swappable_hbar_balance(current_price)"""

nieuw = """            if all_succeeded and self.lp_manager:
                # Balans NA de herbalancerings-swap opvragen, niet vooraf
                # geschat -- dat is de daadwerkelijke inzet voor de LP-positie.
                #
                # BUGFIX (4 sep 2026, gevonden na een "Insufficient funds
                # for transfer"-fout van de RPC-node zelf): de 5-seconden-
                # cache op _get_swappable_hbar_balance() kon hier een
                # VEROUDERDE balans teruggeven als deze aanroep binnen die
                # 5 seconden na de balancerings-swap plaatsvond -- de
                # cache wist dan nog niet dat DIE swap al gas had gekost,
                # waardoor het (foutief) dacht dat er meer natieve HBAR
                # over was dan er werkelijk was. Cache expliciet ongeldig
                # maken vlak vóór deze cruciale meting dwingt een ECHTE,
                # verse RPC-aanroep af.
                self._hbar_balance_cache = None
                final_hbar_balance = self._get_swappable_hbar_balance(current_price)"""

aantal = inhoud.count(oud)
print(f"Aantal gevonden matches: {aantal}")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
        f.write(inhoud)
    print("Correct bijgewerkt.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
