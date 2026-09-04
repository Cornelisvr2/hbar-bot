with open("/root/hbar_bot/MAINNET_MIGRATIEPLAN.md", "r") as f:
    inhoud = f.read()

nieuw_deel = """

## Deel 8 — Aanvullingen na externe reflectie (4 sep 2026)

- **BEARISH_REFLEX mist een symmetrische trailing-stop.** BULLISH_REFLEX
  heeft een 5%-trailing-stop (winst-name bij een teruggang vanaf de
  piek); BEARISH_REFLEX heeft geen equivalent voor een snel herstel
  vanaf een bodem. Bij 100% USDC (op mainnet daadwerkelijk risk-off,
  i.t.t. 100% SAUCE op testnet) is dit een reeel gemis -- een snelle
  trendomkeer zou nu alleen via de tragere sentiment-route of de
  markt-bevestigde-terugkeer opgepikt worden. TOE TE VOEGEN vóór, of
  vroeg na, de mainnet-start.

- **USDC-depeg-check ontbreekt volledig.** Stablecoins zijn niet immuun
  voor volatiliteit (bv. SVB/USDC, 2023). Een harde, blokkerende
  controle (USDC/USD-koers via een betrouwbare bron, bij een
  significante afwijking direct pauzeren, ongeacht het HBAR-sentiment)
  hoort naast de bestaande TWAP-orakel-check thuis. TOE TE VOEGEN vóór
  de mainnet-start.

- **Trailing-stop-basis (verduidelijking, geen actiepunt).** De
  trailing-stop gebruikt de POOL-EIGEN prijsschaal (fresh_reflex_price),
  niet een expliciet USD-orakel. Bij HBAR/SAUCE was dit een ruwe
  benadering (SAUCE beweegt zelf ook); bij HBAR/USDC valt dit onderscheid
  grotendeels weg (USDC ≈ USD per ontwerp) -- de migratie zelf lost dit
  dus al grotendeels op, geen aparte bouwtaak nodig.

- **Nog NIET doorgevoerd, bewust uitgesteld tot na wat mainnet-ervaring**:
  een dynamische bovenmarge in de GBM-range bij aanhoudende bullishness
  (spiegelbeeld van de bestaande fat-tail-onder-marge), en het verkorten
  van de fee-onderprestatie-timer (4u -> 1-2u). Beide zijn legitieme
  ideeën, maar verdienen eerst empirische onderbouwing met echte
  mainnet-data, net als de bestaande, nooit-geijkte aannames elders in
  het systeem."""

with open("/root/hbar_bot/MAINNET_MIGRATIEPLAN.md", "w") as f:
    f.write(inhoud + nieuw_deel)
print("Toegevoegd aan MAINNET_MIGRATIEPLAN.md.")
