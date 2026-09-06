with open("/root/hbar_bot/mainnet_migratieplan.md", "a") as f:
    f.write("""

## Bekend, bewust ongecorrigeerd: foutieve historische waarde-snapshots (6 sep 2026)

De positiewaarde-berekening in `bot_data.py` (gebruikt door zowel het
dashboard als `hourly_snapshot.py`) bevatte tot 6 september 2026 een
canoniek/semantisch-bug die de waarde van een open LP-positie
drastisch onderschatte (bv. $0.13 i.p.v. de daadwerkelijke ~$144).

Dit is op 6 sep 2026 gerepareerd (zie de commit-geschiedenis rond
"KRITIEKE BUGFIX: dashboard/Telegram-positieweergave"), maar de
UURLIJKSE SNAPSHOTS die VOOR deze fix zijn opgeslagen (via de cron-
job die elk uur `hourly_snapshot.py` draait) bevatten dus foutieve,
te lage totaalwaarden -- zichtbaar als scherpe, onverklaarbare dalen
in de "Waardeverandering"-grafiek op het dashboard.

BESLISSING (op verzoek van de gebruiker): deze historische, foutieve
punten blijven BEWUST ongecorrigeerd staan in de database -- geen
opschoning/backfill uitgevoerd. Toekomstige snapshots (vanaf de
eerstvolgende volledige cron-uur na de fix) zijn wel correct.
""")
print("Notitie toegevoegd.")
