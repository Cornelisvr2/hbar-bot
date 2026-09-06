"""
Voegt gerichte diagnostische print-statements toe op elke stap tussen
"if swap_success:" en de open_position()-poging, om exact te
isoleren waar het "stille niets"-pad ophoudt (6 sep 2026, vervolg-
onderzoek).
"""
with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    inhoud = f.read()

vervangingen = [
    (
        "                if swap_success:\n                    hbar_balance = self._get_swappable_hbar_balance(current_price)",
        "                if swap_success:\n                    print(\"[DIAGNOSE-stap] 1: if swap_success: bereikt\")\n                    hbar_balance = self._get_swappable_hbar_balance(current_price)",
    ),
    (
        "                    except Exception:\n                        fresh_price = current_price  # val terug op de oude prijs als ophalen faalt\n                    combined_score_now = compute_fixed_combined_score(self._cached_btc_score, self._cached_hbar_score)",
        "                    except Exception:\n                        fresh_price = current_price  # val terug op de oude prijs als ophalen faalt\n                    print(f\"[DIAGNOSE-stap] 2: fresh_price ververst = {fresh_price}\")\n                    combined_score_now = compute_fixed_combined_score(self._cached_btc_score, self._cached_hbar_score)",
    ),
    (
        "                        confidence_level=self._determine_gbm_confidence_level(combined_score_now),\n                    )\n\n                    hbar_raw_available = int(hbar_balance * (10 ** self._hbar_decimals))",
        "                        confidence_level=self._determine_gbm_confidence_level(combined_score_now),\n                    )\n                    print(f\"[DIAGNOSE-stap] 3: range berekend, tick_lower={tick_lower}, tick_upper={tick_upper}\")\n\n                    hbar_raw_available = int(hbar_balance * (10 ** self._hbar_decimals))",
    ),
    (
        "                    hbar_to_deploy = hbar_raw / (10 ** self._hbar_decimals)\n                    usdc_to_deploy = usdc_raw / (10 ** self._usdc_decimals)\n                    # BUGFIX (6 sep 2026): prijs NOGMAALS verversen,",
        "                    hbar_to_deploy = hbar_raw / (10 ** self._hbar_decimals)\n                    usdc_to_deploy = usdc_raw / (10 ** self._usdc_decimals)\n                    print(f\"[DIAGNOSE-stap] 4: bedragen berekend, hbar_raw={hbar_raw}, usdc_raw={usdc_raw}\")\n                    # BUGFIX (6 sep 2026): prijs NOGMAALS verversen,",
    ),
    (
        "                    except Exception:\n                        mint_price = fresh_price\n                    try:\n                        self.lp_manager.open_position(",
        "                    except Exception:\n                        mint_price = fresh_price\n                    print(f\"[DIAGNOSE-stap] 5: vlak voor open_position(), mint_price={mint_price}\")\n                    try:\n                        self.lp_manager.open_position(",
    ),
]

totaal = 0
for oud, nieuw in vervangingen:
    aantal = inhoud.count(oud)
    print(f"Patroon (lengte {len(oud)} tekens) -- gevonden: {aantal}")
    if aantal == 1:
        inhoud = inhoud.replace(oud, nieuw)
        totaal += 1
    else:
        print(f"  WAARSCHUWING: geen unieke match voor dit patroon!")

print(f"\nTotaal toegepast: {totaal} van {len(vervangingen)}")

with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
    f.write(inhoud)
