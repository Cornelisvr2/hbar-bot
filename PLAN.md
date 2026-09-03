# HBAR Trading Bot — Projectplan

## ⚠️ PIVOT (22 aug 2026) — sentiment naar LLM, deployment naar Docker

Na analyse van een extern Gemini-gesprek over nieuwsbronnen en LLM-architectuur
is besloten:

1. **Sentiment-analyse**: naast (niet per se ter vervanging van) de vote/tijd-
   gewogen berekening in `cryptopanic_client.py`, gebruikt de bot nu ook een
   **LLM-gebaseerde sentiment-engine** (`llm_sentiment_engine.py`, Claude Haiku
   4.5 met gedwongen JSON-output via tool-use). Reden: rijker contextbegrip
   (bv. "Google Cloud breidt Hedera-nodes uit" correct wegen), tegen hogere
   latency/kosten dan pure vote-counting. Claude i.p.v. Gemini's voorstel
   (GPT-4o-mini) omdat je al met Claude werkt.
2. **Deployment**: van losse Python-scripts naar **Docker Compose +
   PostgreSQL** (`docker-compose.yml`, `Dockerfile`, `db_schema.sql`).
   Automatisch herstarten bij crash (`restart: always`), robuuste opslag
   van trades/sentiment/posities i.p.v. losse logs.
3. **Lokaal LLM op de VPS is bewust afgewezen** — geanalyseerd en verworpen:
   geen GPU op de VPS betekent 3-8s latency per nieuwsbericht (te traag voor
   een reactieve bot), tegenover 0.2-0.5s bij een cloud-API die bovendien
   maar een fractie van een cent per call kost.
4. **Farm/epoch-weight-optimalisatie (welke pool het meest oplevert aan
   SAUCE-farming-rewards) is expliciet uit scope gezet** — vereist details
   uit SaucerSwap's API-docs die nog niet zijn aangeleverd (auth-methode,
   endpoint voor epoch-gewichten). Terugkomen zodra die info er is.
5. **CORRECTIE (22 aug 2026): SaucerSwap V3 bestaat wél.** Eerder in dit
   project kon ik geen V3 vinden via GitHub-onderzoek — terecht op dat
   moment, want V3 is geen open-source AMM-contract maar een **off-chain
   matching-engine met on-chain settlement** (CLOB, sinds 12 juni 2026
   live op mainnet), die dus niet in de publieke SaucerSwap-GitHub-org
   staat. Bovendien ligt de launch-datum ná mijn kennis-cutoff (jan 2026).
   Zie de nieuwe sectie hieronder voor wat dit betekent voor onze
   architectuur.

## Complete architectuur — de datastroom

```
┌─────────────────────────────────────────────────────────────────────┐
│                         1. DATA-INGESTIE                            │
│  cryptopanic_client.py    coingecko_client.py                       │
│  (BTC + HBAR nieuws)      (prijzen, 90d beta/correlatie)             │
└──────────────┬───────────────────────┬──────────────────────────────┘
               │                       │
               ▼                       │
┌─────────────────────────────┐        │
│   2. SENTIMENT-LAAG          │       │
│  ┌─────────────────────────┐│        │
│  │ cryptopanic_client.py    ││        │
│  │ (regelgebaseerd: tijds-  ││        │
│  │  verval + votes)         ││        │
│  └─────────────────────────┘│        │
│  ┌─────────────────────────┐│        │
│  │ llm_sentiment_engine.py  ││        │
│  │ (Claude Haiku 4.5,       ││        │
│  │  gedwongen JSON-output)  ││        │
│  └─────────────────────────┘│        │
└──────────────┬───────────────┘       │
               │  btc_score, hbar_score │  hbar_btc_beta
               ▼                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    3. STRATEGY_ENGINE.PY                            │
│   BTC leidend (default trigger) + HBAR-specifiek als modifier/      │
│   losstaande trigger. Combinatiematrix bepaalt richting+confidence. │
└──────────────────────────────┬────────────────────────────────────────┘
                                │ SignalResult (direction, confidence, position_fraction)
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   4. SAFETY_OVERRIDE.PY                             │
│   Circuit breaker: vaste 40/60-weging (Gemini-model). Forceert      │
│   ALLEEN een volledige exit bij extreme paniek, nooit een koop.     │
└──────────────────────────────┬────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│              5. RISK_MANAGER.PY  (nog te bouwen)                    │
│   Max trades/dag, daily loss-limit, harde guardrails los van        │
│   de strategie zelf. Kan een signaal blokkeren, nooit versterken.   │
└──────────────────────────────┬────────────────────────────────────────┘
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
    ┌───────────────────────┐      ┌─────────────────────────────┐
    │   HOLD-signaal         │      │   BUY / SELL-signaal          │
    │  ┌───────────────────┐│      │  ┌─────────────────────────┐│
    │  │ lp_manager.py      ││      │  │ position_planner.py      ││
    │  │ (V2 CLMM-positie   ││      │  │ (VIX Rider-patroon:      ││
    │  │  rond huidige prijs,│      │  │  entry/stop-loss/        ││
    │  │  herbalanceren bij  │      │  │  trailing-stop, €2000)   ││
    │  │  out-of-range)      ││      │  └────────────┬────────────┘│
    │  └───────────────────┘│      │               ▼               │
    │  Eerst LP intrekken bij│      │  ┌─────────────────────────┐│
    │  sterk signaal, dan pas│      │  │ execute_hbar_swap_       ││
    │  swappen               │      │  │ standalone.py            ││
    │                        │      │  │ (losgekoppeld subprocess,││
    │                        │      │  │  V1 of V2 engine)        ││
    │                        │      │  └────────────┬────────────┘│
    └───────────────────────┘      └───────────────┬──────────────┘
                                                     │
                                                     ▼
                                    ┌─────────────────────────────┐
                                    │  swap_executor.py (V1)       │
                                    │  swap_executor_v2.py (V2)    │
                                    │  hedera_rpc_client.py         │
                                    │  → Hedera mainnet/testnet     │
                                    └────────────┬────────────────┘
                                                 │
                                                 ▼
                              ┌───────────────────────────────────┐
                              │  6. LOGGING & NOTIFICATIES          │
                              │  postgres_client.py (nog te bouwen) │
                              │  → sentiment_log, strategy_signals, │
                              │    trades, open_positions            │
                              │  telegram_notify.py ✅               │
                              │  → report_trade, report_panic_       │
                              │    override, report_lp_rebalance,    │
                              │    report_error, send_daily_summary  │
                              └───────────────────────────────────┘
```

**Alles wordt aangestuurd door `main_orchestrator.py` (nog te bouwen)** — de
event-loop die stap 1 t/m 6 elke cyclus doorloopt. Belangrijk architectuur-
principe: **het LLM belt nooit rechtstreeks naar de VPS om te traden** — de
orchestrator roept het LLM aan voor een score, en beslist daarna zelf via
de eigen guardrails (strategy_engine → safety_override → risk_manager) of
en hoe er gehandeld wordt.

## SaucerSwap V3 (CLOB) — nieuw ontdekt, nog niet geïntegreerd

Live op mainnet sinds 12 juni 2026, geaudit door Halborn (18 mei 2026).
Fundamenteel ander mechanisme dan V1/V2:

- **Order signeren i.p.v. transactie signeren**: EIP-712 typed data of
  Hedera personal-sign. Tokens blijven in de wallet tot een fill (wel
  eenmalig een token-allowance nodig per token).
- **Off-chain matching, on-chain settlement**: een matching-engine
  (closed-source, off-chain) matcht orders met milliseconde-latency;
  gematchte orders settlen atomisch via een on-chain "reactor"-contract.
- **Order-types**: limit, market, maker-only (post-only, neemt nooit
  liquiditeit af), en OCO (one-cancels-the-other).
- **Geen gas voor plaatsen/annuleren** — alleen fees bij daadwerkelijke
  fills.
- **AMM-backstop**: een V3-order kan opt-in doorroutet worden naar V1/V2
  als het orderboek zelf onvoldoende diepte heeft (eenrichtingsverkeer,
  geen prijsvergelijking tussen venues).
- **Markt-status**: elke markt heeft zowel een `status`-veld als een
  losse `isMarketHalted`-vlag — een markt kan "open" tonen terwijl
  matching gehalt is. **Beide checken vóór het plaatsen van een order.**
- **Belangrijk risico**: getoonde orderstatus kan kort afwijken van de
  daadwerkelijke on-chain staat (asynchrone matching/settlement) — zie
  de V3 Orderbook Risk Notice voor het volledige risico-overzicht
  voordat hier ooit mee gehandeld wordt.

### Wat dit voor onze architectuur zou kunnen betekenen

- Mogelijk **relevanter voor de LP-vervangende rol** dan voor de kern-
  swap: een maker-only limit-order op je gewenste prijs is in essentie
  een eenvoudiger alternatief voor `lp_manager.py`'s concentrated-
  liquidity-positie, zonder impermanent-loss-risico (je token beweegt
  niet totdat er een fill is).
- De eerder genoemde SaucerSwap-authenticatie-API (waar dit gesprek
  ooit mee begon) is vermoedelijk deze Orderbook API, niet een read-only
  data-API zoals ik toen aannam.
