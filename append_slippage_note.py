notitie = """

## Slippage-marge verruimd voor de reflex-heropeningsflow (4 sep 2026)

Vervolg op de definitieve "dubbele msg.value"-fix: bij de daaropvolgende
test trad een NIEUWE, andersoortige fout op -- "Price slippage check"
(standaard Uniswap V3-bescherming). Root cause: onze eigen testnet-pool
heeft vrijwel geen organische activiteit (bevestigd eerder vandaag: 24u-
volume was slechts 2893 HBAR-equivalent, bijna uitsluitend van onszelf)
-- onze EIGEN, relatief grote balancerings-swaps duwen de prijs daardoor
meerdere procenten weg binnen een enkele herbalancerings-reeks, wat de
eerder berekende range (en de daarbij horende amountMin/amountMax-
grenzen) ongeldig maakt tegen de tijd dat de mint-transactie aan de
beurt is.

Dit is GEEN codefout maar een testnet-specifiek, dunne-liquiditeit-
artefact -- op mainnet zou dezelfde transactiegrootte een verwaarloosbare
prijsimpact hebben. Op uitdrukkelijk verzoek toch verruimd (15% -> 30%)
in de reflex-heropeningsflow (_execute_transition's LP_MODE-tak),
zodat testnet-tests hier niet steeds opnieuw op stuklopen.

Tussentijds ook gevonden en gecorrigeerd: het testscript zelf (definitive_
deployment_test.py) hergebruikte een verouderde fresh_price-waarde bij de
uiteindelijke mint-poging i.p.v. deze vlak ervoor opnieuw te verversen --
de PRODUCTIE-code deed dit al wel correct (26 aug 2026-patroon), dit was
dus specifiek een gat in het testscript zelf."""

with open("/root/hbar_bot/PLAN.md", "a") as f:
    f.write(notitie)
print("Toegevoegd aan PLAN.md.")
