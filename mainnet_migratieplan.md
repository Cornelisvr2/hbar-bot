# Mainnet-migratieplan — HBAR/USDC Liquidity-Bot

*Opgesteld: 4 september 2026*
*Startkapitaal: ~$200 in HBAR*

## Uitgangspunt

Vandaag zijn twee **structurele, echte bugs** gevonden en definitief gerepareerd die ook op mainnet een probleem zouden zijn geweest (de `regime_at_creation`-crash bij het opslaan van een nieuwe positie, en een dubbele `msg.value` bij het openen ervan). Daarnaast zijn een aantal testnet-specifieke eigenaardigheden geïdentificeerd die op mainnet naar verwachting **vanzelf** verdwijnen (zie onder). Dit plan gaat uit van de daadwerkelijke, actuele configuratie-status — niet van aannames.

---

## Deel 1 — Wat al klaar staat

Bevestigd, rechtstreeks uit `config.py`:

| Item | Status |
|---|---|
| Mainnet V2-contractadressen (factory, swap_router, quoter_v2, position_manager) | ✅ Ingevuld, bevestigd via officiële SaucerSwap-docs (23 aug 2026) |
| Mainnet WHBAR/USDC-poolcontract | ✅ Bevestigd via GeckoTerminal (22 aug 2026): **$3,2M TVL, $2,7M 24u-volume** — een échte, liquide pool |
| USDC-tokenadres + decimalen | ✅ `0.0.456858`, 6 decimalen (Circle-standaard) |
| WhbarHelper (mainnet) | ✅ `0.0.5808826` |

Dit is een belangrijk gegeven voor het vertrouwen in deze overstap: de mainnet-pool heeft **duizenden keren meer liquiditeit** dan onze testnet-pool (die vrijwel uitsluitend door onszelf werd verhandeld). De prijsimpact-problemen van vandaag (waarbij onze eigen swaps de prijs meerdere procenten verplaatsten) zouden bij $200 op een pool van $3,2M **verwaarloosbaar** moeten zijn.

## Deel 2 — Nog open, vóór de overstap

1. ~~Fee-tier van de mainnet-pool bevestigen~~ **BEVESTIGD (4 sep 2026)**: de daadwerkelijke fee-tier is **1500 (0,15%)**, NIET de aanname van 3000 (0,30%) die voor testnet gold. De bot leest dit via de omgevingsvariabele `LP_FEE_TIER` (regime_orchestrator.py, regel 430) -- geen codewijziging nodig, alleen instellen in `.env`:
   ```
   LP_FEE_TIER=1500
   ```