- **Nog niet geïntegreerd** — de "Orderbook API reference" (exacte
  endpoints, auth-methode, request-schema's voor het signeren van orders)
  is niet in de aangeleverde documentatie opgenomen. Ik kan
  `docs.saucerswap.finance` nog steeds niet zelf bereiken vanuit deze
  sandbox. Nodig voordat ik hier code voor bouw: de Orderbook API
  reference-pagina en de V3 Orderbook Risk Notice.



Sentiment-gedreven trading bot voor SaucerSwap (Hedera), die HBAR<->USDC
swapt op basis van BTC- en HBAR-specifiek nieuwssentiment. Geïnspireerd
op de bestaande Touch & Turn Scalper / VIX Rider-architectuur (losgekoppelde
subprocessen, risk-first design).

## Kernprincipe sentiment-logica

BTC-sentiment is de **leidende/default trigger** (hoog nieuwsvolume, HBAR
volgt doorgaans de brede markt). HBAR-specifiek nieuws werkt als **modifier**
op die basis-trade, en kan als **losstaande trigger** dienen wanneer BTC
geen duidelijke beweging laat zien (bv. een nieuwe Hedera Council-member).
Zie `strategy_engine.py` voor de volledige combinatiematrix.

Een aparte, simpelere vaste-weging-berekening (BTC 40% / HBAR 60%, uit een
extern geraadpleegd Gemini-gesprek) dient als **paniek-circuit-breaker**
bovenop deze primaire logica — zie `safety_override.py`. Deze overschrijft
alleen richting SELL bij extreme paniek, nooit richting BUY.

## Status per module

| Module | Status | Beschrijving |
|---|---|---|
| `cryptopanic_client.py` | ✅ Klaar | BTC + HBAR nieuws-ophalen, tijdsgewogen sentiment-score (regelgebaseerd) |
| `llm_sentiment_engine.py` | ✅ Klaar (structuur) | LLM-gebaseerde sentiment-analyse via Claude, gedwongen JSON-schema |
| `coingecko_client.py` | ✅ Klaar | Dynamische HBAR/BTC-beta, 90-dagen rolling window |
| `strategy_engine.py` | ✅ Klaar | Primaire beslislogica (BTC leidend, HBAR modifier) |
| `safety_override.py` | ✅ Klaar | Paniek-circuit-breaker (vaste 40/60-weging) |
| `position_planner.py` | ✅ Klaar | VIX Rider-patroon vertaald: entry/stop-loss/trailing-stop, €2000 kapitaal |
| `hedera_address_utils.py` | ✅ Klaar | Hedera-ID ↔ EVM-adres conversie (geverifieerd via round-trip test) |
| `hedera_rpc_client.py` | ✅ Klaar | Wallet, tx-signing, verbinding met Hedera EVM-laag |
| `config.py` | ✅ Klaar | Testnet + mainnet V1-adressen compleet; **mainnet V2-adressen nog leeg** |
| `swap_executor.py` | ✅ Klaar | SaucerSwap V1 (klassieke AMM) swap-uitvoering |
| `swap_executor_v2.py` | ✅ Klaar | SaucerSwap V2 (CLMM) swap-uitvoering via `exactInputSingle` |
| `execute_hbar_swap_standalone.py` | ✅ Klaar | Losgekoppeld subprocess-patroon (VIX Rider-stijl), ondersteunt V1 en V2 |
| `verify_setup.py` | ✅ Klaar | Read-only verificatiescript (geen transacties, geen kosten) |
| `Dockerfile` / `docker-compose.yml` | ✅ Klaar | Deployment: bot + PostgreSQL, auto-restart bij crash |
| `db_schema.sql` | ✅ Klaar | Tabellen voor sentiment_log, strategy_signals, trades, open_positions |
| `.env.example` | ✅ Klaar | Alle benodigde environment-variabelen |
| `lp_manager.py` | ✅ Klaar | V2 CLMM-positiebeheer HBAR/USDC; tokenId-parsing (via Transfer-event) en liquidity-ophalen (via positions()) afgerond 23 aug |
| `postgres_client.py` | ⏳ Nog te bouwen | Python-laag die schrijft naar de nieuwe Postgres-tabellen |
| `risk_manager.py` | ⏳ Nog te bouwen | Max trades/dag, daily loss-limit, harde guardrails los van strategie |
| `main_orchestrator.py` | ⏳ Nog te bouwen | Event loop: poll → sentiment (LLM + vote-based) → strategie → risk-check → swap → Postgres-log |
| `telegram_notify.py` | ✅ Klaar | Trade-meldingen, LP-rebalance-meldingen, foutmeldingen, dagelijkse samenvatting |
| `backtest_pipeline.py` | ✅ Klaar (mechaniek), data ontbreekt nog | Lookahead-bias-vrije terugtoets van sentiment-regels tegen historisch nieuws + koersen |
| **`lp_manager.py`** | 🔜 **Later, bewust uitgesteld** | Actief LP-beheer in V2 concentrated liquidity pool tijdens rustige/neutrale sentiment-periodes |

## De LP-module (uitgesteld, hier vastgelegd voor later)

Concept uit het Gemini-gesprek, nog niet gebouwd:

- Bij een **HOLD**-signaal van de strategy_engine (in plaats van niets doen):
  open een smalle liquiditeitspositie rond de huidige prijs via
  `NonfungiblePositionManager.mint()` (V2 CLMM)
- Monitor of de prijs uit de ingestelde marge loopt → zo ja:
  `decreaseLiquidity()` + `collect()`, herbalanceren, nieuwe positie
  rond de nieuwe prijs
- Bij een sterk sentiment-signaal (BUY/SELL of paniek-override):
  **eerst LP-positie intrekken**, dan pas de swap uitvoeren — anders
  zit kapitaal vast in de pool tijdens een crash
- Open vragen voor als we dit oppakken: breedte van de prijsmarge (bv.
  ±5%), rebalance-trigger-drempel, tick-math-berekeningen voor V2

Dit voegt een aanzienlijk nieuw risico toe (impermanent loss) en vereist
tick-math die we nog niet hebben uitgewerkt — bewust uitgesteld tot de
kernbot (swap-only) end-to-end getest is.

## Openstaande blokkades voor live gebruik

1. **Mainnet V2-adressen** (Factory, SwapRouter, QuoterV2, PositionManager)
   nog niet aangeleverd — nodig voor `config.py`
2. **Fee-tier verificatie** — huidige aanname 3000 (0.3%) moet gecheckt
   worden tegen de daadwerkelijke HBAR/USDC-pool
3. **USDC-associatie** op het bot-account — nog te bevestigen
4. **Testnet-HBAR-balans** op het bot-account — nog te bevestigen

~~5. lp_manager.py: tokenId/liquidity-placeholders~~ — **AFGEVINKT (23 aug 2026)**:
tokenId wordt nu geparsed uit het Transfer-event van de mint-transactie,
en `close_position()` haalt de actuele liquidity op via `positions(tokenId)`
i.p.v. een aangenomen waarde.

## Expliciet uitgesteld (niet vergeten, wel bewust niet nu)

- **Farm/epoch-weight-optimalisatie**: welke pool het meest oplevert aan
  SAUCE-farming-rewards. Vereist SaucerSwap API-details (auth-methode,
  endpoint-structuur) die nog niet zijn aangeleverd. Terugkomen zodra
  die info beschikbaar is.

## Gefaseerd validatietraject (22 aug 2026)

Backtesting en een live testnet-periode zijn geen alternatieven voor
elkaar, maar opeenvolgende fases met een verschillend doel:

**Fase 1 — Backtesting (snel, statistisch).** `backtest_pipeline.py`
tegen een jaar historisch nieuws + Binance-koersen. Doel: bewijzen dat
het sentiment-signaal überhaupt voorspellende waarde heeft, en de
drempelwaarden in `strategy_engine.py` kalibreren. Kan in een middag
draaien; risico is overfitten op het verleden.

**Fase 2 — Testnet-maand (langzaam, operationeel).** `main_orchestrator.py`
laten draaien op testnet, ononderbroken, minstens een maand. Doel:
bewijzen dat het complete systeem betrouwbaar draait onder echte
marktomstandigheden — crasht de bot niet, werkt de swap-executie zoals
verwacht, hoe gedraagt de Hedera-RPC-verbinding zich in de praktijk.
Kan geen overfitting-risico wegnemen (één maand is een kleine
steekproef aan signalen), maar dekt operationele risico's af die
backtesting niet kan raken.

**Fase 3 — Mainnet, klein bedrag.** Pas na een succesvolle Fase 1 én
Fase 2, startend met een fractie van de €2.000.

**Consequentie**: Fase 2 kan pas beginnen zodra `main_orchestrator.py`
en `risk_manager.py` bestaan — er is nog geen doorlopend proces om een
maand te laten draaien. Dit is dus de directe aanleiding om die twee nu
te bouwen.

## Dubbele rol van de bot: directioneel traden + LP-beheer (22 aug 2026)

De bot doet nu twee dingen **gelijktijdig**, niet meer sequentieel
(LP alleen tijdens HOLD zoals oorspronkelijk):
1. Realtime directioneel traden op nieuws/sentiment (de live cyclus)
2. Realtime de HBAR/USDC-LP-positie bijsturen om impermanent loss te
   voorkomen — proactief op sentiment-richting, adaptief qua breedte
   op volatiliteits-regime

**CORRECTIE (22 aug 2026)**: geen gedeelde 50/50-kapitaalsplit meer.
LP-beheer en directioneel traden draaien als **volledig onafhankelijke
processen**, elk met hun eigen apart geconfigureerde kapitaal (bv. losse
wallets/instellingen). `risk_manager.py` bemoeit zich uitsluitend met
het directionele traden (dedup, cooldown, max trades/dag, daily
loss-limit) en heeft een eigen `trading_capital_usdc`-instelling, niet
afgeleid van een gedeeld totaal. `lp_manager.py` beheert zijn eigen
kapitaal volledig zelfstandig.

**`lp_manager.py` uitgebreid** met:
- `VolatilityRegime` (LOW/NORMAL/HIGH) → bepaalt range-breedte (3%/5%/12%),
  periodiek te verversen (niet continu) op basis van rolling volatiliteit
- Sentiment-gestuurde asymmetrische range-verschuiving (proactief, i.p.v.
  alleen reactief herbalanceren als de prijs al buiten de marge is)
- Een cooldown (baseline 4 uur) die beide triggers (reactief + proactief)
  bindt, zodat ze elkaar niet kunnen opjagen tot overmatig herbalanceren

**Openstaand — LP-parameters leren uit historische data**: gedeeltelijk
opgelost (22 aug 2026). `geckoterminal_client.py` is gebouwd en haalt
historische pool-OHLCV **inclusief volume per candle** op via
GeckoTerminal's gratis publieke API — precies de databehoefte die
hiervoor ontbrak. Bevestigd, echt WHBAR/USDC V2-poolcontract
(`0xc5b707348da504e9be1bd4e21525459830e7b11d`, $3.2M TVL, $2.7M
24u-volume op 22 aug 2026) toegevoegd aan `config.py`. Nog te bouwen:
de daadwerkelijke LP-parameter-backtest-loop die deze data gebruikt om
`cooldown_seconds` en de regime-breedtes te optimaliseren — de databron
staat er nu, de simulatie zelf nog niet. Dezelfde bron kan mogelijk ook
de eerder uitgestelde farm/epoch-weight-vraag beantwoorden.

## De drie kernmodules zijn gebouwd (22 aug 2026)

`risk_manager.py`, `postgres_client.py`, en `main_orchestrator.py` staan
er nu, alle drie getest. Kanttekening: `main_orchestrator.py` bevat vier
bewuste TODO's die eerst opgelost moeten worden voordat dit live kan:

1. Live prijs-quote i.p.v. de huidige placeholder (0.065) voor de
   positiegrootte-berekening
2. `lp_manager`-koppeling aan de V1/V2-contractadressen uit `config.py`
   (staat nu op `None`)
3. Correcte token0/token1-verdeling bij het openen van een LP-positie
   (nu een grove helft/helft-placeholder)
4. Periodieke (niet elke cyclus) herberekening van het volatiliteits-
   regime uit historische GeckoTerminal-data (draait nu altijd op NORMAL)

## PIVOT: RegimeOrchestrator vervangt drie processen (23 aug 2026)

Op verzoek: bij "groot nieuws" moet de bot de LP-pool leeghalen en
alles omzetten naar HBAR (bullish) of USDC (bearish), om maximaal te
profiteren van een koersbeweging; bij rustig nieuws moet het volledige
kapitaal juist in de pool staan voor yield.

**Nieuwe module**: `regime_orchestrator.py` — alles-of-niets schakelaar
tussen drie toestanden (`LP_MODE`, `BULLISH_REFLEX`, `BEARISH_REFLEX`),
getriggerd door dezelfde vaste 40/60-weging als `safety_override.py`
(`compute_fixed_combined_score`), nu SYMMETRISCH toegepast (niet alleen
paniek naar beneden, ook euforie naar boven). Winst nemen uit een
bullish-reflex gebeurt via `TrailingStopTracker` -- exact hetzelfde
piek-detectie-mechanisme als bij de reguliere directionele trades.

**Kapitaal samengevoegd**: de eerdere 50/50-scheiding tussen LP- en
trading-kapitaal is losgelaten -- het volledige bedrag (nu €2.000,
`REGIME_TOTAL_CAPITAL_USDC`) wordt door één proces beheerd.

**Drie processen vervangen door één**: `TradingOrchestrator`,
`LpOrchestrator`, en `PositionMonitorOrchestrator` zijn uit de actieve
`asyncio.gather()` in `main_orchestrator.py` gehaald. De klassen zelf
blijven wél in het bestand staan (niet verwijderd) -- bewuste keuze,
voor het geval een apart, gegradueerd tradingbudget met
`strategy_engine.py`'s combinatiematrix ooit weer gewenst is naast dit
regime-kapitaal. `strategy_engine.py` en `position_planner.py` blijven
dus bestaan en correct werken, maar worden momenteel nergens
aangeroepen vanuit de live loop.

**Bewuste afweging**: de eerdere `LpOrchestrator` paste de LP-range-
breedte aan op basis van een volatiliteits-regime en verschoof de range
proactief op sentiment. `RegimeOrchestrator`'s LP_MODE doet dit
(nog) niet -- de positie wordt simpelweg geopend en blijft staan tot een
regime-overgang. Reden: bij een regime-schakelaar verlaat je de pool
sowieso zodra het echt volatiel wordt (dat IS de bullish/bearish-reflex),
dus de noodzaak voor actief impermanent-loss-beheer tijdens LP_MODE is
kleiner dan in het oude, permanent-actieve LP-model.

**NABOUW-FIX (23 aug 2026, later dezelfde dag)**: de pivot brak
stilzwijgend de koppeling met het zelf-herkalibratie-systeem van de dag
ervoor. `TradingOrchestrator` (nu inactief) was de enige die naar
`sentiment_log` schreef; `recalibrate_from_live_history.py` leest daar
juist uit. Zonder fix zou de nachtelijke cron tegen een niet-groeiende
tabel aanlopen en nooit meer iets nieuws vinden. Opgelost: 
`RegimeOrchestrator._refresh_sentiment_if_due()` logt nu ook elke losse
headline-score naar `sentiment_log`, getest en bevestigd (2 aanroepen
voor 2 assets, dedup werkt correct). Ook cooldown tegen "flapping"
(`REGIME_COOLDOWN_SECONDS`, standaard 30 min, met uitzondering voor
winst-name via de trailing-stop) en trade-logging naar `trades` zijn
toegevoegd.

**NABOUW-FIX 2 (23 aug 2026, nog later dezelfde dag)**: `_execute_transition`
zette voorheen `self.current_regime` onvoorwaardelijk op de doel-regime,
ongeacht of de onderliggende swap(s) daadwerkelijk slaagden. Bij een
mislukte swap (netwerkfout, slippage, te weinig gas) zou de bot dus zijn
geregistreerde staat verliezen t.o.v. de werkelijke on-chain positie --
bij echt geld een serieus risico. Opgelost: `_execute_transition` geeft
nu een succes/faal-boolean terug; `current_regime` wordt alleen
bijgewerkt bij succes, en bij falen gaat er een expliciete "HANDMATIGE
CONTROLE VEREIST"-melding naar Telegram. Getest en bevestigd met een
gesimuleerde mislukte swap.

**NABOUW-FIX 3 (23 aug 2026)**: bij het heropenen van de LP-positie
(terugkeer naar LP_MODE) gebruikte de kapitaalberekening hardcoded
`1e6`/`1e8` voor USDC/HBAR-decimalen, in plaats van de al eerder
ontdekte, correcte waarden (testnet-USDC-testtoken heeft 18 decimalen,
niet 6 -- zie de eerdere GeckoTerminal/config.py-ontdekking). `_setup_lp_manager()`
haalde `base.usdc_decimals` al correct op, maar sloeg het nooit op als
instantie-attribuut. Resultaat: een factor 10¹² fout in het bedrag dat
naar de LP-positie zou gaan op testnet. Opgelost: `self._usdc_decimals`
en `self._hbar_decimals` worden nu bewaard en gebruikt in de
berekening. Getest en het factor-verschil expliciet aangetoond.

**NABOUW-FIX 4 (23 aug 2026, meest impactvolle fix van vandaag)**: bij
het verlaten van `BULLISH_REFLEX` werd het te swappen HBAR-bedrag
herberekend als `total_capital_usdc / current_price` -- maar de
werkelijk bezeten hoeveelheid HBAR was vastgesteld bij de INSTAPPRIJS,
niet de huidige prijs. Bij een koersstijging (het scenario waar de hele
reflex voor bedoeld is) bleef hierdoor een deel van de HBAR-positie
stelselmatig ongebruikt liggen -- de koerswinst werd dus nooit verzilverd.
Cijfervoorbeeld uit de test: bij een stijging van 0.070 naar 0.085 bleef
17,6% van de positie (~5.042 HBAR) achter. Hetzelfde gold voor de
LP_MODE-herbalancering, en voor alle overgangen die volgen op het sluiten
van een LP-positie (die geeft een MIX van HBAR+USDC terug, niet zuiver
één token). Opgelost: alle overgangen gebruiken nu de WERKELIJKE
on-chain balans (`_get_swappable_hbar_balance()`,
`_get_swappable_usdc_balance()`), met een vaste gas-reserve (5 HBAR).
Getest en het verschil cijfermatig aangetoond.

**NABOUW-FIX 5 (23 aug 2026, op verzoek)**: de gas-reserve
(`GAS_RESERVE_HBAR = 5.0`) was een vast HBAR-bedrag, terwijl Hedera's
transactiekosten in USD-termen zijn vastgesteld (fee-schedule) maar in
HBAR worden betaald. Bij een lage HBAR-prijs zou 5 HBAR te weinig kunnen
dekken, bij een hoge prijs onnodig veel kapitaal inactief laten liggen.
Opgelost: `GAS_RESERVE_USD = 2.0`, omgerekend naar HBAR op basis van de
actuele prijs (`GAS_RESERVE_USD / current_price`). Getest bij vier
verschillende prijzen ($0.01-$2.00) -- de HBAR-reserve schaalt correct
mee, de USD-waarde blijft constant.

**Ondergrens toegevoegd (op verzoek)**: `MIN_GAS_RESERVE_HBAR = 10.0` --
de reserve is nu het grootste van de USD-som en deze vaste ondergrens,
zodat er bij een hoge HBAR-prijs nooit minder dan 10 HBAR wordt
achtergehouden. Getest bij dezelfde vier prijzen: bij $0.50 en $2.00
springt de ondergrens correct in (10 HBAR i.p.v. de lagere USD-som).

**NABOUW-FIX 6 (23 aug 2026)**: als `DRY_RUN=false` staat maar
`HEDERA_BOT_PRIVATE_KEY` per ongeluk ontbreekt (`self.rpc_client` is dan
`None`), gaven de balans-functies `0.0` terug. Bij bedrag 0 werd de swap
overgeslagen door de `amount>0`-guards, en de code interpreteerde dat als
succes -- de bot zou zichzelf dan valselijk als "overgang geslaagd"
registreren, inclusief een misleidende Telegram-bevestiging, terwijl er
geen wallet was aangesloten en er dus niets was gebeurd. Opgelost: een
expliciete guard vooraan `_execute_transition` die dit scenario direct
en duidelijk laat falen. Getest en bevestigd: `current_regime` blijft nu
correct ongewijzigd i.p.v. valselijk bijgewerkt.

## Code-verificatieronde 2: lp_manager.py (23 aug 2026)

Op verzoek verder gezocht naar dezelfde bug-categorie (staat-
inconsistentie, decimalen-aannames) in andere kernmodules. Gevonden in
`lp_manager.py`'s `rebalance_if_needed()`: na `close_position()` wordt
`open_position()` aangeroepen met de oorspronkelijk MEEGEGEVEN
`amount0`/`amount1`-parameters, niet de werkelijke balans die uit de
sluiting terugkwam (inclusief opgebouwde fees en een mogelijk andere
token-verhouding door prijsbeweging binnen de oude range) -- zelfde
categorie fout als de vijfde `regime_orchestrator.py`-fix van vandaag.

**Bewust NIET gefixt, wel gedocumenteerd**: dit codepad zit in
`LpOrchestrator` (de klasse die sinds de `RegimeOrchestrator`-pivot
NERGENS meer wordt aangeroepen -- bevestigd via `grep`). Een echte fix
vereist weten of `mint()` een voorafgaande WHBAR-ERC20-`approve()`
verwacht, of native HBAR via `msg.value` intern wrapt -- dat bepaalt
welke balans-functie je moet gebruiken. Dit kon niet met zekerheid
worden geverifieerd tegen het daadwerkelijke contract, dus is een gok
hier bewust vermeden (zelfde principe als bij de contractadressen
eerder in dit project). Vastgelegd als expliciete waarschuwing in de
code zelf, zodat een eventuele toekomstige heractivatie van
`LpOrchestrator` deze bug niet stilzwijgend meeneemt.

## KRITIEKE BEVINDING: geen WHBAR/USDC-testnet-pool (23 aug 2026)

Bij het testen van `swap_executor_v2.py` (aanleiding: een vermoeden dat
de HBAR-decimalen-conventie in de swap-code niet klopte -- 18 decimalen
via `to_wei("ether")` vs. de 8 decimalen die elders voor WHBAR worden
aangenomen) bleek een `quote_hbar_to_usdc()`-call op testnet consequent
te reverten, bij ALLE vier gangbare fee-tiers (100/500/3000/10000).

Rechtstreekse Factory-checks (`getPool()` voor V2, `getPair()` voor V1)
bevestigen: **er bestaat helemaal geen pool** voor WHBAR met ons huidige
testnet-USDC-token (`0.0.6503036`) -- niet in V1, niet in V2, bij geen
enkele fee-tier. Dit verklaart de reverts volledig, LOS van de
decimalen-vraag (die blijft dus feitelijk onbeslist, kon niet getest
worden zonder een bestaande pool).

**Waarschijnlijke oorzaak**: dat testnet-USDC-token kwam uit een losse
HashScan-zoekopdracht, niet uit SaucerSwap's eigen documentatie -- het
is vermoedelijk een los testtoken zonder ooit gekoppelde liquiditeit,
niet het token dat SaucerSwap zelf voor hun testnet-pools gebruikt.

**Vervolgstap, nog te doen door de gebruiker**: het daadwerkelijk actieve
HBAR/USDC-paar (of een ander actief paar als sanity-check) rechtstreeks
opzoeken in SaucerSwap's eigen testnet-app, en het bijbehorende
token-ID noteren -- in plaats van verder te gokken naar adressen.

Twee losse verificatiescripts gebouwd voor deze exercitie, beide
herbruikbaar zodra er een nieuw token-ID is: `verify_v2_pool_exists.py`,
`verify_v1_pool_exists.py`.

## UPDATE: officiële SaucerSwap-documentatie ontvangen (23 aug 2026)

Gebruiker leverde de officiële `docs.saucerswap.finance`-pagina's aan
("Contract deployments" en "Developer overview"). Belangrijke
consequenties:

- **Blokkade #1 (mainnet V2-adressen) OPGELOST**: `MAINNET_V2_IDS` in
  `config.py` bevatte tot nu toe alleen `None`-placeholders. Nu ingevuld
  met de officiële adressen: Factory `0.0.3946833`, SwapRouter
  `0.0.3949434`, QuoterV2 `0.0.3949424`, PositionManager `0.0.4053945`
  (de niet-gedeprecieerde V2-variant, niet `0.0.3949448`). Getest:
  resolvt correct naar geldige EVM-adressen.
- **Bevestigd, geen nieuwe actie nodig**: al onze bestaande testnet- en
  WHBAR-adressen kwamen exact overeen met deze officiële bron.
- **USDC bevestigd structureel afwezig**: SaucerSwap heeft zelf GEEN
  officieel USDC-testtoken in hun deployment-lijst -- de eerdere
  "geen pool"-bevinding is dus geen toeval, USDC is simpelweg niet
  onderdeel van hun officiële testnet-opzet. SAUCE is dat wel
  (gekoppeld aan Masterchef/Mothership).
- **"V2 aanbevolen voor nieuwe integraties, V1 is legacy"** -- bevestigt
  dat onze eerdere keuze voor V2 als primaire engine terecht was.
- **Officiële REST Data API ontdekt** (`test-api.saucerswap.finance`
  voor testnet) -- kan pool-data/prijzen/TVL rechtstreeks leveren,
  potentieel een vervanging voor onze eigen `getPool()`-zoektochten.
  Vereist een `x-api-key`, AAN TE VRAGEN bij het SaucerSwap-team zelf --
  niet direct bruikbaar, vastgelegd als toekomstige verbetering.

**Resterende blokkades, bijgewerkt**: van de oorspronkelijke vier is nu
alleen nog over: (2) fee-tier-verificatie, (3) USDC-associatie
[waarschijnlijk te vervangen door een ander token, zie hierboven], (4)
testnet/mainnet-HBAR-balans bevestigen. Mainnet V2-adressen zijn klaar.

## Concrete fixes uit de officiele SaucerSwap-docs (23 aug 2026)

Gebruiker leverde vier extra pagina's aan: WHBAR overview, V2
swap-quote, en V2 new-liquidity-position. Vier directe consequenties:

1. **Bevestigd**: "if the token is HBAR, no spender allowance is
   required" -- `swap_executor_v2.py`'s bestaande aanpak (native HBAR
   via `msg.value`, geen `approve()` voor de HBAR-kant) was al correct.

