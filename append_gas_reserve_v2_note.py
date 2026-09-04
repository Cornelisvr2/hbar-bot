notitie = """

## Gas-reserve definitief herzien: 50 -> 100 HBAR, met correcte onderbouwing (4 sep 2026)

Vervolg op eerder vandaag: de eerste "Insufficient funds"-fix
(reserve naar 100) werd teruggedraaid op basis van de -op dat moment
redelijke- aanname dat 50 HBAR intrinsiek genoeg zou moeten zijn, en
dat het probleem elders zat (een verouderde balans-cache). Die
cache-fix is WEL correct en blijft staan, maar loste het probleem
NIET op -- bij een tweede, doelbewuste test (definitive_deployment_
test.py) trad EXACT dezelfde fout weer op, ook met de cache-fix
actief.

ECHTE OORZAAK, nu empirisch bevestigd: dit is geen kwestie van "de
reserve inzetten als positie-kapitaal" (dat principe klopt en blijft
gehandhaafd -- de reserve wordt nooit gewrapt/ingezet). Het gaat om
wat het NETWERK vooraf blokkeert als garantie (gas_limit x
max_fee_per_gas) VOORDAT een transactie uuberhaupt wordt uitgevoerd,
ongeacht wat er daadwerkelijk in rekening wordt gebracht. Bij
open_position()'s gas_limit_override=1.200.000 bleek 50 HBAR deze
gereserveerde marge niet altijd te dekken.

OPGELOST: MIN_GAS_RESERVE_HBAR opnieuw naar 100 HBAR, nu met deze
correcte onderbouwing vastgelegd in de code zelf, zodat een volgende
sessie dit niet nogmaals per ongeluk terugdraait op basis van de
eerdere, onvolledige redenering.

Twee volledige, live pogingen (met kapitaal, telkens correct hersteld
via recover_whbar.py) waren nodig om dit definitief vast te stellen --
beide keren bleef het kapitaal aantoonbaar volledig veilig."""

with open("/root/hbar_bot/PLAN.md", "a") as f:
    f.write(notitie)
print("Toegevoegd aan PLAN.md.")
