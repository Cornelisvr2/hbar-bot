notitie = """

## Systematische doorlichting: twee extra instanties van de dubbele-msg.value-bug (4 sep 2026)

Op verzoek, na de vraag "hoe sluiten we grote, sluimerende bugs uit
vóór mainnet" -- gericht gezocht naar ALLE payable_value/value_wei-
berekeningen in lp_manager.py, niet alleen de al-gerepareerde plek in
open_position(). Gevonden: EXACT hetzelfde patroon in twee andere
functies:

1. claim_and_compound() -- claimt fees via collect() en herinvesteert
   ze direct. payable_value stuurde het volledige, al-geclaimde bedrag
   NOGMAALS als native msg.value.
2. deploy_additional_capital() -- dit is de functie die
   _deploy_excess_capital_if_available() aanroept (de vandaag eerder
   toegevoegde "directe restkapitaal-bijstorting"-feature!). Dezelfde
   bug hier betekent dat deze feature, sinds de toevoeging vandaag,
   mogelijk STILZWIJGEND is blijven falen op exact dezelfde manier als
   open_position() deed, zonder dat dit als zodanig herkend werd
   (eerdere observaties werden toegeschreven aan de balanceringsklem).

OPGELOST: beide functies gebruiken nu hetzelfde, klein-symbolisch-
bedrag-patroon als de eerdere fix in open_position() -- geen volledige
bedragen meer dubbel verstuurd.

Geverifieerd: syntax. NOG NIET live getest (dit vereist een moment
waarop claim_and_compound() of deploy_additional_capital() daadwerkelijk
wordt aangeroepen, wat niet triviaal op afroep te forceren is zonder
een bestaande, open positie).

BREDERE LES: dit bevestigt het patroon-gebaseerde zoeken (dezelfde
soort berekening, andere functie) als waardevolle aanvulling op puur
toevallig-geraakte bugs. Aanbeveling voor een volgende sessie: eenzelfde
doorlichting voor het regime_at_creation-patroon (is dat inmiddels
overal weg? bevestigd: ja, alle 4 plekken eerder vandaag al gefixed) en
voor andere, structureel-herhaalde patronen in het bestand."""

with open("/root/hbar_bot/PLAN.md", "a") as f:
    f.write(notitie)
print("Toegevoegd aan PLAN.md.")
