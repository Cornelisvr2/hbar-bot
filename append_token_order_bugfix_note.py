notitie = """

## KRITIEKE, systeembrede bug gevonden tijdens mainnet-verificatie: token0/token1-volgorde (4 sep 2026)

Tijdens de DRY_RUN=true-verificatiefase (bewust ingebouwd vóór de
daadwerkelijke omschakeling) bleek get_live_pool_price() een compleet
verkeerde prijs terug te geven op mainnet: 129263.98 USDC voor 1 HBAR,
i.p.v. de correcte ~0.077.

ROOT CAUSE: Uniswap V3-achtige pools ordenen token0/token1 ALTIJD op
numeriek adres (kleinste eerst) -- de tick-afgeleide prijs is dus
ALTIJD "canoniek-token1 per canoniek-token0", ongeacht in welke
volgorde de aanroeper de parameters doorgeeft. Op testnet was WHBAR
toevallig altijd numeriek kleiner dan SAUCE (dus canoniek token0),
waardoor dit onderscheid de HELE dag nooit is opgevallen. Op mainnet
is USDC numeriek kleiner dan WHBAR -- PRECIES omgedraaid.

OPGELOST: get_live_pool_price() bepaalt nu zelf, via een numerieke
adresvergelijking, of de aanroeper's token0 overeenkomt met de pool's
canonieke token0. Zo niet: de prijs wordt geinverteerd EN de
decimaal-correctie in de andere richting toegepast.

Geverifieerd, empirisch, op mainnet: 0.077361 USD/HBAR -- exact
overeenkomend met de daadwerkelijke, actuele koers.

DOORLICHTING van de rest van het bestand: get_twap_tick() geeft een
RUWE tick terug (geen decimaal-conversie), gebruikt voor RELATIEVE
tick-vs-tick-vergelijking -- inherent veilig, ongeacht token-volgorde.
compute_amount0_for_amount1() en vergelijkbare functies nemen een
AL-GEGEVEN, correct georienteerde current_price als invoer -- veilig
zodra de BRON (get_live_pool_price, nu gerepareerd) klopt. De bug was
dus geisoleerd tot exact een functie.

BREDERE LES: dit soort "toevallig altijd waar op testnet, maar niet
fundamenteel gegarandeerd"-aannames zijn precies het soort sluimerende
bug waar de vandaag gevraagde systematische doorlichting naar zocht --
en dit is verreweg de belangrijkste vondst van die hele doorlichting."""

with open("/root/hbar_bot/PLAN.md", "a") as f:
    f.write(notitie)
print("Toegevoegd aan PLAN.md.")
