with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    inhoud = f.read()

oud = '''                else:
                    telegram_notify.report_error(
                        "regime_loop: LP-positie openen (vangnet)",
                        "Herbalancerings-swap mislukt -- LP-positie niet geopend, "
                        "kapitaal staat los in de wallet. Vangnet probeert NIET automatisch opnieuw -- herstart de bot handmatig na controle.",
                    )'''

nieuw = '''                else:
                    # Rustige, informatieve melding (4 sep 2026, op
                    # verzoek na herhaalde vals-alarmerende meldingen
                    # elke ~30 min) -- de balancerings-swap weigerde
                    # HIER vóór enige transactie (dezelfde balanceringsklem
                    # als elders), dus kapitaal is gegarandeerd nog
                    # exact waar het was. Het vangnet probeert dit
                    # vanzelf, periodiek opnieuw (zie de cooldown
                    # hierboven) -- geen HANDMATIGE CONTROLE nodig voor
                    # dit routinematige, veilige geval.
                    print("[regime] Vangnet: herbalancerings-swap nog niet mogelijk -- "
                          "kapitaal onaangeroerd, wordt periodiek opnieuw geprobeerd.")'''

aantal = inhoud.count(oud)
print(f"Aantal gevonden matches: {aantal}")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
        f.write(inhoud)
    print("Correct bijgewerkt.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
