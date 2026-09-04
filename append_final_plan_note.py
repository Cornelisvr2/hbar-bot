notitie = """

## Directe restkapitaal-bijstorting na een geslaagde heropening (4 sep 2026)

Op verzoek, na herhaaldelijk geobserveerd: een positie opent wel, maar
met te veel restkapitaal onbenut (bv. 132 van de 1.483 HBAR) -- puur
inherent aan hoe mint() werkt (accepteert alleen precies de exacte,
actuele prijsverhouding, stort de rest terug), maar het bestaande
"restkapitaal bijstorten"-mechanisme wachtte voorheen op zijn EIGEN,
normale cooldown vóórdat het voor het eerst iets probeerde -- ook vlak
na een gloednieuwe positie-opening.

OPGELOST: _deploy_excess_capital_if_available() kreeg een nieuwe,
optionele bypass_cooldown-parameter (standaard False, ongewijzigd
gedrag overal elders). Direct na een geslaagde heropening (in
_execute_transition's LP_MODE-tak, na save_active_lp_position()) wordt
deze nu METEEN aangeroepen met bypass_cooldown=True -- geeft
restkapitaal de beste kans om nog dezelfde cyclus bijgestort te worden,
vóórdat de prijs verder wegdrijft en het weer moeilijker wordt.

Geverifieerd: syntax, EN handmatig bevestigd dat de aanroep op de
juiste plek en inspringing staat (binnen de try-blok, na de succes-
melding, vóór de except). NOG NIET live bevestigd met een daadwerkelijk
geslaagde heropening waarbij dit in actie komt."""

with open("/root/hbar_bot/PLAN.md", "a") as f:
    f.write(notitie)
print("Toegevoegd aan PLAN.md.")