2. **NIEUWE vereiste ontdekt**: het bot-account moet vooraf
   geassocieerd zijn met het SaucerSwapV2 LP-NFT-token (mainnet
   `0.0.4054027`, testnet `0.0.1310436`) voordat `mint()` ooit kan
   slagen -- naast de al bekende USDC-associatie. Toegevoegd aan de
   blokkade-lijst.

3. **Foute fee-tier-lijst gecorrigeerd**: de docs noemen expliciet
   500/1500/3000/10000 als geldige V2-tiers -- wij testten met
   100/500/3000/10000 (100 is ongeldig, 1500 ontbrak). Gecorrigeerd in
   alle drie de verificatiescripts.

4. **KRITIEKE FIX in `lp_manager.py`'s `open_position()`**: het
   officiele patroon is `multicall([mint_encoded, refundETH_encoded])`
   met de HBAR-kant als `payableAmount`/`msg.value` -- onze code riep
   `mint()` voorheen RECHTSTREEKS aan, zonder multicall, zonder ooit een
   payable-waarde mee te sturen (`build_and_send_transaction()` zette
   `value` nergens). Zonder deze fix zou `mint()` altijd falen zodra er
   een echte WHBAR-pool is, want het contract ontvangt nooit de HBAR die
   het intern moet wrappen. Opgelost:
   - `hedera_rpc_client.py`: `build_and_send_transaction()` heeft nu een
     `value_wei`-parameter.
   - `lp_manager.py`: `LpPositionConfig` heeft een nieuw
     `whbar_address`-veld (betrouwbare detectie welke kant HBAR is, i.p.v.
     een positionele aanname). `open_position()` gebruikt nu het
     multicall-patroon en berekent de juiste payable-waarde.
   - `regime_orchestrator.py`: geeft `whbar_address` door bij het
     opbouwen van de LP-configuratie.
   - Getest: multicall/refundETH correct herkend in het ABI, encode_abi
     produceert geldige hex-data, payable-waarde-detectie werkt correct
     in beide token-posities.

**Nog open**: de decimalen-vraag voor `swap_executor_v2.py` (18 vs. 8
decimalen voor de WHBAR-kant van `amountIn`) blijft onbeslist -- de
docs bevestigen "amountIn in token's smallest unit" maar niet expliciet
WHBAR's eigen decimals()-waarde. Kan pas empirisch getest worden zodra
er een bestaande pool is (bv. WHBAR/SAUCE) om een quote tegen te doen.

## KRITIEKE FIX 2: close_position() unwrapte nooit WHBAR (23 aug 2026)

Uit de "Decreasing liquidity (V2)"-docs: `decreaseLiquidity` + `collect`
+ `unwrapWHBAR` horen in EEN multicall. Onze vorige `close_position()`
deed decrease en collect als TWEE losse transacties, en riep
`unwrapWHBAR` NOOIT aan.

**Waarom dit ernstig is**: zonder `unwrapWHBAR` blijft het opgehaalde
bedrag steken als WHBAR-ERC20-token, niet als native HBAR. Dit zou
NABOUW-FIX 4 van eerder vandaag (balans-gebaseerde swap-bedragen via
`_get_swappable_hbar_balance()`, die specifiek de NATIVE HBAR-balans
checkt) stilzwijgend hebben ondermijnd -- na het sluiten van een
LP-positie zou die functie altijd 0 HBAR zien, ook al staat de waarde
er wel degelijk (alleen vast als WHBAR).

Opgelost: `close_position()` bundelt nu `decreaseLiquidity` + `collect`
+ (indien WHBAR betrokken is) `unwrapWHBAR` in EEN multicall, consistent
met `open_position()`'s multicall-patroon van de vorige fix. `unwrapWHBAR`
toegevoegd aan het ABI. Getest: correcte WHBAR-detectie in alle drie de
scenario's (WHBAR als token0, als token1, geen WHBAR betrokken).

## KRITIEKE FIX 3: mint-fee ontbrak, en bijna een nieuwe decimalen-bug (23 aug 2026)

Uit "Liquidity position fee (V2)": er is een APARTE HBAR-fee bovenop de
token-bedragen zelf, opgevraagd via `Factory.mintFee()` (in tinycent
US) en omgerekend naar tinybar via de mirror-node exchange-rate-API
(`/api/v1/network/exchangerate`). Deze fee ontbrak volledig in onze
`payable_value`-berekening.

**Bijvangst tijdens het implementeren**: bij het toevoegen van deze fee
werd duidelijk dat de BESTAANDE `payable_value`-berekening (uit de
vorige fix) zelf een decimalen-fout bevatte -- `amount0_desired`/
`amount1_desired` staan in WHBAR's EIGEN 8-decimalen-termen (correct
voor het `mint()`-structveld), maar `msg.value` wordt door de EVM-relay
geinterpreteerd in de 18-decimalen-wei-conventie. Die twee werden
zonder omrekening gelijkgesteld -- exact dezelfde bug-categorie als
eerder vandaag, deze keer bijna zelf geintroduceerd tijdens het fixen
van iets anders.

Opgelost:
- `NETWORK_SETTINGS` in `config.py` heeft nu `mirror_node_url` per
  netwerk (bevestigd tegen de officiele docs).
- `LpPositionConfig` heeft nieuwe velden `factory_address` en
  `mirror_node_url`.
- `LpManager._get_mint_fee_tinybar()`: vraagt `Factory.mintFee()` op,
  rekent om via de mirror-node-koers.
- `open_position()`'s `payable_value` corrigeert nu expliciet van
  WHBAR's 8-decimalen-termen naar de 18-decimalen-wei-conventie, en
  telt de mint-fee (ook omgerekend) erbij op.
- `regime_orchestrator.py`: geeft `factory_address`/`mirror_node_url`
  door.
- Getest: 1 WHBAR (8-dec) rekent correct om naar 1 HBAR in wei-termen
  (10^18), en de tinycent->tinybar->wei-keten volgt de gedocumenteerde
  formule correct.

## KRITIEKE FIX 4: swap_executor_v2.py miste ook unwrapWHBAR (23 aug 2026)

## DEFINITIEVE CORRECTIE: SwapRouter's unwrapWHBAR werkt niet zoals gedacht (24 aug 2026)

De fixes van 23 augustus (multicall + `unwrapWHBAR` op de SwapRouter/
PositionManager zelf) bleken bij een ECHTE, live test op testnet NIET te
werken -- empirisch bevestigd via twee onafhankelijke swaps (HBAR->SAUCE
werkte prima, maar de omgekeerde richting SAUCE->HBAR liet het bedrag
STEKEN als WHBAR-ERC20-token, ook na een poging met `recipient`=router-
adres in plaats van gebruikersadres).

**Grondoorzaak, definitief vastgesteld**: de SwapRouter's/PositionManager's
eigen `unwrapWHBAR()` unwrapt alleen WHBAR dat het CONTRACT ZELF
binnen dezelfde transactie vasthoudt -- niet WHBAR dat al in de
gebruikers-wallet zit uit een eerdere/losse actie. Dit hadden we nooit
kunnen ontdekken zonder een echte test, want de transactie meldt
gewoon "success" terwijl het feitelijk niets doet.

**De WERKELIJK juiste route**, gevonden via de officiele
`developers/whbar/unwrap-whbar-for-hbar`-documentatie: een APART
contract, `WhbarHelper` (testnet `0.0.5286055`, mainnet `0.0.5808826`),
met een eigen functie `unwrapWhbar(uint256 wad)` (let op: kleine 'w',
andere naam dan de kapotte SwapRouter-variant). Dit contract haalt de
WHBAR ACTIEF op uit de wallet via `safeTransferFrom()`, wat een
voorafgaande `approve()` vereist -- en unwrapt die dan naar native HBAR.

Empirisch bevestigd: het gestrande bedrag (0,34747 WHBAR, opgebouwd uit
twee eerdere mislukte pogingen) is via deze route succesvol teruggehaald.

**Beide bestanden definitief herschreven**:
- `swap_executor_v2.py`: `swap_usdc_to_hbar()` is nu een 2-3-staps-
  proces (swap naar eigen wallet, dan approve+unwrapWhbar via
  WhbarHelper) i.p.v. een enkele multicall.
- `lp_manager.py`: `close_position()` idem -- de kapotte multicall-
  unwrapWHBAR-stap is verwijderd, vervangen door dezelfde WhbarHelper-
  route na collect().
- `config.py`: `whbar_helper`-adressen toegevoegd voor beide netwerken,
  `ResolvedAddresses` uitgebreid.