2. **HEDERA_NETWORK staat op TWEE plekken** — `config.py` (hardgecodeerd, regel 19) én `.env` (regel 26). Beide moeten naar `mainnet`, anders ontstaat een mismatch tussen wat de code denkt en wat er daadwerkelijk gebeurt.
3. **Relay-account-uitsluiting herzien** — `0.0.7314364` (gebruikt om Hedera's JSON-RPC-relay uit te sluiten bij het berekenen van "totale stortingen") is testnet-specifiek; het mainnet-equivalent moet apart geverifieerd worden.
4. **GeckoTerminal-netwerk-ID** — vandaag ontdekt dat `HEDERA_NETWORK_ID = "hedera-hashgraph"` in `geckoterminal_client.py` altijd al **mainnet** bevraagde (GeckoTerminal indexeert geen testnet). Op mainnet is dit dus eindelijk correct en consistent met de rest van de bot — geen wijziging nodig, maar wel goed om te beseffen dat de eerder gerapporteerde "Live pool-APR"-cijfers de hele tijd al échte, bruikbare mainnet-data waren.
5. **Adressen dubbel verifiëren op HashScan** — de bestaande waarschuwing bovenaan `config.py` ("verifieer op HashScan vóór je omschakelt") blijft van kracht; een laatste, handmatige controle vóór de eerste transactie.

## Deel 3 — Wat waarschijnlijk vanzelf oplost

- **Prijs-slippage door eigen impact** (vandaag herhaaldelijk tegengekomen): bij $3,2M TVL is een positie van $200 verwaarloosbaar klein — de "Price slippage check"-problemen van vandaag zouden hier niet moeten optreden.
- **Fee-APR-basislijn**: de live, mainnet-APR die we vandaag zagen (28-43%) is voortaan **wél** representatief voor de daadwerkelijke pool waarin je handelt — geen aparte kalibratie nodig, maar wees je ervan bewust dat dit een pool-breed gemiddelde is, niet een garantie voor jouw specifieke, kleine positie.
- **Volatiliteit/fat-tail-kalibratie**: onze uurvolatiliteit komt van Binance (HBAR/USD, extern) — dit was nooit testnet-specifiek en blijft ongewijzigd bruikbaar.

## Deel 4 — Financieel plan voor de start ($200)

Gegeven de vaste `MIN_GAS_RESERVE_HBAR = 50` (nu ongeveer $4 bij de huidige koers) en de aanbeveling om **niet** meteen het volledige bedrag in te zetten:

| Fase | Bedrag | Doel |
|---|---|---|
| **Fase 0 — Kleinschalige mechaniek-test** | ~$20-30 | Wrap/approve/mint-cyclus **handmatig** verifiëren op mainnet, met een verwaarloosbaar bedrag. Bevestigt dat de vandaag-gerepareerde bugs ook op mainnet correct werken, zonder veel op het spel te zetten. |
| **Fase 1 — Volledige inzet** | Resterende ~$170-180 | Pas nadat Fase 0 zonder problemen verloopt, het volledige bedrag inzetten en de bot zijn normale cyclus laten oppakken. |

## Deel 5 — Stapsgewijs testplan (mechaniek, vóór de bot loslaten)

1. `HEDERA_NETWORK` op beide plekken (`config.py`, `.env`) naar `mainnet`
2. `verify_setup.py` draaien (bestaande, nog niet vandaag gebruikte verificatiescript) om de opgeloste adressen te controleren
3. Fee-tier van de mainnet-pool rechtstreeks bevragen en vergelijken met de aanname (3000)
4. **Handmatig, met het kleine testbedrag (~$20-30)**:
   - Eén simpele swap (HBAR → USDC en terug) — bevestigt basisconnectiviteit en swap-mechaniek
   - Eén positie openen (test of de vandaag-gerepareerde wrap/mint-keten werkt)
   - Eén positie sluiten — bevestigt de volledige levenscyclus
5. Pas na een schone, foutloze doorloop: het resterende kapitaal bijstorten en de bot **DRY_RUN=false** laten draaien met het volledige bedrag

## Deel 6 — Eerste dagen: nauwlettend volgen

Gezien dit echt geld is (in tegenstelling tot de hele testnet-fase):
- Houd Telegram-meldingen de eerste dagen actief in de gaten, met name reflex-overgangen en balanceringsklem-meldingen
- Het dashboard (na het HTTPS/Caddy-adres aan te passen voor mainnet, indien nodig) blijft het centrale overzicht
- Overweeg de reflex-drempels (1% terugval, 30 min zijwaarts) de eerste periode extra kritisch te volgen — deze zijn nooit empirisch geijkt op échte marktdata, alleen op aannames

## Deel 7 — Nog openstaande, grotere ontwerpvragen (niet blokkerend voor de start)

- **Whipsawing bij de reflex-modus** — de economische poort is verwijderd; nog geen empirisch bewijs of dit tot herhaaldelijk, kostbaar in-en-uit-springen leidt in een schokkerige markt. Aanbeveling: elke reflex-episode loggen (aanleiding, duur, contrafeitelijke vergelijking) om dit na verloop van tijd met échte mainnet-data te kunnen beoordelen.
- **Tranche-architectuur** voor overtollig kapitaal — nog niet gebouwd, mogelijk pas relevant bij een groter kapitaalbedrag dan de initiële $200.
- **Dashboard-forceerknoppen** — bewust uitgesteld tot authenticatie is toegevoegd.

---

## Samenvatting: volgorde van handelen

1. Fee-tier bevestigen
2. `HEDERA_NETWORK` op beide plekken omzetten
3. `verify_setup.py` draaien
4. Handmatige mechaniek-test met ~$20-30
5. Bij succes: resterende ~$170-180 bijstorten, bot op `DRY_RUN=false`
6. Eerste dagen nauwlettend volgen via Telegram + dashboard


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
  het systeem.