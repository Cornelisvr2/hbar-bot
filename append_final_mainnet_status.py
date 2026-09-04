notitie = """

## Eindstand mainnet-migratie, sessie 4 sep 2026

Kapitaal: ~2406 HBAR + ~23,17 USDC (~$209, vrijwel exact het startbedrag
van $210, verschil puur gaskosten van de vele test-transacties). Volledig
veilig, bevestigd via de mirror node.

Bot-service (hbar-bot) is BEWUST GESTOPT (docker compose stop) -- draait
NIET automatisch. HEDERA_NETWORK=mainnet, DRY_RUN=false, LP_FEE_TIER=1500
staan actief in .env/config.py.

Twee kritieke, systeembrede bugs gevonden en gerepareerd tijdens deze
mainnet-verificatiefase (zie eerdere secties hierboven voor volledige
details):
1. Token0/token1-canonieke-volgorde in get_live_pool_price()
2. Decimalen-mismatch in 10 aanroepen die deze functie gebruiken

Kleinschalige mechaniek-test: de EERSTE swap (HBAR->USDC, ~300 HBAR)
slaagde volledig en correct. De positie-openingstest liep tweemaal
tegen problemen aan:
- Eerste poging: token_id 76712, liquidity=0 (voor de decimalen-fix) --
  geen financiele schade, netjes gesloten.
- Tweede poging (na beide fixes): prijzen/bedragen nu volledig correct
  en realistisch (range 0,0736-0,0813 USD, gebruik van 265,62 HBAR +
  22,01 USDC) -- maar de mint zelf faalde op "Price slippage check"
  (dezelfde, bekende marge-kwestie als eerder vandaag op testnet,
  waarschijnlijk gewoon een te-krappe 5%-marge voor deze kleine test).
  Kleine hoeveelheid WHBAR (0,22) kwam vast te zitten, succesvol
  hersteld via recover_whbar_mainnet.py.

NOG TE DOEN, volgende sessie:
- Positie-openingstest herhalen met een ruimere slippage-marge (bv. 15-
  20%, zoals we eerder vandaag op testnet ook nodig hadden)
- Bij succes: pas dan de bot-service weer daadwerkelijk starten voor
  automatisch, doorlopend gebruik
- Het lege NFT-restant (token_id 76712, in token 0.0.4054027) kan
  genegeerd worden -- geen financiele waarde, puur cosmetisch
- Overweeg de twee, eerder vastgelegde aanvullingen (BEARISH_REFLEX-
  trailing-stop, USDC-depeg-check) alsnog te bouwen vóór de bot
  autonoom te laten draaien"""

with open("/root/hbar_bot/PLAN.md", "a") as f:
    f.write(notitie)
print("Toegevoegd aan PLAN.md.")