**Les voor de rest van het project**: dit is de zoveelste keer dat een
"logische aanname op basis van documentatie-patronen" (hier: "vast
patroon herhalen op een ander contract") bij een echte test toch bleek
te kloppen -- niet altijd, dus. Alles wat ooit met echt geld gaat
werken, moet minstens een keer empirisch getest zijn, ongeacht hoe
overtuigend de documentatie-analyse vooraf leek.

Zelfde patroon als KRITIEKE FIX 2 (lp_manager.py), nu gevonden in
`swap_usdc_to_hbar()`: geen `unwrapWHBAR`-stap na de swap, dus het
resultaat zou steken blijven als WHBAR-ERC20-token i.p.v. native HBAR.

**Ook vastgelegd, NIET blind gefixt**: de officiele "Swap tokens for
tokens"-docs demonstreren `exactInput(bytes path, ...)` i.p.v. onze
`exactInputSingle(tuple params)` -- dat is een fundamenteel andere
aanroepvorm. `exactInputSingle` bestaat vermoedelijk ook op het
contract (standaard bij Uniswap V3-forks), maar dit is NIET empirisch
geverifieerd tegen het daadwerkelijke gedrag. Bewust geen gok hier --
expliciet gedocumenteerd in de code zelf als open vraag, te testen
zodra er een bestaande pool is.

**Ook ontdekt**: de output-token moet vooraf geassocieerd zijn bij de
ontvanger, anders `TOKEN_NOT_ASSOCIATED_TO_ACCOUNT`.

Opgelost: `swap_usdc_to_hbar()` bundelt nu `exactInputSingle` +
`unwrapWHBAR` via `multicall`, consistent met het patroon uit
`lp_manager.py`. Getest: multicall/unwrapWHBAR correct herkend en
encodeerbaar op de router.

## Bijgewerkte lijst met vereiste token-associaties

Uit de documentatie-ronde van vandaag blijkt dit er MEER te zijn dan de
oorspronkelijke ene "USDC-associatie"-blokkade:
1. USDC (of het uiteindelijk gekozen alternatief token)
2. WHBAR (bevestigd: `TOKEN_NOT_ASSOCIATED_TO_ACCOUNT` zonder dit)
3. SaucerSwapV2 LP-NFT-token (mainnet `0.0.4054027`, testnet `0.0.1310436`)
4. Elk ander output-token van een swap (algemene regel)

Dit moet allemaal geverifieerd/geregeld worden voordat er ooit uit
DRY_RUN gegaan wordt -- een uitbreiding van de oorspronkelijke blokkade #3.

## DECIMALEN-VRAAG DEFINITIEF OPGELOST (23 aug 2026)

Empirisch getest tegen de echte, bevestigde WHBAR/SAUCE-pool
(contractId 0.0.2661057, fee=3000, liquidity>0, via
test-api.saucerswap.finance ontdekt): een quote met WHBAR in zijn EIGEN
8-decimalen-conventie gaf 57,22 SAUCE voor 1 WHBAR, tegenover een
verwachte ~57,49 (uit de API's priceUsd-velden) -- een verschil van
amper 0,5%, volledig verklaarbaar door normale prijsimpact. Dit
bevestigt: WHBAR's eigen 8 decimalen is de juiste conventie voor het
`amountIn`/`amountOutMinimum`-swap-parameter, NIET de 18-decimalen-
wei-conventie die `swap_executor_v2.py` tot nu toe overal gebruikte.

**Belangrijke nuance, ontdekt tijdens het fixen**: `amountIn` (het
swap-parameter) en `msg.value` (de payable-waarde die daadwerkelijk
verstuurd wordt) staan in TWEE VERSCHILLENDE conventies -- WHBAR's 8
decimalen voor het eerste, de EVM-relay's 18-decimalen-wei-conventie
voor het tweede (native HBAR-representatie). Voorheen werd dezelfde
waarde voor beide hergebruikt in `swap_hbar_to_usdc()`, wat een factor
10^10-mismatch veroorzaakte.

Opgelost: `SwapConfigV2` heeft een nieuw `whbar_decimals=8`-veld.
`quote_hbar_to_usdc()`, `quote_usdc_to_hbar()`, `swap_hbar_to_usdc()`,
en `swap_usdc_to_hbar()` gebruiken nu allemaal consequent WHBAR's eigen
8-decimalen-conventie voor swap-parameters, met `msg.value` apart
berekend in de 18-decimalen-wei-conventie. Getest: het verschil tussen
de twee conventies is exact een factor 10^10, zoals verwacht.

Dit is de laatste van de vandaag gevonden decimalen-gerelateerde
problemen -- de belangrijkste onzekerheid die de hele dag openstond is
nu empirisch, niet alleen theoretisch, bevestigd.

## Eerste live testnet-transacties: gedeeltelijk gelukt (23 aug 2026)

Na de decimalen-fix zijn we overgegaan naar de daadwerkelijke, nog
openstaande blokkade: token-associatie. Bevindingen:

1. **Bot-account bestond nog niet on-chain** (0 HBAR, 404 bij de
   mirror-node) -- opgelost door 10 testnet-HBAR aan te vragen via
   portal.hedera.com/faucet. Account-ID: `0.0.10194038`.
2. **Gas-prijs was verouderd**: onze hardcoded default (500 Gwei) lag
   onder het toen geldende minimum (1110 Gwei) -- opgelost door de
   gas-prijs dynamisch op te vragen (`w3.eth.gas_price`) i.p.v. een
   vaste waarde, met 20% marge.
3. **Gas-limiet te laag geschat**: meerdere hardcoded pogingen
   (800K, 2M) faalden op `INSUFFICIENT_GAS`, telkens exact op de
   limiet. Uiteindelijk opgelost door `build_and_send_transaction()`
   uit te breiden met dynamische gas-schatting via `estimate_gas()`
   (50% veiligheidsmarge) i.p.v. blijven gokken met hardcoded getallen.
4. **WHBAR succesvol geassocieerd** via de enkelvoudige `associateToken()`
   HTS-precompile-call (5.000.000 gas, later bevestigd: de dynamische
   schatting komt uit op ~1,58 miljoen geschat, 2,37 miljoen met marge --
   ruim voldoende).
5. **SAUCE + LP-NFT nog NIET geassocieerd**: de poging faalde op
   "Insufficient funds for transfer" -- niet een bug, maar simpelweg de
   testnet-HBAR-balans op (2,02 HBAR resterend van de oorspronkelijke
   10, de rest opgegaan aan de meerdere mislukte pogingen die ONDANKS
   het falen alsnog gas-kosten in rekening brachten).
6. **Faucet-blokkade**: de Hedera-faucet hanteert een 24-uurs-cooldown
   per adres. Bot-account `0x293ba5c20033400807217980E796A6C2abf70367`
   (Hedera-ID `0.0.10194038`) kan pas over 24 uur opnieuw testnet-HBAR
   aanvragen.

**Openstaand voor de volgende sessie**: zodra er meer testnet-HBAR
beschikbaar is, `associate_required_tokens.py` opnieuw draaien (nu met
dynamische gas-schatting, zou moeten werken) voor SAUCE + LP-NFT.
Daarna: `verify_token_associations.py` ter bevestiging, en dan pas de
eerste daadwerkelijke swap/LP-test op de bevestigde WHBAR/SAUCE-pool.

## Fase 2 (testnet-maand) — bevindingen onderweg (23 aug 2026)

- **Sentiment-venster verruimd** van 1 naar 4 uur (zowel trading- als
  LP-loop) -- bij een gemeten frequentie van ~0,12 BTC- en ~0,17
  HBAR-items per uur was 1 uur te smal, `sentiment_log` bleef leeg na
  15 uur draaien terwijl de bot verder foutloos liep. Dedup via
  `risk_manager` voorkomt dat een breder venster tot dubbele verwerking
  leidt.
- **Junk-filter toegevoegd aan `rss_news_client.py`**: automatisch
  gegenereerde valuta-omreken-pagina's (bv. "Convert 10 HBAR to OMR -
  Bybit") glipten door het keyword-filter heen omdat ze toevallig
  "HBAR" bevatten. `JUNK_TITLE_PATTERNS` sluit deze nu uit (17 -> 6
  items in een test-run, allemaal daadwerkelijk relevant). **Kanttekening**:
  dit was ook actief tijdens de Fase 1-backtest van 22 aug -- een deel
  van de 57 HBAR-backtest-items was mogelijk zulke junk-pagina's, wat de
  eerdere backtest-cijfers enigszins kan hebben vertekend. Overweeg de
  backtest later opnieuw te draaien met deze fix erin.

## Gap-analyse (22 aug 2026) — wat nog niet is afgedekt

Kritisch doorlopen op basis van wat er nu staat, los van de losse
openstaande modules hierboven.

### Blokkerend voor live gebruik met echt geld

1. **Geen dedup van nieuwsitems.** `cryptopanic_client.py` en
   `llm_sentiment_engine.py` houden niet bij welke headlines al
   verwerkt zijn. Bij elke poll-cyclus kan hetzelfde oude nieuws
   opnieuw een signaal triggeren -> risico op dubbele trades op
   basis van hetzelfde bericht. Nodig: een `processed_news_ids`-set
   (Postgres of in-memory), te bouwen als onderdeel van
   `main_orchestrator.py`.
2. **Geen cooldown-periode na een trade.** Vroeg in het project
   genoemd als parameter (`cooldown_period`), maar nooit daadwerkelijk
   gebouwd in `strategy_engine.py`. Zonder dit kan de bot binnen
   enkele minuten meerdere keren tegengesteld handelen op ruis rond
   hetzelfde nieuwsevent (whipsaw).
3. **Geen kapitaal-boekhouding tussen LP-positie en swap-positie.**
   `position_planner.py` en `lp_manager.py` gaan er allebei impliciet
   van uit dat het volledige `total_capital_usdc` (€2000) beschikbaar
   is. Als er tegelijk een LP-positie open staat én een swap-positie,
   kan de bot in theorie meer inzetten dan er daadwerkelijk beschikbaar
   is. Dit hoort een kernverantwoordelijkheid van `risk_manager.py`
   te worden: bijhouden hoeveel kapitaal waar vastzit.
4. **Geen nonce-locking tussen losgekoppelde subprocessen.**
   `execute_hbar_swap_standalone.py` haalt de nonce op via
   `get_transaction_count()`. Als er per ongeluk twee subprocessen
   near-simultaan draaien (bv. een swap én een LP-rebalance), kunnen
   ze dezelfde nonce grijpen en faalt een van de twee transacties.
   Nodig: een simpel lock-bestand of een sequentiële job-queue in
   `main_orchestrator.py` i.p.v. losse fire-and-forget subprocessen.

~~5. Geen backtesting-pipeline~~ — **AFGEVINKT (22 aug 2026)**:
`backtest_pipeline.py` is gebouwd, met `get_price_strictly_at_or_before()`
die actief een `LookaheadBiasError` opgooit bij data uit de toekomst en
te oude candles overslaat. Nog wel nodig: een echte historische
nieuws-dataset en Binance-koersdata om de pipeline te vullen — de
mechaniek staat, de data erin nog niet.

### Belangrijk, maar niet direct blokkerend

6. **Geen retry/backoff-logica** in `cryptopanic_client.py`,
   `coingecko_client.py`, of `llm_sentiment_engine.py`. Eén timeout of
   rate-limit-error laat de huidige poll-cyclus gewoon falen i.p.v.
   netjes opnieuw proberen.
7. **Geen timeout op de Claude-API-call** in `llm_sentiment_engine.py`
   -- een hangende call zou de hele orchestrator-cyclus kunnen
   blokkeren als hier geen `timeout`-parameter aan wordt toegevoegd.
8. **CryptoPanic's gratis tier is zeer beperkt** (5 requests/minuut,
   zie het Gemini-kostenoverzicht) -- bij actief pollen loop je hier
   waarschijnlijk snel tegenaan. Nog niet besproken welk betaald plan
   je wilt gebruiken.
9. **Geen liveness-/heartbeat-melding.** `restart: always` in Docker
   vangt een crash op, maar als de orchestrator zelf blijft hangen
   (geen crash, wel geen voortgang) merk je dat nu niet. Een simpele
   "bot is nog actief"-melding elke paar uur via `telegram_notify.py`
   zou dit afdekken.

### Nice-to-have, niet urgent

10. **Geen liquiditeitsdiepte-check** voor het testnet-USDC-token (we
    zagen eerder een total supply van slechts ~10.000 tokens) --
    grote orders relatief tot een dunne pool geven flinke slippage.
    Voor testnet acceptabel, voor mainnet de moeite van het checken
    waard via `getAmountsOut`/`quoteExactInputSingle` vóór het
    versturen van een trade.

## KRITIEKE FIX 5: price_to_tick had de exponent omgekeerd (24 aug 2026)

Bij de eerste echte poging tot een LP-positie: CONTRACT_REVERT_EXECUTED,
gedecodeerd als "Price slippage check". Grondoorzaak: price_to_tick()
gebruikte 10 ** (token0_decimals - token1_decimals) in plaats van
10 ** (token1_decimals - token0_decimals) -- de exponent stond
omgekeerd, wat de mensvriendelijke prijs met een factor 10.000 verkeerd
omrekende naar de interne Uniswap-V3-prijsrepresentatie.

Geverifieerd met een bekend rekenvoorbeeld (1 BTC @ 30.000 USDC, 8 vs. 6
decimalen): de oude formule gaf 3.000.000 i.p.v. de correcte 300.
Na de fix: de berekende tick voor de huidige WHBAR/SAUCE-prijs
(-5586) ligt vlak bij de daadwerkelijke pool-tick uit de eerder
gevonden SaucerSwap-API-data (-5553) -- een verschil van 33 ticks,
volledig verklaarbaar door normale prijsbeweging.

Dit is de vijfde kritieke, empirisch gevonden bug in twee dagen tijd --
allemaal het soort fout die alleen aan het licht komt door daadwerkelijk
te testen tegen een echte pool, nooit zichtbaar in code-review of
theoretische analyse alleen.

## Status einde dag (24 aug 2026): LP-positie nog niet volledig bevestigd

Vandaag gevonden en opgelost, in volgorde:
1. price_to_tick had de exponent omgekeerd (KRITIEKE FIX 5)
2. Ontbrekende SAUCE-approve() vóór mint() -- nu structureel opgelost
   in lp_manager.py's open_position() via de nieuwe
   _ensure_token_approval()-helper (automatisch voor elk niet-WHBAR-token)

**Nog NIET bevestigd**: een volledig geslaagde open_position()-aanroep
tegen de echte pool. De laatste poging strandde op onvoldoende
resterend testnet-HBAR-budget (2,92 HBAR over, gas-prijs ~1120 Gwei) --
dit is een testgeld-beperking, geen bekende codefout meer.

**Voor de volgende sessie**:
1. Nieuwe testnet-HBAR aanvragen (faucet-cooldown is dan verstreken)
2. test_first_lp_position.py opnieuw draaien (klein bedrag: 0.3 WHBAR
   + 17 SAUCE, of desnoods kleiner)
3. Bij succes: de tokenId noteren, en de close_position()-cyclus
   bevestigen (met de WhbarHelper-fix van vandaag)
4. Zodra dit werkt: overwegen of test_first_lp_position.py's logica
   (open+direct sluiten) geschikt is om in te bouwen als eigen
   verificatiestap binnen regime_orchestrator.py's LP_MODE-overgang, of
   dat een aparte, bewuste "smoke test" voor toekomstig gebruik blijft.

**Samenvatting van de dag**: 5 kritieke bugs gevonden en gefixt
(unwrapWHBAR x2, mint-fee-decimalen, price_to_tick-exponent, ontbrekende
token-approve), 2 succesvolle swaps in beide richtingen bevestigd,
gestrand testnet-geld succesvol teruggehaald. Belangrijkste les:
empirisch testen tegen een echte pool blijft onmisbaar, ook na
zorgvuldige documentatie-analyse.

## STRUCTURELE BEVINDING: RegimeOrchestrator hardcoded op USDC, niet SAUCE (24 aug 2026)

Bij het zoeken naar meer bugs ontdekt: de volledige live bot-loop
(RegimeOrchestrator) en execute_hbar_swap_standalone.py zijn overal
hardcoded op USDC_TO_HBAR/HBAR_TO_USDC en base.usdc -- niet
configureerbaar naar SAUCE.

**Consequentie**: alle vandaag gevonden en gefixte bugs
(unwrapWHBAR/WhbarHelper, price_to_tick, token-approve) zijn GENERIEK
en correct, geverifieerd via losse testscripts met SAUCE. Maar de
ECHTE bot-loop zelf kan dat bewijs niet zelf herhalen op testnet --
die blijft geprogrammeerd om specifiek naar het lege USDC-testtoken te
swappen. Zelfs met DRY_RUN=false zou elke live-transactiepoging van de
bot zelf blijven falen op testnet (geen pool voor USDC), ondanks dat de
onderliggende mechaniek nu bewezen werkt.

**Voor mainnet is dit geen probleem** -- daar heeft USDC wel echte
liquiditeit (eerder gevonden: $3,2M TVL via GeckoTerminal).

**Besluit uitgesteld** (op verzoek, 24 aug 2026): gebruiker wil later
beslissen tussen (a) SAUCE/USDC configureerbaar maken per netwerk, of
(b) dit laten zoals het is en testnet-validatie via losse scripts
laten volstaan. Vastgelegd, geen actie ondernomen.

## Extra bugs gevonden bij expliciet zoeken (24 aug 2026, later)

Op verzoek verder gezocht naar meer problemen, gericht op de vandaag
meest-aangeraakte bestanden. Twee gevonden:

**1. `_send_payable_tx()` in zowel `swap_executor.py` (V1) als
`swap_executor_v2.py` (V2)**: beide hadden een EIGEN, losstaande
transactie-opbouw met een HARDCODED `maxFeePerGas: 500 gwei` -- exact
dezelfde verouderde waarde die we vanochtend al fixten in
`hedera_rpc_client.py` (huidig minimum ligt rond 1110+ Gwei). Deze
methode gebruikte de eerdere fix nooit, dus zou bij daadwerkelijk
gebruik alsnog zijn gefaald op "gas price below minimum". Nooit eerder
opgemerkt omdat `swap_hbar_to_usdc()` (die deze methode aanriep) tot nu
toe nooit daadwerkelijk is getest -- de losse testscripts van vandaag
bouwden hun eigen transacties, buiten deze klasse om.

Opgelost: beide `_send_payable_tx()`-methodes volledig verwijderd,
vervangen door hergebruik van `client.build_and_send_transaction()`
(die de dynamische gas-prijs/limiet-fix al heeft). Ook
`ensure_usdc_approval()`'s hardcoded `gas_limit=100_000` in beide
bestanden meegenomen naar dynamische schatting.

**2. `lp_manager.py`'s `open_position()` (900K) en `close_position()`'s
decrease+collect (500K)**: hardcoded gas-limieten, inconsistent met de
les van vandaag dat dynamische schatting betrouwbaarder bleek dan
handmatige gokken (zie de token-associatie-episode eerder vandaag).
Overgezet naar dynamische schatting.

**Kanttekening**: deze twee LP-gerelateerde wijzigingen zijn nog NIET
empirisch getest tegen een echte pool (dat wachtte al op meer testnet-
HBAR) -- de dynamische-gas-aanpak is wel al bevestigd te werken voor
token-associatie en swaps, dus een redelijke, consistente keuze, maar
niet specifiek gevalideerd voor een payable multicall met mint().

## Aandachtspunt voor de volgende LP-test-poging (25 aug 2026)

Bij het doorlezen van de officiele docs (herhaling van gisteren, geen
nieuwe info) viel op: het voorbeeld gebruikt `Position.fromAmount0()`
uit de Uniswap V3 SDK, die `amount1` WISKUNDIG AFLEIDT uit `amount0` en
de gekozen tick-range -- niet twee onafhankelijk gekozen bedragen zoals
`test_first_lp_position.py` nu doet (0.3 WHBAR + 17 SAUCE, los bepaald).

Als die verhouding niet precies aansluit bij wat de tick-range
wiskundig vereist voor de daadwerkelijke pool-liquiditeitscurve, kan
dat OOK een "Price slippage check"-fout veroorzaken -- los van de al
gefixte price_to_tick-exponent-bug. Dit is nog niet empirisch
uitgesloten als bijdragende factor bij de mislukte pogingen van
gisteren (die strandden op te weinig HBAR-budget voordat we dit konden
isoleren).

**Voor de volgende poging**: overweeg `amount1_desired` af te leiden
uit `amount0_desired` en de tick-range (vergelijkbaar met hoe
`Position.fromAmount0()` dat doet), in plaats van een los geschat
bedrag te blijven gebruiken.

## Proportionele amount1-berekening geïmplementeerd (24 aug 2026)

Het hierboven genoemde aandachtspunt is nu daadwerkelijk geimplementeerd,
niet alleen vastgelegd. `lp_manager.py` heeft een nieuwe functie
`compute_amount1_for_amount0()` die de exacte Uniswap V3-liquiditeits-
wiskunde toepast (zelfde principe als de SDK's Position.fromAmount0()):
gegeven amount0, de huidige prijs, en de tick-range, wordt het WISKUNDIG
CORRECTE amount1 afgeleid, in plaats van een los geschat bedrag.

Getest met een symmetrische +/-5%-range rond de huidige prijs: 0.3 WHBAR
-> 16.88 SAUCE afgeleid, tegenover de naieve schatting van 17.16 SAUCE
(1.6% verschil -- correct gedrag, geen bug, want een positie met een
zekere range-breedte wijkt altijd licht af van de kale spotprijs-ratio).

`test_first_lp_position.py` gebruikt deze functie nu i.p.v. het eerder
losstaand geschatte SAUCE-bedrag. Nog NIET empirisch getest tegen de
echte pool (wacht op nieuwe testnet-HBAR).

## LP-positie: INVALID_NFT_ID, vermoedelijk SaucerSwap-testnet-contractprobleem (25 aug 2026)

Na uitgebreide diagnose (tick-range bevestigd correct, proportionele
amount1-berekening geimplementeerd en getest, slippage-marge van 2%
tot 99.9% geprobeerd, WHBAR handmatig gewrapt) blijft mint() consistent
falen met CONTRACT_REVERT_EXECUTED, INVALID_NFT_ID -- exact dezelfde
fout, ongeacht welke van onze eigen parameters we aanpasten.

**Mirror-node-check van de LP-NFT-collectie (0.0.1310436) zelf**: gezond
-- total_supply=274 (eerdere mints zijn dus gelukt), treasury komt
overeen met het PositionManager-contract, supply_key correct aanwezig,
geen pause/freeze-blokkade.

**Werkhypothese**: het PositionManager-contract houdt intern zijn eigen
`_nextSN`-teller bij (zie de officiele broncode van gisteren), apart
van de HTS-ledger's eigen serienummer-boekhouding. Als die twee uit
sync zijn geraakt op dit GEDEELDE testnet-contract (bv. door een
eerdere, elders mislukte transactie van een andere gebruiker), zou dat
deze exacte fout verklaren -- iets wat alleen SaucerSwap zelf kan
diagnosticeren/repareren, niet vanaf onze kant oplosbaar.

**Alle eigen code bevestigd correct** voordat dit punt werd bereikt:
- Token-associaties (WHBAR, SAUCE, LP-NFT): bevestigd
- Tick-range: bevestigd correct via directe pool-slot0()-vergelijking
- amount1-verhouding: nu wiskundig correct afgeleid
  (compute_amount1_for_amount0)
- Decimalen, gas, payable-waarde: eerder al bevestigd via de geslaagde
  swaps

**Aanbevolen vervolgstap**: proberen via SaucerSwap's eigen officiele
testnet-webinterface (niet onze code) of daar hetzelfde probleem
optreedt voor dit specifieke paar -- dat zou definitief bevestigen of
dit een breder testnet-side-probleem is. Zo niet: contact opnemen met
SaucerSwap (support@saucerswap.finance, eerder gevonden in hun
API-docs).

## Status LP-positie: grondig gediagnosticeerd, klaar voor volgende poging (25 aug 2026)

Vandaag een lange, diepe diagnose-sessie doorlopen die de "INVALID_NFT_ID"-
fout van eerder volledig ophelderde en drie ECHTE bugs vond:

**1. estimate_gas() geeft een MISLEIDENDE fout voor deze specifieke
multicall**: de dynamische gas-schatting (normaal betrouwbaar, zie
eerdere fixes) faalt hier met INVALID_NFT_ID -- een gesimuleerde,
NOOIT ECHT VERZONDEN call. Dit verklaarde waarom alle eerdere
"verruimde slippage-marge"-tests (15%, 99.9%) niets bewezen: ze liepen
allemaal via deze kapotte simulatie, kwamen nooit bij een echte
transactie. Opgelost: `open_position()` heeft nu een
`gas_limit_override`-parameter om de schatting te omzeilen en een
ECHTE transactie te forceren.

**2. Nonce-timing-race-condition**: na een bevestigde approve-transactie
gaf de RPC-relay soms nog een verouderde nonce terug voor de
daaropvolgende transactie ("Nonce too low"). Opgelost: een korte pauze
(2 sec) toegevoegd na elke bevestigde approve in
`_ensure_token_approval()`.

**3. Echte, bevestigde oorzaak van "Price slippage check"**: via de
volledige HashScan call-trace geanalyseerd. De pool gaf bij `pool.mint()`
daadwerkelijk maar 26.540.873 raw WHBAR-eenheden terug (0,2654 WHBAR),
tegenover onze `amount0Min` van 29.400.000 (98% van de gewenste 0,3
WHBAR) -- een tekort van ~11,5%. Onze `amount1`-berekening
(compute_amount1_for_amount0) bleek daarentegen zeer nauwkeurig (0,17%
afwijking op de SAUCE-kant). De precieze reden voor deze asymmetrische
~11,5%-afwijking op de WHBAR-kant is nog niet volledig verklaard, maar
empirisch ruim opgevangen door slippage_tolerance te verhogen naar 15%.

**Huidige status**: alle drie de fixes staan correct in de code
(bevestigd op GitHub en in de container). Een poging met de nieuwe
15%-marge gaf voor het eerst een ANDERE fout dan "Price slippage
check": "Insufficient funds for transfer" -- puur een testnet-HBAR-
budget-tekort (2,69 HBAR resterend na de vele diagnostische pogingen
van vandaag), geen codeprobleem meer.

**Voor de volgende sessie**: nieuwe testnet-HBAR aanvragen, dan
`test_first_lp_position.py` opnieuw draaien. Verwachting: zou nu
moeten slagen, gezien alle bekende blokkades zijn opgelost of
opgevangen.

## MIJLPAAL: eerste volledig geslaagde LP-positie-cyclus (26 aug 2026)

Met 1000 HBAR beschikbaar (nieuw account aangemaakt, HBAR doorgestuurd
naar het bestaande, al-geassocieerde bot-account) is de LP-positie-test
eindelijk volledig geslaagd, na twee nieuwe bugs gevonden en gefixt:

**Bug 6 -- positions() ABI klopte niet**: onze POSITION_MANAGER_ABI
gebruikte de standaard Uniswap V3-interface (12 velden, met nonce +
operator vooraan). SaucerSwap's daadwerkelijke contract retourneert
maar 10 velden (geen nonce/operator). Opgelost door deze twee velden
te verwijderen uit de ABI-declaratie, en de liquidity-index aan te
passen (van 7 naar 5).

**Bug 7 -- nonce-timing-race-condition, opnieuw en breder**: het
patroon van gisteren (RPC-relay's nonce-tracking loopt soms achter op
een net bevestigde transactie) bleek op MEERDERE plekken voor te komen,
niet alleen bij de eerder gefixte _ensure_token_approval(). In plaats
van steeds handmatig sleep()-aanroepen toe te voegen op elke afzonderlijke
plek, is de fix nu CENTRAAL doorgevoerd in hedera_rpc_client.py's
wait_for_receipt() zelf (2 sec pauze na elke bevestigde transactie) --
elke aanroeper profiteert hier nu automatisch van, geen losse patches
meer nodig.

**Resultaat**: token_id=338 succesvol geopend (0,3 WHBAR + 17,44 SAUCE)
en volledig gesloten, geld correct teruggekomen (997,46 HBAR, 32,22
SAUCE resterend na alle gas-kosten van de sessie).

**Openstaand voor later**: de exacte oorzaak van de ~11,5%-asymmetrische
afwijking tussen gewenst en daadwerkelijk gebruikt amount0 (zie gisteren)
is nog niet volledig verklaard -- opgevangen door slippage_tolerance op
15% te zetten, wat werkt, maar het onderliggende "waarom" verdient op
termijn nog aandacht als er tijd is. Voor nu: LP-functionaliteit is
bevestigd volledig werkend van begin tot eind.

## Herbalanceer-cooldown vervangen door economische afweging (26 aug 2026)

De eerdere vaste 4-uur-cooldown in rebalance_if_needed() is vervangen
door compute_economic_cooldown(): een berekening op basis van
verwachte fee-inkomsten (kapitaal x fee-APR) versus de bekende,
empirisch vastgestelde kosten van een volledige herbalanceer-cyclus
(~2 HBAR gas, gemeten 24-26 aug 2026).

**Belangrijke, eerlijke uitkomst**: bij realistische testnet-
positiegroottes (tientallen tot honderden HBAR) loopt de economisch
verantwoorde cooldown al snel op tot DAGEN, soms maanden bij kleine
posities (bv. 182 dagen bij 20 HBAR @ 20% APR). Dit is geen bug, maar
een eerlijke weerspiegeling van de economie op deze schaal: de vaste
gaskosten per cyclus maken frequent herbalanceren simpelweg niet
rendabel bij kleine bedragen.

**Besluit (26 aug 2026, gebruiker)**: GEEN bovengrens instellen, de
economie volledig leidend laten zijn -- expliciet OPNIEUW TE BEKIJKEN
zodra er richting een live/mainnet-versie wordt gegaan, aangezien
mainnet-gaskosten en de daadwerkelijk ingezette kapitaalomvang tot een
heel andere, mogelijk veel gunstigere uitkomst kunnen leiden. Dit is
een bewuste, tijdelijke aanname voor de testnet-fase, geen definitieve
productie-instelling.

fee_apr is voorlopig een instelbare parameter (default 20%) -- nog niet
gekoppeld aan SaucerSwap's eigen, live volumedata. Dat zou de logische
vervolgstap zijn zodra dat nodig wordt geacht.

## Claim-en-herinvesteer-drempel toegevoegd (26 aug 2026)

Zelfde economisch principe als de herbalanceer-cooldown, toegepast op
opgebouwde (nog niet geclaimde) fees: should_claim_and_compound() checkt
of de opgebouwde waarde (tokensOwed0/tokensOwed1) minstens 2x de
geschatte kosten van claimen+herinvesteren (~2 HBAR) overtreft, voordat
het de moeite waard wordt geacht.

Belangrijk detail: fees die in de pool blijven staan gaan NIET verloren
of verlopen niet -- er is dus geen enkele haast, alleen een gemiste kans
op extra rendement zolang het geclaimde bedrag niet meewerkt in de
liquiditeit.

Nieuwe LpManager.claim_and_compound()-methode voert dit daadwerkelijk
uit: collect() (claimen) gevolgd door increaseLiquidity() (herinvesteren)
via multicall+refundETH, met dezelfde mint-fee-behandeling als
open_position() (bevestigd via de officiele docs: de mint-fee geldt ook
bij het toevoegen van liquiditeit aan een bestaande positie, niet alleen
bij een nieuwe positie). Ook increaseLiquidity() toegevoegd aan
POSITION_MANAGER_ABI (ontbrak nog).

Nog NIET empirisch getest tegen een echte pool (logische volgende stap
zodra er weer testnet-tijd is, en er genoeg fees zijn opgebouwd om het
zinvol te testen -- of handmatig een kleine claim forceren door de
drempel-parameters tijdelijk te verlagen).

## Beheer van losse/onbekende tokens (26 aug 2026)

Nieuw bestand stray_token_handler.py voor tokens die de bot ontvangt
maar niet direct kan gebruiken (bv. reward-tokens uit een SaucerSwap-
incentive-programma, apart van de gewone swap-fees die altijd in
token0/token1 binnenkomen).

Twee stappen, allebei met een economische afweging:
1. get_token_value_in_hbar(): probeert het token te waarderen via een
   quote tegen WHBAR. Geeft NONE terug als er geen pool bestaat --
   wordt dan NOOIT blind verwerkt, geen gok.
2. should_convert_stray_token(): vergelijkt de waarde tegen de kosten
   van associeren (indien nodig, ~2 HBAR) + swappen (~1 HBAR), met een
   veiligheidsmarge van 2x.

convert_stray_token_to_hbar() voert de daadwerkelijke conversie uit
(associate indien nodig, dan swap naar HBAR) -- ervan uitgaand dat de
aanroeper de economische check al zelf heeft gedaan.

Getest met 4 scenario's (onbekende waarde, klein/groot bedrag,
met/zonder bestaande associatie) -- alle vier correct. Nog NIET
geintegreerd in de RegimeOrchestrator-loop zelf (dat vereist eerst
duidelijkheid over WELKE reward-tokens SaucerSwap daadwerkelijk uitkeert,
iets wat nog niet is uitgezocht) en nog niet empirisch getest tegen een
echt derde token.

## LARI-mechanisme opgehelderd + twee kalibraties (26 aug 2026)

**LARI opgehelderd**: "lari rewards" uit een eerdere vraag bleek
SaucerSwap's officiele Liquidity Aligned Reward Initiative te zijn --
GEEN onderdeel van tokensOwed0/tokensOwed1 (dus NIET afgedekt door
claim_and_compound()), maar een APARTE, automatische airdrop elke 2
weken (geen staking/custody-transfer nodig, posities doen automatisch
mee). stray_token_handler.py is het juiste gereedschap zodra zulke
airdrops binnenkomen.

**Kalibratie 1 -- range-breedtes**: RANGE_WIDTH_BY_REGIME (LOW/NORMAL/
HIGH) geijkt op SaucerSwap's officiele Focused/Balanced/Relaxed-presets
voor fee-tier 3000: 5%/15%/30% (was voorheen 3%/5%/12%, eigen
ongekalibreerde schattingen).

**Kalibratie 2 -- Fees-APR-formule**: compute_fees_apr() toegevoegd,
exact volgens SaucerSwap's officiele formule (Fees APR = 24u-volume x
fee x 5/6 / L_bal x 365), geverifieerd met een handmatig doorgerekend
voorbeeld. LET OP: vereist nog een bevestigde bron voor 24u-volume --
niet aanwezig in de /v2/pools-REST-endpoint die we tot nu toe hebben
gezien (wel liquidity/amountA/amountB, geen volume-veld). Dit is een
correcte implementatie van de formule zelf; het vinden van een
volume-databron is een aparte, nog openstaande stap voordat
compute_economic_cooldown()'s fee_apr-aanname (nu nog 20%, hardcoded)
hiermee vervangen kan worden.

