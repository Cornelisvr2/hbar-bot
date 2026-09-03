# HBAR Trading Bot — Management samenvatting

*Stand van zaken: 22 augustus 2026*

## Doel

Een geautomatiseerde trading bot die USDC/HBAR verhandelt op SaucerSwap
(Hedera-netwerk), gestuurd door sentiment-analyse van Bitcoin- en
HBAR-specifiek nieuws. Draait naast de bestaande aandelen-tradingbots
(Touch & Turn Scalper, VIX Rider) op dezelfde Hostinger VPS.

## Aanpak in het kort

- **Tweelaags sentiment**: een snelle, regelgebaseerde laag (nieuws-votes,
  tijdsverval) gecombineerd met een LLM-laag (Claude) voor rijker
  contextbegrip — bijvoorbeeld het correct wegen van een partnership-
  aankondiging versus routine-nieuws. Het LLM wordt gedwongen ook een
  **tegenargument** tegen zijn eigen score te formuleren (waarom zou de
  markt juist niet zo reageren?), wat overmoedige inschattingen afremt.
- **Het LLM "leert" niet in de klassieke zin** — er is geen training of
  fine-tuning. Wat wel gebeurt: (1) een paar zorgvuldig gekozen
  historische voorbeelden worden per aanvraag meegegeven als ijkpunt
  (few-shot), en (2) een aparte offline **backtesting-pipeline** speelt
  historisch nieuws na tegen historische koersen om te meten of onze
  eigen drempelwaarden (wanneer een score "sterk genoeg" is om te
  handelen) daadwerkelijk voorspellende waarde hebben. Een ingebouwde
  check voorkomt hierbij lookahead bias (per ongeluk koersdata van ná
  het nieuwsbericht gebruiken, wat een vals positief beeld zou geven).
- **BTC-sentiment is leidend**, HBAR-specifiek nieuws werkt als versterker
  of kan als losstaande trigger dienen (bijvoorbeeld bij Hedera Council-
  nieuws dat BTC niet raakt).
- **Twee veiligheidslagen**: een paniek-circuit-breaker (vaste, simpele
  drempelwaarde als vangnet) bovenop de primaire strategie, plus een
  risicomanager (in aanbouw) voor harde grenzen zoals max. trades per dag.
- **Kapitaalinzet**: €2.000, met een positiebeheer-model geïnspireerd op
  de bestaande VIX Rider-strategie (entry-prijs, stop-loss, meebewegende
  trailing-stop om winst vast te zetten).
- **Infrastructuur**: Docker + PostgreSQL, automatisch herstartend bij
  een crash, met doorlopende Telegram-rapportage (trades, dagoverzicht,
  foutmeldingen, noodstop-meldingen).

## Status

**Klaar**: sentiment-verzameling (nieuws + marktdata), de beslislogica,
beide veiligheidslagen, swap-uitvoering op zowel SaucerSwap V1 als V2,
de volledige Telegram-rapportage, en de backtesting-pipeline (met
ingebouwde bescherming tegen lookahead bias).

**Nog te bouwen**: de risicomanager, de centrale regellus die alles
samenbrengt, en de database-koppeling voor historische rapportage.

**Vier resterende concrete risico's** (was vijf, backtesting is
afgevinkt) zijn geïdentificeerd die vóór gebruik met echt geld afgedekt
moeten zijn — o.a. het voorkomen van dubbele trades op hetzelfde
nieuwsbericht, een afkoelperiode na een trade, en het correct bijhouden
van hoeveel kapitaal waar vastzit. Zie `PLAN.md` voor het volledige
overzicht.

## Risico's

- **Marktrisico**: crypto blijft volatiel; sentiment-signalen kunnen
  fout zijn, ook met een LLM erbij.
- **Technisch risico**: niet alle guardrails staan er al — bewust nog
  niet live met echt geld tot de risicomanager en de vijf openstaande
  punten zijn afgerond.
- **DeFi-specifiek risico**: smart-contract-risico op SaucerSwap zelf;
  bij eventueel toekomstig gebruik van liquiditeitspools ook impermanent
  loss.
- **Nieuw, nog te onderzoeken**: SaucerSwap lanceerde in juni 2026 een
  orderboek-systeem (V3) naast de bestaande pools — nog niet
  geïntegreerd, wacht op aanvullende documentatie.

## Wat nog nodig is van buitenaf

- Mainnet-contractadressen voor SaucerSwap V2 (nu alleen testnet compleet)
- Bevestiging van de juiste fee-tier voor de HBAR/USDC-pool
- SaucerSwap's Orderbook API-documentatie (voor de V3-verkenning)
- Een historische nieuws-dataset (CryptoPanic-archief of handmatige
  export) om de backtesting-pipeline daadwerkelijk te vullen — de
  pipeline zelf staat, de data erin nog niet

## Databron-beslissing: Binance i.p.v. CoinGecko voor backtesting

Voor de historische koersen die de backtesting-pipeline gebruikt, is
gekozen voor Binance's gratis klines-API (minuut-precisie, geen
API-key nodig) in plaats van CoinGecko. Reden: CoinGecko's gratis tier
geeft voor data ouder dan ~90 dagen alleen dag-niveau, te grof om
precies te bepalen wat de koers was op het exacte moment van een
nieuwsbericht. Er wordt nog steeds op SaucerSwap gehandeld — Binance
dient alleen als preciezere prijs-referentie voor het terugtoetsen.
CoinGecko blijft de juiste bron voor de lopende (dag-niveau) beta-
berekening tussen HBAR en BTC.

## Aanbevolen vervolgstappen — gefaseerd traject

Backtesting en een testnet-proefperiode zijn geen alternatieven voor
elkaar, maar twee stappen na elkaar met een verschillend doel:

1. **Risicomanager en centrale regellus bouwen** — nodig voordat er
   sowieso iets ononderbroken kan draaien, met de vier resterende
   gaps als harde vereisten
2. **Fase 1 — Backtesting** (snel, een middag): historisch nieuws +
   Binance-koersen door de pipeline halen om te bewijzen dat het
   sentiment-signaal statistisch voorspellende waarde heeft
3. **Fase 2 — Een maand op testnet laten draaien** (langzaam,
   operationeel): bewijst dat het complete systeem betrouwbaar werkt
   onder echte marktomstandigheden — iets wat backtesting niet kan
   testen, en waar backtesting ook niet voor bedoeld is
4. **Fase 3 — Pas daarna mainnet**, startend met een klein deel van
   het kapitaal
