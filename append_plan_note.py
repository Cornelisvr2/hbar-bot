notitie = """

## Twee-in-een fix: 'Insufficient funds for transfer' bij heropenen (4 sep 2026)

Live gevonden tijdens het handmatig sluiten+heropenen van positie 352
(met een verse, symmetrische GBM-range, zie de fat-tail-buffer-fix
hierboven): open_position() faalde met een ECHTE RPC-fout (niet de
bekende simulatie-gerelateerde INVALID_NFT_ID) -- "Insufficient funds
for transfer", HTTP 400 rechtstreeks van Hashio's node.

ROOT CAUSE, in twee lagen:
1. Eerste hypothese (te snel, TERUGGEDRAAID op verzoek): de vaste
   MIN_GAS_RESERVE_HBAR (50) leek te krap voor de cumulatieve
   gaskosten van een meerstaps-transactiereeks (swap+wrap+approve+
   mint). Op verzoek teruggedraaid: 50 HBAR is intrinsiek genoeg als
   reserve -- de bot MAG eronder komen voor gas, maar mag het nooit
   INZETTEN als positie-kapitaal.
2. WERKELIJKE oorzaak: de 5-seconden-cache op _get_swappable_hbar_
   balance() gaf een VEROUDERDE balans terug bij de definitieve
   open_position()-berekening, als die binnen 5 seconden na de
   balancerings-swap plaatsvond -- de cache wist dan nog niet dat DIE
   swap al gas had gekost, en overschatte daardoor hoeveel natieve
   HBAR er nog beschikbaar was.

OPGELOST: self._hbar_balance_cache = None expliciet vlak vóór de
definitieve, kritieke balans-meting in de LP_MODE-heropeningsflow
(_execute_transition) -- dwingt een ECHTE, verse RPC-aanroep af op
precies het moment waarop het er het meest toe doet, i.p.v. te
vertrouwen op een cache die de gaskosten van eerdere stappen in
dezelfde reeks nog niet had verwerkt.

Kapitaal was tijdens dit hele incident volledig veilig (bevestigd via
daily_status_report.py en de mirror node) -- eerst tijdelijk vast als
WHBAR (hersteld via het bestaande recover_whbar.py-script), daarna
volledig los in de wallet, wachtend op een succesvolle heropening.

Geverifieerd: syntax. NOG NIET live bevestigd met een daadwerkelijk
geslaagde heropening na deze specifieke fix (vereist de eerstvolgende
vangnet-poging, binnen de bestaande 30-minuten-cooldown)."""

with open("/root/hbar_bot/PLAN.md", "a") as f:
    f.write(notitie)
print("Toegevoegd aan PLAN.md.")