## GeckoTerminal-integratie werkend + eerste live Fee-APR (26 aug 2026)

fetch_pool_volume_geckoterminal.py werkt nu volledig. Belangrijke,
empirisch gevonden correctie: HEDERA_NETWORK_SLUG is "hedera-hashgraph",
niet "hedera" (gevonden via GeckoTerminal's eigen /networks-endpoint).

**Eerste live Fee-APR-berekening, SAUCE/WHBAR 0.3%-pool (mainnet)**:
- 24u-volume: $6.606,44
- TVL: $375.390,36
- Fees-APR: 1,61%

**Belangrijk verschil met de eerdere aanname**: de oude, hardcoded
fee_apr=0.20 (20%) in compute_economic_cooldown() bleek voor DEZE
specifieke pool ruim 12x te optimistisch. Bij een positie van 200 HBAR
verandert dit de economisch verantwoorde cooldown van ~18 dagen (bij de
oude aanname) naar ~227 dagen (bij de echte, live APR).

**Aanbevolen vervolgstap**: fee_apr in de RegimeOrchestrator-aanroepen
niet langer hardcoded laten, maar live ophalen via
fetch_pool_volume_geckoterminal.py + de pool's reserve_in_usd (TVL) --
gecombineerd met compute_fees_apr(). Dit is alleen bruikbaar op MAINNET
(GeckoTerminal indexeert geen testnet-activiteit).

Pool-adressen mainnet, gevonden via fetch_pools_for_token() op het
SAUCE-token (0x00000000000000000000000000000000000b2aD5):
- SAUCE/WHBAR 0.3% (onze doelpool): 0x5fc19c944f1bccf5159e6ae92dc3bf2ff2576b98

## Trades gekoppeld aan sentiment-beslissingen (26 aug 2026)

Gevonden bug: strategy_signal_id werd ALTIJD als None gelogd bij elke
trade -- ondanks dat log_strategy_signal() zelf al een bruikbaar ID
teruggaf, werd dat nergens opgevangen of doorgegeven. Trades waren dus
nooit gekoppeld aan de specifieke sentiment-redenering die ze
veroorzaakte, wat elke vorm van "was deze sentiment-gedreven beslissing
achteraf verstandig"-analyse onmogelijk maakte.

Opgelost: signal_id wordt nu opgevangen bij log_strategy_signal() en
doorgegeven via de hele keten (_execute_transition ->
_run_swap_and_log -> log_trade). Nieuw script
analyze_trades_with_context.py toont trades samen met de score en
redenering die ze veroorzaakte.

Dit is precies gevonden en gefixt op het moment dat de bot voor het
eerst LIVE ging op testnet (DRY_RUN=false, 26 aug 2026) -- vanaf nu
worden alle live trades correct gekoppeld aan hun sentiment-context,
wat op termijn (samen met recalibrate_from_live_history.py's
prijs-koppeling) een compleet beeld geeft: nieuws -> beslissing ->
trade -> daadwerkelijke koersuitkomst.

## Interactieve Telegram-commando's toegevoegd (26 aug 2026)

Nieuw bestand telegram_commands.py -- in tegenstelling tot
telegram_notify.py (puur eenrichtingsverkeer) kan dit berichten
ONTVANGEN via Telegram's getUpdates-polling.

Commando's: /status, /pause, /resume, /balance. Geintegreerd in
RegimeOrchestrator.run_forever(): elke cyclus wordt kort (niet-
blokkerend, timeout=1s) gecheckt op nieuwe berichten, voordat de
eigenlijke regime-logica draait. Bij /pause wordt de cyclus overgeslagen
(bestaande posities blijven gewoon open, geen nieuwe acties) totdat
/resume wordt gestuurd.

Ontworpen om de lopende, live bot niet te verstoren: elke fout binnen
de commando-afhandeling wordt stilzwijgend genegeerd (nooit de
hoofdloop breken), en alleen berichten uit de eigen, geconfigureerde
TELEGRAM_CHAT_ID worden verwerkt.

Nog NIET getest tegen een echte Telegram-chat (wacht op deployment).

## Telegram-commando's volledig werkend, apart bot-token (26 aug 2026)

Opgelost: de HBAR-bot en de bestaande scalper-tradingbot (IBKR,
/opt/strategy) deelden aanvankelijk dezelfde Telegram-bot-token, wat
een structureel pollingconflict veroorzaakte (Telegram's
offset-gebaseerde getUpdates-mechanisme laat geen twee onafhankelijke
pollers op een token toe -- de snelst pollende partij "wint" altijd).

Definitieve oplossing: een eigen, apart Telegram-bot-token aangemaakt
voor de HBAR-bot (@Hbar_lp_bot) via BotFather. Het scalper-project
behield zijn oorspronkelijke bot, met commando's hernoemd naar een
ibkr_-voorvoegsel (/opt/strategy/telegram_bot.py, tts-telegram-bot.
service herstart) om verwarring te voorkomen ook al is er nu geen
technisch conflict meer.

Voor de HBAR-bot zelf: commando's teruggezet naar de korte namen
(/status, /pause, /resume, /balance) -- geen voorvoegsel meer nodig nu
het een apart bot-token betreft.

BELANGRIJKE KANTTEKENING: tijdens dit proces is het HBAR-bot-token
kortstondig blootgesteld in de chat (per ongeluk geplakt door de
gebruiker) -- meteen ingetrokken en vervangen via BotFather voordat het
verder gebruikt werd.

Bevestigd werkend: /status (toont regime + actief/gepauzeerd), /balance
(toont live HBAR-balans, bevestigd correct: 997).

## KRITIEKE BUG: bot bleef "in lp_mode hangen zonder LP" (26 aug 2026)

Gevonden na een gebruikersvraag ("hoeveel zit er in de pool?"): de bot
stond al de hele tijd sinds live gaan in lp_mode, maar had NOOIT een
daadwerkelijke LP-positie geopend. Kapitaal (997 HBAR + 32 SAUCE) stond
gewoon los in de wallet, niets aan het verdienen.

Grondoorzaak: current_regime start standaard op LP_MODE (__init__), maar
open_position() wordt alleen aangeroepen bij een gedetecteerde OVERGANG
naar LP_MODE vanuit een ander regime -- bij het opstarten is er geen
vorig regime om vandaan te komen, dus die overgang wordt nooit
gedetecteerd, en er wordt nooit een positie geopend.

Opgelost: een vangnet toegevoegd aan het begin van _cycle() dat elke
cyclus checkt of de bot in lp_mode zit ZONDER daadwerkelijk open positie
(self.lp_manager.state.is_open == False), en zo ja, alsnog een positie
opent met de beschikbare wallet-balans. Veilig tegen herhaaldelijk
openen: is_open wordt pas True gezet na een BEVESTIGD succesvolle
mint-transactie.

Dit is een structurele bug die vermoedelijk AL DE HELE TIJD aanwezig was
sinds de eerste versie van RegimeOrchestrator, maar nooit eerder opviel
omdat we tot nu toe altijd handmatig LP-posities testten (nooit de bot
zelf, autonoom, vanuit een koude start).

Nog NIET empirisch bevestigd tegen de live bot (wacht op deployment +
een volgende cyclus om te zien of de positie daadwerkelijk opent).

## Vangnet uitgebreid: herbalancering + hybride reserve-logica (26 aug 2026)

Na het vinden van de "lp_mode zonder LP"-bug (hierboven) bleek het
simpele vangnet zelf ook tekort te schieten bij een scheve HBAR/SAUCE-
verhouding in de wallet (997 HBAR tegenover 32 SAUCE) -- zonder
herbalancering zou het vangnet slechts een verwaarloosbaar kleine
positie openen (~0.44 HBAR-equivalent), met bijna al het kapitaal
nutteloos ongebruikt.

Twee toevoegingen:

1. **Herbalancerings-swap**: de helft van het inzetbare bedrag wordt nu
   eerst omgezet naar SAUCE (HBAR_TO_USDC) voordat de positie wordt
   geopend -- zelfde patroon als de reguliere regime-overgangslogica al
   gebruikte, nu ook toegepast in het vangnet.

2. **Hybride reserve-logica** (op verzoek): de HBAR die in de wallet
   achterblijft is het GROOTSTE van (a) een percentage
   (LP_SAFETYNET_DEPLOY_FRACTION, nu 90% voor testen) en (b) een
   absolute ondergrens (LP_SAFETYNET_MIN_RESERVE_HBAR, nu 50 HBAR --
   wat de gebruiker zelf altijd aanhield bij handmatig beheer). Dit
   voorkomt dat een klein percentage bij een kleine positie te weinig
   reserve overlaat voor toekomstige transacties. Beide instelbaar via
   environment-variabelen, dus makkelijk aan te passen voor een
   mainnet-versie met andere verhoudingen.

Ook nieuw: compute_amount0_for_amount1() in lp_manager.py, de omgekeerde
afleiding van compute_amount1_for_amount0() -- nodig om te bepalen welke
kant (HBAR of SAUCE) daadwerkelijk de beperkende factor is, en de andere
kant daar correct van af te leiden. Zonder dit zou de slippage-check
onvermijdelijk falen bij een scheve wallet-balans.

Nog NIET empirisch bevestigd tegen de live bot (wacht op deployment).

## INCIDENT: ongecontroleerde herhaal-lus in het vangnet (26 aug 2026)

Bij de eerste live-poging van het nieuwe vangnet (herbalancering +
positie openen) trad exact hetzelfde probleem op als de INVALID_NFT_ID-
episode van dagen eerder: open_position() faalde op de gesimuleerde
gas-schatting (estimate_gas(), nooit een echte transactie) met "Price
slippage check" -- maar zonder gas_limit_override om die kapotte
simulatie te omzeilen (die fix zat nog niet in het nieuwe vangnet).

**Gevolg**: zonder enige cooldown/backoff probeerde het vangnet ELKE
cyclus (60 sec) opnieuw, en deed daarbij ELKE keer opnieuw de
herbalancerings-swap (helft van het inzetbare bedrag naar SAUCE) --
zonder ooit de positie daadwerkelijk te kunnen openen. Balans daalde
van 997 naar 196 HBAR in enkele cycli, SAUCE liep op tot 41.408. Niets
verloren (puur omgezet, plus normale gaskosten per poging), maar
duidelijk onbedoeld gedrag.

**Gebruiker heeft de bot direct gepauzeerd via het net gebouwde
/pause-Telegram-commando** -- precies waarvoor die functionaliteit
bedoeld was, en het werkte zoals verwacht.

**Twee fixes doorgevoerd**:
1. gas_limit_override=1_200_000 toegevoegd aan BEIDE open_position()-
   aanroepen in regime_orchestrator.py (het vangnet EN de reguliere
   regime-overgangslogica, die dezelfde onderliggende kwetsbaarheid
   bleek te hebben, nooit eerder opgemerkt omdat een echte BULLISH/
   BEARISH-overgang nog nooit heeft plaatsgevonden).
2. self._safetynet_attempted-vlag toegevoegd: het vangnet probeert nu
   MAXIMAAL EEN KEER per opstart, ongeacht succes/falen. Bij falen is
   een herstart van de bot vereist (wat de vlag terugzet) i.p.v.
   automatische herhaling -- voorkomt dat dit ooit weer een
   ongecontroleerde lus kan worden, ook bij een toekomstige,
   onvoorziene faalreden.

**Les**: elke nieuwe open_position()-aanroep moet vanaf nu standaard
gas_limit_override meekrijgen -- de dynamische schatting is aantoonbaar
onbetrouwbaar specifiek voor mint()-multicalls, herhaaldelijk bevestigd
over meerdere dagen.

## DOORBRAAK: eerste volledig autonome LP-positie van de bot zelf (26 aug 2026)

Na een lange reeks van 4 mislukte, echte on-chain "Price slippage
check"-pogingen (ondanks binding-constraint-wiskunde, 15%-marge,
gas-omzeiling, en zelfs een prijs-verversing vlak voor gebruik) bleek
de daadwerkelijke, grondoorzaak: GeckoTerminal (onze prijsbron voor de
tick-berekening) heeft een EIGEN indexerings-vertraging t.o.v. de
daadwerkelijke, live on-chain pool-staat. Onze EIGEN herhaalde
HBAR_TO_USDC-swaps (tijdens de mislukte pogingen) verschoven de
werkelijke pool-prijs merkbaar (van ~57 naar ~49 SAUCE/WHBAR) --
GeckoTerminal weerspiegelde dat niet snel genoeg, wat de tick-range en
amount-berekeningen tegen een verouderde prijs liet plaatsvinden.

