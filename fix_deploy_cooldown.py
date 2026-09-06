"""
BUGFIX (6 sep 2026, empirisch bevestigd -- veroorzaakte een
herhaal-lus zonder rem toen deploy_additional_capital() faalde door de
ontbrekende wrap-stap): _last_capital_deploy_at werd alleen bij
SUCCES bijgewerkt, waardoor elke mislukking de cooldown volledig
omzeilde en de volgende cyclus (na maar ~1 minuut) meteen opnieuw
probeerde -- zelfde patroon als eerder al gerepareerd bij het
vangnet ("ALTIJD zetten, ongeacht succes/falen").
"""
with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    inhoud = f.read()

oud = '''        try:
            tx_hash = self.lp_manager.deploy_additional_capital(
                self.lp_manager.state.token_id, hbar_raw, usdc_raw,
            )
            if tx_hash:
                telegram_notify.send_telegram_message(
                    f"Overtollig kapitaal automatisch bijgestort in positie "
                    f"{self.lp_manager.state.token_id}: "
                    f"{hbar_balance:.4f} HBAR + {usdc_balance:.2f} SAUCE."
                )
                self._last_capital_deploy_at = time.time()
            else:
                telegram_notify.report_error(
                    "regime_loop: kapitaal bijstorten",
                    "increaseLiquidity() gaf geen succesvolle receipt terug.",
                )
        except Exception as e:
            telegram_notify.report_error("regime_loop: kapitaal bijstorten", str(e))'''

nieuw = '''        # BUGFIX (6 sep 2026): cooldown ALTIJD zetten, ongeacht succes/
        # falen -- voorkomt een herhaal-lus zonder rem bij elke
        # mislukking (zelfde patroon als eerder al gerepareerd bij het
        # vangnet).
        self._last_capital_deploy_at = time.time()
        try:
            tx_hash = self.lp_manager.deploy_additional_capital(
                self.lp_manager.state.token_id, hbar_raw, usdc_raw,
            )
            if tx_hash:
                telegram_notify.send_telegram_message(
                    f"Overtollig kapitaal automatisch bijgestort in positie "
                    f"{self.lp_manager.state.token_id}: "
                    f"{hbar_balance:.4f} HBAR + {usdc_balance:.2f} SAUCE."
                )
            else:
                telegram_notify.report_error(
                    "regime_loop: kapitaal bijstorten",
                    "increaseLiquidity() gaf geen succesvolle receipt terug.",
                )
        except Exception as e:
            telegram_notify.report_error("regime_loop: kapitaal bijstorten", str(e))'''

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
        f.write(inhoud)
    print("Gecorrigeerd.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
