notitie = """

## DEFINITIEF gevonden en opgelost: dubbele msg.value in open_position() (4 sep 2026)

Na TWEE eerdere, foutieve hypotheses (verouderde balans-cache; gas-
allowance-reservering -- beide teruggedraaid na doelbewuste, live
tegenbewijzen) is de WERKELIJKE oorzaak van "Insufficient funds for
transfer" gevonden door de volledige open_position()-implementatie
regel voor regel door te lezen:

payable_value werd berekend als amount0_desired * decimal_correction
-- het VOLLEDIGE, net-gewrapte positiebedrag NOGMAALS, als msg.value
voor de mint-transactie zelf. Dit was een bewuste "dubbele
betaalroute"-constructie van 27 augustus (wrap+approve EN msg.value
tegelijk, met de redenering dat refundETH() het ongebruikte deel toch
teruggeeft) -- maar dat vereist wel dat je EERST genoeg NATIVE HBAR
hebt om het te VERSTUREN, ongeacht de latere refund. Na het wrappen
(stap 1) is dat bedrag niet meer native beschikbaar (alleen de
reserve nog), dus het versturen zelf mislukte al.

OPGELOST: payable_value stuurt nu een klein, symbolisch bedrag (1
HBAR, WHBAR_SYMBOLIC_MSG_VALUE_TINYBAR) plus de eigenlijke mint-fee,
i.p.v. het volledige positiebedrag nogmaals -- voldoende om aan
mint()'s "msg.value > 0 zodra een token WHBAR is"-eis te voldoen,
zonder het al-gewrapte bedrag te dupliceren. Op uitdrukkelijk verzoek:
dit symbolische bedrag mag uit de 50 HBAR-reserve komen (die is er
juist voor fees/gas) -- het principe dat de reserve NOOIT het
positiebedrag zelf financiert, blijft onveranderd.

Traject: drie live pogingen nodig (elke keer kapitaal veilig hersteld
via recover_whbar.py) plus twee zuiver-diagnostische, kapitaal-vrije
scripts (gas-wiskunde, mint-fee-check) om de EERSTE twee hypotheses
overtuigend uit te sluiten, vóórdat de daadwerkelijke oorzaak in de
code zelf werd gevonden. MIN_GAS_RESERVE_HBAR blijft op 50 (de
oorspronkelijke, nooit het echte probleem)."""

with open("/root/hbar_bot/PLAN.md", "a") as f:
    f.write(notitie)
print("Toegevoegd aan PLAN.md.")