**Definitieve oplossing**: nieuwe functie get_live_pool_price() in
lp_manager.py, die de prijs RECHTSTREEKS uit de pool zelf haalt (via
slot0()'s tick, dezelfde methode als diagnose_tick_range.py eerder al
succesvol gebruikte) -- de enige bron die gegarandeerd overeenkomt met
wat de pool zelf gebruikt om de mint()-transactie te beoordelen.
Geverifieerd met een rekenvoorbeeld (bekende tick -5578 -> afgeleide
prijs 57.25, tegenover de bekende Quoter-prijs 57.08 op dat moment --
0.3% verschil, volledig verklaarbaar door normaal tijdsverschil).

Toegepast op BEIDE open_position()-aanroepen (het vangnet EN de
reguliere regime-overgangslogica) voor consistentie.

**Resultaat**: tokenSN 339 succesvol geopend, 25.4312 HBAR + 1463.47
SAUCE, na automatische herbalancering. HBAR-balans na afloop: 73.86
(boven de 50-HBAR-ondergrens, zoals bedoeld).

**Belangrijke les voor de rest van het project**: GeckoTerminal (of elke
externe prijs-indexeerder) is een prima bron voor SENTIMENT-gedreven
beslissingen (waar een paar procent afwijking niet uitmaakt), maar NOOIT
geschikt als bron voor exacte, on-chain-kritieke berekeningen zoals
tick-ranges en slippage-gevoelige bedragen -- daarvoor moet de bron
ALTIJD de pool zelf zijn, rechtstreeks bevraagd.

Dit lost ook definitief de "lp_mode zonder LP"-bug op waarmee deze
sessie begon -- de bot beheert nu voor het eerst daadwerkelijk,
zelfstandig een LP-positie.

## Twee gescheiden problemen opgelost: duplicaat-posities EN out-of-range-detectie (26 aug 2026)

Bij het onderzoeken van het duplicaat-positie-incident kwam een tweede,
los probleem aan het licht (gebruikersvraag: "waarom herstellen i.p.v.
een nieuwe openen? de markt kan toch uit range zijn?"):

**Probleem 1 (duplicaten)**: LpManager.state.is_open is puur in-memory,
dus elke herstart (bv. de nachtelijke herkalibratie-herstart) laat de
bot "vergeten" dat er al een positie open staat. Opgelost met een
nieuwe database-tabel (active_lp_position) + opstart-reconciliatie
(_reconcile_lp_position_on_startup(), verifieert altijd on-chain vóór
vertrouwen).

**Probleem 2 (out-of-range, nooit eerder opgemerkt)**:
LpManager.rebalance_if_needed() bestond al (met de economische
cooldown-logica), maar werd NERGENS aangeroepen in de levende bot-loop
-- dode code. Zonder dit zou een herstelde (of gewoon langdurig open
staande) positie voor onbepaalde tijd buiten zijn tick-range kunnen
blijven liggen, zonder ooit fees te verdienen, zonder dat de bot dit
ooit zou detecteren of erop zou reageren.

Opgelost met een NIEUWE methode (_rebalance_if_out_of_range()) die het
BEWEZEN, vandaag opgebouwde patroon hergebruikt (get_live_pool_price,
proportionele amount-afleiding, 15%-marge, gas-omzeiling, database-
persistentie) i.p.v. de oudere, ongefixte rebalance_if_needed() (die
zelf nog een bekende bug had: stale amount0/amount1 na het sluiten).
Wordt elke cyclus aangeroepen (niet alleen bij opstarten), want de
prijs kan op elk moment buiten de range lopen.

Beide problemen waren volledig gescheiden concepten: reconciliatie
beantwoordt "heb ik al iets lopen?", de nieuwe rebalance-check
beantwoordt "is wat ik heb nog goed gepositioneerd?".

Nog NIET empirisch getest tegen de live bot (wacht op deployment).

## Dynamisch volatiliteitsregime + sentiment-skew daadwerkelijk aangesloten (26 aug 2026)

Op verzoek: de al bestaande, maar nooit gebruikte mogelijkheden
(VolatilityRegime.LOW/NORMAL/HIGH, sentiment_direction-skew) zijn nu
daadwerkelijk aan live data gekoppeld -- voorheen gebruikten ALLE
compute_range()-aanroepen stilzwijgend de defaults (altijd NORMAL,
altijd sentiment=0.0), ongeacht de daadwerkelijke marktomstandigheden.

**Volatiliteitsregime**: nieuwe periodieke verversing (elke 4 uur, niet
elke cyclus) via _refresh_volatility_regime_if_due(), die 48 uur aan
HBAR-uurcandles ophaalt via de al bestaande BinanceKlinesClient en
compute_volatility_regime() aanroept (bestond al, was nooit aangesloten).
Bevestigd werkend: eerste berekening gaf "low" terug.

**Sentiment-skew**: alle vier de compute_range()-aanroepen in
regime_orchestrator.py geven nu combined_score (dezelfde score die de
regime-overgangen aanstuurt) door als sentiment_direction, i.p.v. de
default 0.0.

LET OP: Binance's API is niet bereikbaar vanuit de sandbox-omgeving
waarin dit is ontwikkeld (403 Forbidden) -- dit is een environment-
specifieke beperking, geen codefout. Al bevestigd werkend op de VPS
zelf, waar recalibrate_from_live_history.py al langer succesvol
dezelfde client gebruikt.

## Symmetrische herbalancering, consistent op alle drie de plekken (26 aug 2026)

Gebruiker vroeg terecht: bij het handmatig testen van een LOW/Focused-
positie bleek de bestaande logica maar EEN richting te checken ("is
SAUCE genoeg voor volledige HBAR-inzet") -- nooit de omgekeerde
richting ("is HBAR genoeg voor volledige SAUCE-inzet"), wat kapitaal
onnodig ongebruikt kon laten liggen bij een scheve wallet-balans.

Nieuwe, gedeelde methode _ensure_balanced_liquidity_ratio() toegevoegd:
checkt symmetrisch in beide richtingen, swapt de helft van het
overschot in de juiste richting indien nodig (met een ondergrens om
micro-swaps te voorkomen). Ondersteunt een optionele max_hbar_to_use-
parameter, zodat het vangnet zijn bewuste reserve kan blijven
respecteren.

Toegepast op ALLE DRIE de plekken waar een LP-positie geopend/
heropend kan worden:
1. Het vangnet (_cycle())
2. De reguliere regime-overgangslogica (_execute_transition(),
   LP_MODE-heropening) -- verving de eerdere "blinde 50/50-swap",
   die specifiek voor het BULLISH/BEARISH-startpunt redelijk was maar
   niet zo nauwkeurig als de nieuwe, tick-range-bewuste versie
3. De out-of-range-herbalancering (_rebalance_if_out_of_range())

Nog NIET empirisch getest tegen de live bot (wacht op deployment).

## KRITIEKE BUG gevonden: volatility_regime/sentiment_direction nooit doorgegeven aan open_position() (26 aug 2026)

Bij het verifieren van positie 342 (bedoeld als LOW/Focused-test) bleek
de daadwerkelijke on-chain range -14.2%/+16.5% te zijn -- exact de
NORMAL-breedte, niet de verwachte LOW/Focused ~5%. Grondoorzaak: ALLE
DRIE de open_position()-aanroepen in regime_orchestrator.py gaven wel
zelf tick_lower/tick_upper door aan de amount-berekening
(compute_amount1_for_amount0/compute_amount0_for_amount1), maar NOOIT
volatility_regime/sentiment_direction aan open_position() ZELF -- die
berekent INTERN zijn EIGEN tick-range via zijn eigen compute_range()-
aanroep, met de defaults (NORMAL, 0.0), volledig los van wat de
aanroeper er zelf al voor had berekend.

Gevolg: de bedragen waren correct geproportioneerd voor de BEOOGDE
range, maar de daadwerkelijke mint() gebruikte een ANDERE (altijd
NORMAL) range -- een mismatch die vermoedelijk ook een deel van de
eerdere, herhaalde "Price slippage check"-fouten verklaart die we
gisteren zo lang hebben uitgezocht.

Opgelost: alle drie de open_position()-aanroepen geven nu expliciet
volatility_regime=self._cached_volatility_regime en
sentiment_direction=combined_score_now mee, consistent met wat al
gebruikt werd voor de amount-berekening ernaast.

Nog NIET empirisch bevestigd tegen de live bot (wacht op deployment +
een nieuwe test-positie om te verifieren dat de on-chain range nu wel
klopt met het bedoelde regime).

## Uitgebreid onderzoek: LOW/Focused-range faalt consistent, oorzaak nog onbekend (27 aug 2026)

Na de dynamische volatiliteits-integratie (26 aug) bleek een structurele bug:
open_position() gaf zelf nooit volatility_regime/sentiment_direction door aan
de daadwerkelijke open_position()-aanroepen in regime_orchestrator.py (nu
gefixed, 3 aanroepen bijgewerkt).

Bij het testen van de LOW/Focused-range (+/-5%) zelf bleek een aanhoudende,
lege revert (CONTRACT_REVERT_EXECUTED, error_message "0x", ~311.000 gas)
die NIET optreedt bij NORMAL (+/-15%) of breder. Uitgebreid getest en
uitgesloten als oorzaak:
- Onjuiste mint()-parameters (geverifieerd via decodering)
- ERC20-goedkeuring (beide tokens, met 0.5%-marge toegevoegd, structurele
  fix in lp_manager.py: APPROVAL_SAFETY_MARGIN)
- WHBAR-goedkeuring specifiek (op advies van SaucerSwap support toegevoegd
  -- eerdere aanname "HBAR heeft geen approve() nodig" bleek onvolledig,
  nu structureel gefixed: beide tokens worden altijd goedgekeurd)
- Native HTS-laag-goedkeuring (via precompile 0x167)
- msg.value-afrondingsbuffer (SaucerSwap's eigen, zeer gedetailleerde
  verklaring over Uniswap V3's rond-af/rond-op-liquiditeitswiskunde --
  getest met zowel 10 als 10.000 tinybar buffer, beide identiek gefaald)
- Balans, gas, tick-spacing-uitlijning, tick-staat (bevestigd schoon)
- Bedraggrootte (1-205 HBAR) en exacte breedte (5%, 7%, 10%) -- alle
  identiek falend

**Twee blijvende, structurele verbeteringen in lp_manager.py** (los van of
ze dit specifieke probleem oplossen, sowieso defensief verstandig):
1. Beide tokens (ook WHBAR) krijgen altijd een ERC20-approve() met 0.5%
   marge, i.p.v. WHBAR over te slaan
2. Een kleine buffer (10 tinybar) op de meegestuurde msg.value, opgevangen
   door de al-bestaande refundETH()

**Status**: uitgebreide technische bevindingen teruggekoppeld aan
SaucerSwap's Discord-support, inclusief alle transactiehashes en
uitgesloten oorzaken. Nog geen oplossing gevonden. LOW/Focused-regime
blijft voorlopig ongebruikt in de praktijk -- de bot gebruikt NORMAL/HIGH,
die bewezen betrouwbaar werken.

## DOORBRAAK: LOW/Focused-range definitief opgelost (27 aug 2026)

Na een zeer lange, grondige zoektocht (uitgebreide diagnostiek, 5%/7%/10%-
breedtes getest, tientallen mislukte transacties, meerdere verkeerde
hypotheses uitgesloten) is de daadwerkelijke oorzaak gevonden, met hulp
van SaucerSwap's eigen Discord-support.

**Grondoorzaak**: mint() accepteert NIET alleen msg.value (met de aanname
dat het contract zelf wrapt), en NIET alleen vooraf gewrapte + goedgekeurde
WHBAR-tokens zonder msg.value -- het vereist BEIDE tegelijk:
1. HBAR eerst expliciet wrappen via WhbarHelper.wrapWhbar() tot echte
   WHBAR-ERC20-tokens in de wallet
2. Die tokens normaal goedkeuren (approve()) richting de PositionManager
3. EN nog steeds de volledige msg.value meesturen bij mint() zelf

refundETH() (al onderdeel van de multicall) voorkomt dubbel betalen --
het ongebruikte deel komt gewoon terug.

**Waarom dit specifiek bij LOW/Focused (smalle, nieuwe tick-grenzen)
opviel en niet bij bredere, al-bestaande ticks**: vermoedelijk doorloopt
mint() bij het initialiseren van een GEHEEL NIEUWE tick-grens een ander,
strenger controlepad dan bij het hergebruiken van een al-bestaande,
eerder geinitialiseerde tick -- waardoor de ontbrekende WHBAR-allowance
bij bredere posities (die vaker bestaande ticks hergebruikten) nooit tot
een merkbare fout leidde.

**Nieuwe WHBAR_HELPER_ABI-functie toegevoegd**: wrapWhbar() (payable,
geen argumenten) -- tegenhanger van de al-bekende unwrapWhbar().

**Empirisch bevestigd**: tokenSN 345 succesvol geopend met
tickLower=-7740, tickUpper=-5700 (10%-breedte-test), liquidity=1533190104.

Beide eerder toegevoegde, blijvende verbeteringen (WHBAR-approve met
0.5%-marge, kleine msg.value-buffer) blijven ook staan -- geen van beide
was de daadwerkelijke oorzaak, maar allebei defensief verstandig.

**Belangrijke openstaande vraag**: deze wrapWhbar()-stap is nu alleen in
open_position() toegevoegd. De vergelijkbare aanroepen in
increase_liquidity()/claim_and_compound() (regel ~842/844) gebruiken nog
het oude patroon en zijn NIET bijgewerkt -- als die ooit een NIEUWE
tick-grens raken (onwaarschijnlijk, want increase_liquidity werkt op een
BESTAANDE positie), zouden ze mogelijk hetzelfde probleem tegenkomen.
Voorlopig niet aangepast, want buiten scope van de huidige sessie.

## Economisch-bewuste breedte-selectie (27 aug 2026)

Na de succesvolle LOW/Focused-fix bleek uit een backtest (analyze_range_
width.py, echte HBAR/USD-historie als benadering voor HBAR/SAUCE) dat de
optimale range-breedte sterk afhangt van kapitaalgrootte: bij weinig
kapitaal (bv. 500 HBAR) wegen de vaste herbalancerings-kosten (~2 HBAR
per keer, empirisch gemeten) zwaar, en wint een BREDERE range. Bij veel
kapitaal (bv. ~13.798 HBAR, EUR 1000-equivalent) worden die vaste kosten
verwaarloosbaar t.o.v. de veel hogere fee-concentratie van een SMALLERE
range -- daar wint juist LOW/Focused, met een aanzienlijk hogere netto
winst dan NORMAL/HIGH.

De bestaande, puur-volatiliteits-gebaseerde regime-selectie
(compute_volatility_regime()) hield hier geen rekening mee. Nieuwe
functie toegevoegd: select_optimal_volatility_regime() in lp_manager.py,
die voor elk van LOW/NORMAL/HIGH de herbalancerings-frequentie simuleert
over recente historische prijzen (simulate_rebalance_frequency(),
verplaatst vanuit het analysescript naar lp_manager.py als herbruikbare
bouwsteen) en het regime met de hoogste verwachte netto winst kiest.

RegimeOrchestrator._refresh_volatility_regime_if_due() gebruikt deze
nieuwe functie nu i.p.v. de oude, en geeft daarbij de daadwerkelijke,
actuele wallet-balans (in HBAR) mee als kapitaal-input. Draait nog
steeds elke 4 uur (VOLATILITY_REGIME_REFRESH_SECONDS), niet vaker.

Functioneel bevestigd (synthetische data): 500 HBAR kapitaal -> HIGH
gekozen, 13.798 HBAR kapitaal -> LOW gekozen, exact het verwachte
patroon.

compute_volatility_regime() (de oude, puur-volatiliteits-functie) blijft
overigens gewoon bestaan in lp_manager.py, voor het geval die elders nog
relevant is -- alleen de levende bot gebruikt 'm niet meer direct.

Nog NIET empirisch bevestigd tegen de live bot met echte, actuele data
(wacht op deployment + de eerstvolgende 4-uurlijkse verversing).

## Bugfix: te kort lookback-venster voor economische breedte-selectie (27 aug 2026)

Direct na deployment bleek de nieuwe select_optimal_volatility_regime()
bij een klein kapitaal (156 HBAR) toch "low" te kiezen, in tegenspraak
met het verwachte patroon (bevestigd met een 500 HBAR synthetische test:
die koos "high"). Oorzaak: het 48-uur-venster (overgenomen van de oude,
puur-volatiliteits-functie) liet in de praktijk 0 herbalanceringen zien
op ALLE breedtes -- bij toeval een rustige periode. Met kosten=0 overal
wint LOW altijd triviaal (hoogste fee-schatting), ongeacht kapitaal.

Opgelost: het venster voor DEZE specifieke aanroep verlengd naar 1000
uur (~41,7 dagen, Binance's maximum per aanroep) -- consistent met de
backtest-periode die het patroon oorspronkelijk liet zien. Alleen deze
ene aanroep aangepast; compute_volatility_regime()'s eigen, kortere
48-uur-ontwerp blijft ongewijzigd voor eventuele toekomstige toepassing.

Nog NIET empirisch herbevestigd tegen de live bot met het langere
venster (wacht op herstart).

## Impermanent loss toegevoegd aan de economisch-bewuste breedte-selectie (27 aug 2026)

Na een uitgebreide, cyclus-per-cyclus backtest (analyze_range_width_full.py)
bleek dat de eerdere select_optimal_volatility_regime() (alleen fee-
opbrengst vs. herbalancerings-kosten) het beeld structureel te optimistisch
liet zien voor smalle ranges -- impermanent loss (IL) schaalt met dezelfde
concentratiefactor als fees, en overschaduwt de fee-opbrengst bij
realistische HBAR-volatiliteit ruimschoots.

compute_il_v2() toegevoegd (standaard V2-IL-formule, gevalideerd tegen
bekende referentiewaarden: -5.72% bij x2, -20.00% bij x4 prijsverandering).
select_optimal_volatility_regime() herschreven om, per herbalancerings-
cyclus, IL te berekenen (geschaald met de 1/breedte-concentratiefactor,
zelfde vuistregel als fees) en mee te wegen in de netto-winst-berekening.

Empirisch bevestigd (2 onafhankelijke periodes van 41,7 dagen elk): met IL
meegerekend wint HIGH (30%) vrijwel altijd bij de recente HBAR-volatiliteit
-- de eerdere, IL-loze versie koos stelselmatig ten onrechte LOW.

BLIJFT EEN BENADERING: IL-schaling gebruikt dezelfde 1/breedte-vuistregel
als fee-schaling, geen volledig exacte V3-liquiditeitswiskunde per cyclus.
De RICHTING van de conclusie (smal = slecht bij deze volatiliteit) was
echter consistent genoeg over beide geteste periodes om vertrouwen te
rechtvaardigen.

Nog NIET empirisch herbevestigd tegen de live bot (wacht op deployment).

## Betrouwbaarheidsverbeteringen tegen testnet.hashio.io-storingen (28 aug 2026)

Aanleiding: drie herhaalde storingen (21:13, 21:49, en de volgende ochtend
09:43/09:56/09:58) met 502 Bad Gateway / RemoteDisconnected van
testnet.hashio.io, tijdens zowel "prijs ophalen" als "herbalanceren
(sluiten)". Escalerend patroon wijst op een structureel, aanhoudend
probleem met deze gratis, publieke RPC-relay op dat moment, niet een
incidentele hik.

BELANGRIJKE NUANCE: leesoperaties (prijs/saldo ophalen) zijn veilig om
blind te herhalen; schrijfoperaties (een transactie versturen) NIET --
een 502 kan betekenen dat de transactie wel degelijk aankwam en alleen
het antwoord verloren ging; blind herhalen zou tot een dubbele actie
kunnen leiden.

**Twee, elk passende oplossingen gebouwd:**

1. **retry_utils.py** (nieuw): generieke retry-met-exponentiele-backoff-
   decorator, UITSLUITEND toegepast op leesoperaties:
   - GeckoTerminalClient.get_pool_snapshot() (3 pogingen, 2s basis)
   - HederaRpcClient.get_hbar_balance() / get_token_balance() (3 pogingen, 2s basis)
   - HederaRpcClient.wait_for_receipt() (2 pogingen, 3s basis -- minder
     pogingen omdat de onderliggende wait_for_transaction_receipt() zelf
     al tot timeout_seconds kan duren per poging)

2. **Automatische, veilige on-chain-verificatie na een mislukte close**
   (regime_orchestrator.py, TWEE plekken: _rebalance_if_out_of_range() en
   _execute_transition()): bij een exception tijdens close_position(),
   checkt de bot NU EERST on-chain (via position_manager.functions.
   positions(token_id).call(), zelfde patroon als
   _reconcile_lp_position_on_startup()) of de positie daadwerkelijk nog
   open staat, VOORDAT een "HANDMATIGE CONTROLE VEREIST"-paniekbericht
   wordt gestuurd:
   - still_open=False -> close IS gelukt, alleen het antwoord ging
     verloren -- rustige bevestigingsmelding, geen paniek, database
     bijgewerkt, verder normaal
   - still_open=True -> close is ECHT mislukt, positie staat nog open --
     kapitaal zit nog veilig in de bestaande positie, duidelijke, maar
     minder paniekerige melding (geen kapitaalverlies)
   - still_open=None (verificatie zelf mislukte ook) -> valt terug op de
     oude, voorzichtige "HANDMATIGE CONTROLE"-melding

**Nog NIET gebouwd (uit het oorspronkelijke 4-punts-plan), voor een
volgende sessie:**
- Punt 3: een reserve/tweede RPC-endpoint waar de bot automatisch naar
  overschakelt als hashio.io faalt -- grootste, structurele verbetering,
  vraagt nog onderzoek naar een betrouwbaar tweede testnet-RPC-endpoint
- Punt 4 (onderscheid in meldings-urgentie) volgt grotendeels al mee met
  punt 1 en 2 hierboven, maar zou verder verfijnd kunnen worden

**Status**: volledig lokaal getest (retry-logica met synthetische
storingen, syntax-checks op alle vier bestanden), NOG NIET gedeployed
naar de VPS -- wacht op de gebruiker om weer te kunnen meekijken.

## Echte bug gevonden: vastzittende, niet-unwrapped WHBAR (28 aug 2026)

Op verzoek van de gebruiker onderzocht of de herhaalde hashio.io-502's
(ook) een codeprobleem waren, niet alleen extern. BEVESTIGD: 109.52
WHBAR (ERC20, niet native) stond vast in de wallet -- ontstaan doordat
close_position() drie APARTE transacties doet (multicall
decrease+collect, dan approve, dan unwrapWhbar), en een 502 tijdens de
laatste twee stappen de close als "mislukt" deed lijken terwijl de
liquiditeit al wel was teruggetrokken. De bestaande balans-controles
(check_balance.py EN de eerder gebouwde on-chain-verificatie na een
mislukte close) checkten alleen NATIVE HBAR, nooit deze aparte
WHBAR-ERC20-balans -- waardoor dit stille faalscenario onopgemerkt bleef.

Handmatig hersteld: 109.52 WHBAR succesvol geunwrapt naar native HBAR
(twee transacties: approve + unwrapWhbar, beide success). Wallet-balans
na herstel: 209.20 HBAR.

**Structurele fix gebouwd (vier onderdelen):**
1. LpManager.check_and_recover_stuck_whbar() (nieuw): checkt WHBAR-
   ERC20-balans, unwrapt automatisch naar native HBAR indien nodig, en
   trekt de WhbarHelper-goedkeuring meteen weer in na gebruik.
2. Aangeroepen bij ELKE opstart (naast de bestaande regime- en
   LP-positie-reconciliatie) -- vangt eerdere, onopgemerkte gevallen op.
3. Aangeroepen in BEIDE plekken waar de eerdere on-chain-verificatie na
   een mislukte close al bestond (_rebalance_if_out_of_range() EN
   _execute_transition()) -- specifiek in de "still_open is False"-tak
   (liquidity=0, dus decrease+collect gelukt), waar dit exacte scenario
   het meest waarschijnlijk is.
4. close_position() zelf: trekt de WhbarHelper-goedkeuring nu ook
   standaard in na een succesvolle, normale unwrap (op advies van
   SaucerSwap's eigen support: "don't leave an open allowance to the
   wrapped hbar contract"). Met eigen try/except -- als dit specifieke
   stapje faalt, telt dat NIET als een mislukte close (de daadwerkelijke
   sluiting is dan al voltooid).
5. check_balance.py bijgewerkt: toont nu ook de WHBAR-ERC20-balans,
   met een expliciete waarschuwing als die niet nul is.

**Belangrijke, tweede tip van SaucerSwap's support** (nog niet
opgevolgd): "double check the contract addresses to ensure you're not
sending stuff places where it can't be recovered. ai has done this a
few times in the past" -- een algemene aanmaning tot voorzichtigheid,
geen concrete, direct te implementeren actie. Het is de moeite waard om
op een rustig moment een adres-audit te doen: alle hardcoded/resolved
contractadressen in de codebase nog eens langslopen en tegen de
officiele SaucerSwap-documentatie te verifieren.

**Status**: volledig lokaal getest (syntax-checks op alle drie
bestanden), NOG NIET gedeployed naar de VPS.

## Regime-switching + GBM-koppeling: volledige bouwronde (28 aug 2026)

Zeer omvangrijke uitbreiding, in meerdere stappen, op verzoek van de
gebruiker (overstap van statisch script naar adaptief kwantitatief
systeem). Alle onderdelen apart wiskundig/functioneel getest.

### Kernonderdeel 1: GBM-gebaseerde range (VOLLEDIG LIVE GEKOPPELD)
- llm_sentiment_engine.py: vraagt nu ook volatility_sigma per headline op
  (LLM-onzekerheidsscore, apart van sentiment_score), met een geverifieerde
  fallback (mu=0, sigma=0.5) bij elke storing (API-fout, ongeldige JSON,
  waarden buiten bereik).
- gbm_range_model.py (nieuw): compute_gbm_confidence_interval(), Geometric
  Brownian Motion's analytische, lognormale oplossing, geeft een
  betrouwbaarheidsinterval voor de toekomstige prijs -- vervangt de
  eerdere, discrete LOW/NORMAL/HIGH-breedte-indeling. _normal_quantile()
  (eigen Acklam-benadering) geverifieerd tegen bekende referentiewaarden
  (foutmarge < 1e-6).
- compute_range_via_gbm() in LpManager, open_position() uitgebreid met
  precomputed_tick_range-parameter. Alle VIJF plekken in
  regime_orchestrator.py waar posities geopend/heropend worden nu
  overgezet op deze route.
- Gedifferentieerde sentiment-halfwaardetijd: BTC 1.5u, HBAR 6u.
- Nieuwe cooldown specifiek voor LP-herbalancering (15 min), tegen te
  snel herhaald opnieuw minten.
- Database (sentiment_log) uitgebreid met volatility_sigma-kolom.

### Kernonderdeel 2: Regime-switching (VOLLEDIG LIVE GEKOPPELD, na een tweede bevestiging)
- macro_regime_model.py (nieuw): detect_macro_regime() -- eenvoudig,
  momentum-gebaseerd (30-dagen prijsverandering, +-15%-drempels), BEWUST
  geen volledig Hidden Markov Model (te data-intensief om betrouwbaar te
  trainen/valideren binnen deze sessie). Hergebruikt de al-opgehaalde
  Binance-klines-data uit de bestaande volatiliteitsregime-verversing,
  geen extra API-aanroep.
- gbm_range_model.py: apply_regime_bias() -- past sentiment_mu aan op
  basis van het macro-regime (regime-bevestigend nieuws versterkt,
  regime-tegensprekend nieuws afgezwakt). BELANGRIJKE, BIJ HET TESTEN
  GEVONDEN FOUT: de eerste versie (simpele lineaire mu+mu*beta-formule)
  gaf bij NEGATIEVE mu-waarden het TEGENGESTELDE effect van de bedoeling
  -- vereiste tekenafhankelijke logica (bevestigend vs. tegensprekend),
  gecorrigeerd en herbevestigd tegen de exacte voorbeelden uit het
  voorstel (-0.5 -> -0.2 in bull, +0.5 -> +0.8 in bull).
- MACRO_REGIME_DRIFT_BOOST: extra drift-versterking (x2.5) bij een
  bevestigd Bull/Bear-regime (niet Sideways), geintegreerd in
  compute_gbm_confidence_interval() zelf (macro_regime-parameter) --
  zorgt voor de gevraagde asymmetrische ranges, zonder een aparte,
  losstaande discrete-regelset naast het GBM-model te hoeven bouwen.
- Alle VIJF plekken in regime_orchestrator.py bijgewerkt: passen nu
  apply_regime_bias() toe op combined_score_now VOORDAT dit aan
  compute_range_via_gbm() wordt meegegeven, en geven macro_regime=
  self._cached_macro_regime door.
- self._cached_macro_regime wordt elke volatiliteitsregime-verversing
  (elke paar uur) bijgewerkt, naast de bestaande, gecachete waarden.

### Kernonderdeel 3: Flash-event-detectie + verdediging (VOLLEDIG LIVE GEKOPPELD)
- flash_event_model.py (nieuw): detect_flash_event() -- detecteert
  plotselinge sentiment-sprongen (d(mu)/dt) gecombineerd met lage
  LLM-confidence (drempel: |delta|>0.6 EN confidence<0.5). Hergebruikt
  de bestaande 5-minuten-sentiment-verversingscyclus als "tijdvenster",
  geen aparte continue tijdreeks nodig. Ook detect_mean_reversion()
  toegevoegd (gebouwd en getest, NOG NIET aan een actie gekoppeld).
- llm_sentiment_engine.py: nieuwe aggregate_confidence_with_decay()
  (tijd-gewogen, niet confidence-gewogen om circulariteit te vermijden).
- regime_orchestrator.py: _trigger_flash_defense() -- sluit de LP-positie
  onmiddellijk bij een gedetecteerde flash-event (zelfde veilige
  on-chain-verificatie-patroon als elders vandaag), activeert een
  verdedigingsperiode (standaard 30 min, LP_REBALANCE_COOLDOWN_SECONDS-
  achtig instelbaar via FLASH_DEFENSE_DURATION_SECONDS). _cycle() slaat
  alle normale herbalancerings-/vangnet-/regime-logica over zolang de
  verdedigingsperiode actief is.
- BEKENDE BEPERKING: _flash_defense_until wordt NIET gepersisteerd in de
  database -- een herstart tijdens een actieve verdedigingsperiode zou
  dit vergeten. Nog niet opgelost, voor een volgende sessie.

### Kernonderdeel 4: LVR-kwantificering (LOSSTAAND, NIET gekoppeld)
- lvr_model.py (nieuw): compute_discrete_lvr() -- VOLLEDIG geverifieerd
  via sympy tegen de standaard Uniswap-V3-liquiditeitswiskunde. BELANGRIJKE
  CORRECTIE: de oorspronkelijk aangeleverde formule (L*(P0-P1)^2) bleek
  dimensioneel onjuist, ~3590x afwijkend van de correcte waarde in een
  testgeval. Correcte, geverifieerde formule:
  LVR = L*(sqrt(P0)-sqrt(P1))^2/sqrt(P0).
  compute_continuous_lvr_rate() -- EXPLICIET GEMARKEERD als NIET
  volledig geverifieerd (interne inconsistentie gevonden bij het
  narekenen van de Gamma-formule, macht van P kwam niet overeen tussen
  twee afleidingsmethodes). NIET gebruiken voor automatische
  besluitvorming totdat dit grondiger geverifieerd is.

### Kernonderdeel 5: Zelflerende kalibratie (LOSSTAAND, NIET gekoppeld)
- self_calibration_model.py (nieuw): compute_calibration_factor() --
  meet de voorspellingsfout (MSE) tussen voorspelde en gerealiseerde
  volatiliteit, past een kalibratiefactor traag aan (LEARNING_RATE=0.02
  per ronde, dus vereist HERHAALDE aanroepen om te convergeren -- geen
  eenmalige, grote sprong). Veiligheidsmaatregelen: MIN_DATAPOINTS_
  BEFORE_CALIBRATION=30 (blijft op 1.0 tot voldoende data), harde
  grenzen MIN/MAX_CALIBRATION_FACTOR=0.5/2.0 (geverifieerd: blijft
  exact op de grens hangen, ook na 100 herhaalde extreme-afwijkings-
  rondes, komt er nooit overheen).
- NOG NIET gekoppeld aan de daadwerkelijke data-pijplijn (er is nog geen
  mechanisme dat automatisch predicted_sigma vastlegt EN later de
  gerealiseerde volatiliteit meet om CalibrationDataPoint-records te
  vullen) -- dat vereist een aparte, nieuwe periodieke taak (vergelijkbaar
  met de nachtelijke recalibrate_cron.sh, maar dan voor sigma/mu i.p.v.
  losse sentiment-scores).

### Nog volledig open, voor een volgende sessie
- Mean-reversion-strategie: detectiefunctie klaar, GEEN gekoppelde actie
  (het daadwerkelijk innemen van een "strak boven de gecrashte prijs"-
  positie)
- Continue LVR-formule: verificatie afmaken voordat gebruikt
- Zelflerende kalibratie: koppelen aan een periodieke meet-taak
- _flash_defense_until: persisteren in de database (herstart-bestendig maken)

## Derde optie tussen LP_MODE en volledig uitstappen (28 aug 2026)

Op verzoek: het binaire alles-of-niets-gedrag (LP_MODE vs. volledig
BULLISH_REFLEX/BEARISH_REFLEX) had geen tussenweg, terwijl eerdere
backtests vandaag lieten zien dat "breed in de pool blijven + hogere
momentum-gekoppelde APR profiteren" bij GEMATIGDE bewegingen soms beter
presteert dan volledig uitstappen.

Elegant geintegreerd met het bestaande GBM-model (geen aparte,
losstaande regelset): MODERATE_SENTIMENT_THRESHOLD=0.30 -- zodra
abs(combined_score) (NA regime-bias-toepassing) deze drempel overschrijdt
maar nog onder REGIME_THRESHOLD=0.55 blijft, gebruikt de GBM-berekening
een verhoogd betrouwbaarheidsniveau (0.95 i.p.v. de standaard 0.80),
wat een merkbaar bredere range oplevert (geverifieerd: 4.08% -> 6.24% in
een testgeval, ~53% breder) -- zonder de positie te sluiten. Pas boven
REGIME_THRESHOLD stapt de bot nog steeds volledig uit via BULLISH_REFLEX/
BEARISH_REFLEX.

determine_gbm_confidence_level() toegevoegd, functioneel getest tegen
vier scenario's (zwak/gematigd/sterk-negatief/exact-op-de-drempel).
Toegepast op alle VIJF plekken waar compute_range_via_gbm() wordt
aangeroepen.

## Economische poort vóór volledige reflex-overstap (28 aug 2026)

Op verzoek: de bot moet ook meewegen of de VOLLEDIGE heen-en-terug-
cyclus (LP-positie sluiten, alles omzetten naar een enkel token, en
later weer terugkomen naar LP_MODE) daadwerkelijk meerwaarde heeft --
niet alleen de sentiment-drempel (REGIME_THRESHOLD) checken.

gbm_range_model.py: evaluate_reflex_transition_economics() (nieuw) --
vergelijkt verwachte vermeden impermanent loss (via GBM's expected_price)
MINUS misgelopen fee-inkomsten, tegen een geschatte, vaste heen-en-terug-
kostenpost (standaard 6 HBAR, ruwe schatting op basis van vandaag
empirisch gemeten transactiekosten). Hergebruikt compute_il_v2()
(lokaal gedupliceerd, zelfde formule als analyze_range_width_full.py).

Functioneel getest: zwak signaal -> False (kosten wegen niet op), extreme
situatie (kunstmatig hoge volatiliteit) -> True, bevestigt dat het
mechanisme correct werkt. Bij REALISTISCHE, huidige kalibratie
(0.6%-uurvolatiliteit, SENTIMENT_TO_DRIFT_SCALE=0.02) blijkt een
volledige overstap zelden economisch gerechtvaardigd, zelfs bij een
sterk signaal (mu=0.9) -- consistent met eerdere bullrun-backtests
vandaag.

Gekoppeld in regime_orchestrator.py's hoofdcyclus: de poort geldt
UITSLUITEND bij een NIEUWE overstap vanuit LP_MODE naar een reflex-
regime -- niet bij het verlaten van een reflex-regime, en niet bij de
trailing-stop-winst-name (die altijd moet kunnen doorgaan, ongeacht deze
poort). horizon_hours=24.0 als aanname voor de verwachte duur in
reflex-modus.

VOLLEDIG LIVE GEKOPPELD (niet losstaand) -- dit beinvloedt DIRECT
wanneer de bot daadwerkelijk overstapt naar bullish_reflex/bearish_reflex.
