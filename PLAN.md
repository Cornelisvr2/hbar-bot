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

## Volatiliteit-kalibratie gekoppeld aan de nachtelijke herkalibratie (28 aug 2026)

Op verzoek: de bestaande "koers-vs-nieuws"-tracking (recalibrate_from_
live_history.py, al bestaand van vóór vandaag, voor de few-shot-sentiment-
voorbeelden) bleek NIET ook volatility_sigma bij te houden, en voedde de
nieuwe self_calibration_model.py nog niet.

- fetch_live_sentiment_history(): query uitgebreid met volatility_sigma.
- build_volatility_calibration_datapoints() (nieuw): bouwt (voorspelde_
  sigma, gerealiseerde_sigma)-paren. BELANGRIJKE KANTTEKENING: gebruikt
  per-HEADLINE-scores als praktische proxy voor de geaggregeerde
  voorspelling die de bot destijds daadwerkelijk gebruikte (geen exacte
  reconstructie). Gerealiseerde volatiliteit genormaliseerd naar dezelfde
  0.0-1.0-schaal (aanname: 2%/uur ~ sigma=1.0). Functioneel getest met
  synthetische data (hoge voorspelling + vlakke koers -> correct lage
  gerealiseerde sigma).
- main(): berekent de kalibratiefactor via compute_calibration_factor(),
  persisteert naar volatility_calibration.json (zelfde patroon als
  calibration_examples.json -- vereist een herstart om te laden, geen
  live-herlaad-mechanisme). Stuurt een Telegram-melding bij een
  betekenisvolle wijziging (>0.01).
- regime_orchestrator.py: laadt deze factor bij het opstarten
  (_load_volatility_calibration_factor(), default 1.0 als het bestand nog
  niet bestaat). Toegepast als multiplier op combined_volatility_sigma_now
  op ALLE ZES plekken waar dat gebruikt wordt (de vijf GBM-aanroepen +
  de economische-poort-berekening), met een harde bovengrens van 1.0.

BUG GEVONDEN EN OPGELOST TIJDENS HET BOUWEN: een geautomatiseerd
regex-script voor het toepassen van de vermenigvuldiging op de vijf
GBM-locaties kreeg de inspringing verkeerd (0 spaces i.p.v. de
daadwerkelijke, contextuele inspringing) -- veroorzaakte een
IndentationError, gevonden via de gebruikelijke syntax-check en
vervolgens handmatig, per-locatie hersteld op basis van de omliggende
regels. Alle zes locaties nadien visueel geverifieerd.

VOLLEDIG LIVE GEKOPPELD (na de eerstvolgende herstart die het
gepersisteerde bestand inleest) -- nog GEEN datapunten totdat
recalibrate_from_live_history.py voor het eerst gedraaid wordt EN er
voldoende oude (>=24u) sentiment_log-historie is opgebouwd.

## KRITIEKE BUG: __init__ per ongeluk afgebroken (28 aug 2026)

Bij het toevoegen van _load_volatility_calibration_factor() werd deze
methode-definitie per ongeluk MIDDEN IN __init__() geplaatst (na
self._volatility_calibration_factor = ..., voor de rest van __init__'s
oorspronkelijke inhoud). Omdat de nieuwe @staticmethod-definitie op
DEZELFDE class-niveau-inspringing stond als __init__ zelf, beeindigde
dit __init__ VOORTIJDIG -- alle daaropvolgende, oorspronkelijke
__init__-inhoud (flash-event-velden, cooldowns, rpc_client-opzet, EN
CRUCIAAL: self.lp_manager = None + self._setup_lp_manager()-aanroep)
kwam PER ONGELUK terecht ALS ONBEREIKBARE CODE binnen de nieuwe
_load_volatility_calibration_factor()-methode (na de return-statements
van het try/except-blok daarin) -- syntactisch geldig Python, dus
ast.parse() (de gebruikelijke syntax-check) miste dit volledig.

GEVOLG IN PRODUCTIE: AttributeError: 'RegimeOrchestrator' object has no
attribute 'lp_manager' bij het opstarten -- de bot crashte volledig,
kon niet starten.

HERSTELD: methode-definitie verplaatst naar NA het einde van __init__
(na de self._setup_lp_manager()-aanroep), alle oorspronkelijke
__init__-inhoud teruggezet op zijn juiste plek. Geverifieerd op DRIE
niveaus (niet slechts syntax alleen, gezien deze fout PRECIES door een
syntax-check heen glipte):
1. ast.parse() -- syntax OK (had de fout dus niet gevonden, ter
   illustratie van waarom dit niet genoeg is)
2. AST-boom-inspectie: bevestigd dat self.lp_manager daadwerkelijk
   BINNEN __init__'s eigen function-body valt (39 top-level statements)
3. DAADWERKELIJKE INSTANTIATIE: RegimeOrchestrator(nep_db) aangeroepen,
   bevestigd dat lp_manager/rpc_client/alle nieuwe attributen correct
   bestaan en de juiste waarden hebben.

LES VOOR VERVOLG: bij wijzigingen aan __init__() (of andere methodes
waar een nieuwe methode-definitie NA een bestaande, lopende functie
wordt toegevoegd), voortaan ALTIJD ook daadwerkelijk instantieren/
aanroepen als onderdeel van de test, niet alleen ast.parse(). Een
syntax-check bevestigt alleen dat de tekst geldig Python IS, niet dat
de STRUCTUUR (welke code bij welke functie hoort) nog klopt zoals
bedoeld.

## Bug-hunt-ronde (28 aug 2026) -- drie echte bugs gevonden en opgelost

Op verzoek, na de eerdere kritieke __init__-fout: systematisch verder
gezocht naar structurele EN semantische bugs.

**Structuur-controles (geen problemen gevonden):**
- Geen dubbele methode-definities in RegimeOrchestrator (AST-gecontroleerd)
- De drie langste functies (_rebalance_if_out_of_range, _cycle,
  _execute_transition) sluiten allemaal logisch af, geen per-ongeluk-
  samengevoegde code
- combined_score_now EN combined_volatility_sigma_now: overal correct
  toegewezen VOOR gebruik, in alle drie functies waar ze voorkomen
  (AST-gecontroleerd, niet alleen visueel)
- is_price_out_of_range() gebruikt de daadwerkelijke, actieve
  self.state.tick_lower/tick_upper -- werkt correct samen met
  variabele (soms bredere, gematigde-zone) ranges, geen hardcoded aanname

**BUG 1 -- vangnet vuurt nooit meer na een flash-verdediging:**
_safetynet_attempted is ontworpen om precies EENMAAL te vuren (bij
opstarten), maar wordt daarna nooit teruggezet. Flash-verdediging
(_trigger_flash_defense()) sluit de LP-positie, maar reset deze vlag
niet -- na het aflopen van de verdedigingsperiode zou de bot dus VOOR
ALTIJD vastzitten in lp_mode ZONDER positie, kapitaal los in de wallet,
tot een handmatige herstart. OPGELOST: _safetynet_attempted = False
toegevoegd in BEIDE succesvolle-sluiting-paden binnen
_trigger_flash_defense() (normale afsluiting + de on-chain-verificatie-
na-mislukking-route).

**BUG 2 -- stuck-WHBAR-check ontbrak in het flash-verdedigingspad:**
De drie eerder gebouwde toepassingen van check_and_recover_stuck_whbar()
(opstarten, _rebalance_if_out_of_range, _execute_transition) misten het
flash-verdedigingspad, terwijl close_position() daar exact hetzelfde
driestaps-risico (decrease+collect, approve, unwrap) loopt. OPGELOST:
toegevoegd aan de "still_open is False"-tak binnen
_trigger_flash_defense().

**BUG 3 -- flash-verdediging blokkeerde onterecht de trailing-stop
tijdens BULLISH_REFLEX:** de cyclus-brede flash-verdedigings-check
("if self._flash_defense_until > time.time(): return") gold
ONVOORWAARDELIJK, ook tijdens BULLISH_REFLEX -- waar geen LP-positie
open staat om te beschermen, maar waar de trailing-stop (een EIGEN
kapitaalbeschermingsmechanisme) daardoor 30 minuten lang niet kon
reageren op een eventuele crash. OPGELOST: de blokkade geldt nu alleen
nog als self.current_regime == Regime.LP_MODE.

**Vervolgens ontdekte, gerelateerde tweede laag van bug 3:** met de
trailing-stop nu vrijgegeven tijdens flash-verdediging, zou een
winst-name-transitie (BULLISH_REFLEX -> LP_MODE) een NIEUWE LP-positie
proberen te openen MIDDENIN de nog actieve verdedigingsperiode --
precies de volatiliteit vermijden die de verdediging beoogde. OPGELOST:
binnen _execute_transition()'s LP_MODE-tak, als flash-verdediging nog
actief is, wordt het heropenen uitgesteld (kapitaal blijft in HBAR/USDC,
_safetynet_attempted wordt gereset zodat het vangnet het later
vanzelf oppakt), met een duidelijke Telegram-melding.

Alle drie bugfixes geverifieerd op zowel syntax (ast.parse) als
daadwerkelijke instantiatie (RegimeOrchestrator(nep_db) aangeroepen,
bevestigd geen crash) -- de les van de __init__-bug (syntax-check alleen
is onvoldoende) consequent toegepast.

## Dagelijks statusrapport naar Telegram (29 aug 2026)

Op verzoek: elke dag om 09:00 een statusbericht met wallet-saldo (HBAR +
SAUCE, met USD-waarde) en de samenstelling + waarde van de actieve
LP-positie.

**Nieuwe wiskunde, zelf afgeleid en geverifieerd:** lp_manager.py kreeg
tick_to_price() en compute_position_amounts() -- standaard Uniswap-V3-
liquiditeitswiskunde om te berekenen hoeveel token0/token1 een BESTAANDE
positie op dit moment bevat, gegeven liquidity/tick_lower/tick_upper/
huidige prijs. Geverifieerd via sympy (grensgevallen op P=Pa/P=Pb geven
correct 0 terug) en functioneel getest met de daadwerkelijke, echte
liquidity-waarde van vandaag (107986448226) -- eerste testpoging met
VEROUDERDE tick-waarden (-8160/-5160, van vroeg vandaag, vóór talloze
herbalanceringen) gaf onzinnige resultaten; met realistische, actuele
ticks (rond -72648/-71066) gedroeg de functie zich correct in alle drie
scenario's (onder/binnen/boven de range).

**Bevestigd, terzijde:** WHBAR is daadwerkelijk token0 (8 dec), SAUCE
token1 (6 dec) voor dit specifieke pool-adres -- geverifieerd via de
daadwerkelijke, numerieke EVM-adresvergelijking (WHBAR-adres < SAUCE-
adres), niet zomaar aangenomen.

**Nieuwe bestanden:**
- daily_status_report.py: haalt wallet-saldo, LP-positie-samenstelling
  en actuele HBAR-prijs op, berekent USD-waarden, stuurt een
  overzichtelijk Telegram-bericht. Functioneel getest met een volledig
  gemockte omgeving (geen echte wallet/DB nodig) -- output klopte intern
  consistent.
- daily_status_cron.sh: cron-wrapper, zelfde patroon als
  recalibrate_cron.sh. Installatie: crontab -e, voeg toe:
  0 9 * * * /root/hbar_bot/daily_status_cron.sh >> /root/hbar_bot/logs/daily_status.log 2>&1

NOG NIET GEINSTALLEERD IN CRONTAB OP DE VPS -- vereist een handmatige
crontab -e-stap door de gebruiker na deployment.

## Dagelijks statusrapport om 09:00 via Telegram (29 aug 2026)

Op verzoek. BLEEK AL GROTENDEELS GEBOUWD te zijn (waarschijnlijk vóór de
laatste /compact, buiten het zichtbare gespreksgeheugen) --
daily_status_report.py en daily_status_cron.sh stonden al klaar. Grondig
nagelopen i.p.v. blind vertrouwd, gezien eerdere ervaring vandaag met
fouten die syntax-checks omzeilden:
- compute_position_amounts() in lp_manager.py: bevestigd correct, enige
  echte, gestandaardiseerde versie (een DUBBELE, zelf-toegevoegde versie
  per ongeluk aangemaakt tijdens het narekenen, EN daarbij per ongeluk
  de eerste regel van de bestaande compute_amount0_for_amount1()-
  signatuur mee verwijderd -- beide fouten gevonden via syntax-check en
  hersteld).
- Alle imports, functiesignaturen, database-methode (get_active_lp_
  position(), sleutels token_id/tick_lower/tick_upper), en adresresolutie
  (resolve_testnet_v2_addresses() -- bevestigd testnet, niet per ongeluk
  mainnet 0.0.4053945) stuk voor stuk geverifieerd.

Rapport bevat: wallet-saldo (native HBAR + SAUCE, met USD-waarde),
waarschuwing bij vastzittende WHBAR (hergebruikt de eerdere check),
samenstelling en waarde van de actieve LP-positie (indien open, anders
duidelijke "geen actieve positie"-melding), en de totale waarde.
SAUCE wordt overal behandeld als ~1 USD (testnet-proxy voor USDC, zelfde
aanname als de rest van de codebase de hele dag al gebruikt).

Draait via cron (NIET als onderdeel van de continu draaiende bot-
container zelf): `docker compose exec -T hbar-bot python3
daily_status_report.py`, elke dag om 09:00. Installatie-instructies
staan in daily_status_cron.sh zelf.

STATUS: bestanden klaar en geverifieerd, NOG NIET gedeployed/crontab
geinstalleerd op de VPS.

## Structurele 50-HBAR-reserve + eenmalige consolidatie (30 aug 2026)

Op verzoek: voortaan STRUCTUREEL minimaal 50 HBAR reserve aanhouden bij
elke toekomstige positie-opening/herbalancering (niet alleen deze ene
keer). MIN_GAS_RESERVE_HBAR verhoogd van 10.0 naar 50.0 in
regime_orchestrator.py -- dit was al een bestaand, elders gebruikt
reserve-mechanisme (_get_swappable_hbar_balance()), nu simpelweg
opgehoogd en herbestempeld van pure gas-buffer naar algemene
operationele veiligheidsreserve. Geverifieerd via daadwerkelijke
instantiatie (orchestrator.MIN_GAS_RESERVE_HBAR == 50.0).

Voor de eenmalige consolidatie zelf (positie 347 sluiten, opnieuw
openen met alle beschikbare kapitaal minus de reserve): BEWUST GEEN
losse open-positie-logica gebouwd (te veel duplicatie-risico van de
GBM/sentiment-logica). In plaats daarvan: close_position_for_
consolidation.py sluit alleen de bestaande positie, waarna een
HERSTART van de bot-container het bestaande vangnet-mechanisme laat
heropenen -- met de nieuwe reserve al actief, via de al-geteste,
live-draaiende route.

TWEE FOUTEN GEVONDEN EN GECORRIGEERD TIJDENS HET BOUWEN (vóór deployment):
1. Eerste versie gebruikte MagicMock() voor de orchestrator's db-
   parameter -- zou _reconcile_lp_position_on_startup() breken (heeft
   ECHTE database-toegang nodig).
2. Vergat aanvankelijk _reconcile_lp_position_on_startup() uberhaupt
   aan te roepen -- LpManager.state.is_open is puur in-memory en
   begint standaard op False, dus zonder deze aanroep zou het script
   ONTERECHT denken dat er geen positie open staat, ook al staat
   positie 347 daadwerkelijk open.

BELANGRIJKE PROCEDURE-STAP: na het draaien van dit script is een
HERSTART van de bot-container vereist (niet slechts wachten) -- de
al-draaiende bot leest zijn eigen lp_manager.state alleen bij het
opstarten opnieuw in, niet doorlopend.

## KRITIEKE BUG: verkeerde prijs-eenheid in GBM-tick-berekening (30 aug 2026)

Gevonden bij het uitzoeken waarom positie 348 (net geopend via het
vangnet) volledig eenzijdig (100% HBAR, 0% SAUCE) bleek te zijn.

**Kernontdekking**: GeckoTerminal's "price_usd" (bv. 0.075) en de pool's
EIGEN, interne SAUCE-per-HBAR-koers (bv. 51,55, rechtstreeks via
slot0()) zijn TWEE COMPLEET VERSCHILLENDE GROOTHEDEN -- empirisch
bevestigd verhouding: ~685x. Dit betekent dat SAUCE (het testnet-token)
NIET ~$1 waard is zoals de hele dag werd aangenomen, maar slechts ~$0,0015.

**De bug**: price_to_tick() heeft de POOL'S EIGEN prijs nodig (via
get_live_pool_price(), die rechtstreeks slot0() bevraagt) om tot een
zinvolle tick te komen -- niet GeckoTerminal's USD-schatting. Van de vijf
plekken waar compute_range_via_gbm() wordt aangeroepen, gebruikten er
DRIE (de vangnet-route in _cycle(), en de LP_MODE-heropeningstak in
_execute_transition(), inclusief de bijbehorende _ensure_balanced_
liquidity_ratio()-aanroepen) de foutieve current_price (GeckoTerminal)
in plaats van fresh_price (via get_live_pool_price()) -- de andere twee
(_rebalance_if_out_of_range(), en de tweede/verse herberekening vlak
voor het minten) waren AL correct.

**Waarom positie 347 (van vóór vandaag) wel klopte**: die werd geopend
via de oudere, reeds-langer-bestaande compute_range()-route, die AL
langer correct get_live_pool_price() gebruikte.

**OPGELOST**: alle drie foutieve locaties gecorrigeerd naar fresh_price
(via get_live_pool_price(), zelfde patroon als de twee al-correcte
locaties). Geverifieerd op syntax EN daadwerkelijke instantiatie.

**NOG OPEN, VOOR EEN VOLGENDE SESSIE**:
1. Positie 348 zelf staat nog met de VERKEERDE range open (voor deze fix
   geopend) -- moet handmatig gesloten en opnieuw geopend worden met de
   gecorrigeerde code.
2. GROTER, NOG NIET AANGEPAKT probleem: overal waar de codebase SAUCE als
   ~$1 behandelt voor USD-waardeberekeningen (daily_status_report.py,
   evaluate_reflex_transition_economics()'s fee/IL-schattingen, alle
   eerdere backtests van vandaag) is dit AANTOONBAAR ONJUIST -- SAUCE is
   in werkelijkheid ~$0,0015 waard (afgeleid: hbar_price_usd /
   pool_sauce_per_hbar_koers). Dit beinvloedt VEEL meer dan alleen de
   tick-berekening, maar is NIET meer binnen deze sessie hersteld.

## LET OP -- verplicht te herzien bij mainnet-migratie (USDC i.p.v. SAUCE)

Belangrijke notitie voor de mainnet-overstap: de SAUCE-als-~$1-aanname
(zie hierboven, "KRITIEKE BUG: verkeerde prijs-eenheid") is een
TESTNET-SPECIFIEK probleem. Zodra de pool wordt vervangen door de
ECHTE HBAR/USDC-pool op mainnet, vervalt dit specifieke euvel
grotendeels vanzelf -- USDC is namelijk wel degelijk (nagenoeg) $1
waard, in tegenstelling tot het testnet-SAUCE-token.

TOCH EXPLICIET OPNIEUW CONTROLEREN bij die overstap, niet zomaar
aannemen dat het dan vanzelf goed is:
- Bevestig empirisch (net als vandaag gedaan voor SAUCE) dat
  GeckoTerminal's price_usd en de pool's eigen, interne prijs (via
  get_live_pool_price()) op mainnet WEL overeenkomen (of een bekende,
  correcte omrekenfactor hebben) voordat er met echt kapitaal wordt
  gehandeld.
- Alle vandaag gecorrigeerde fresh_price/get_live_pool_price()-fixes
  blijven hoe dan ook correct en nodig (die lossen een structureel,
  niet testnet-specifiek probleem op: GeckoTerminal kan altijd een
  eigen indexerings-vertraging hebben t.o.v. de daadwerkelijke,
  live pool-staat, ongeacht welk token-paar het betreft).
- USDC-decimalen op mainnet zijn 6 (zelfde als de huidige SAUCE-
  aanname) -- waarschijnlijk geen wijziging nodig op dat vlak, maar
  wel expliciet herbevestigen, niet aannemen.

**Aanvulling (30 aug 2026)**: daily_status_report.py leidt nu SAUCE's
werkelijke USD-waarde af via `sauce_price_usd = hbar_price_usd /
pool_price_sauce_per_hbar` (rechtstreeks via get_live_pool_price()) --
dit was NODIG omdat testnet-SAUCE geen 1:1 USD-proxy is. Bij de
mainnet-overstap naar echte USDC wordt deze afgeleide berekening
OVERBODIG (en zelfs VERKEERD als USDC's koers toevallig net niet exact
$1 is door deze formule) -- vervang dit dan gewoon door
`sauce_price_usd = 1.0` (of, voor extra precisie, een echte USDC/USD-
koersbron), in plaats van de pool-ratio-afleiding te blijven gebruiken.

## Automatisch bijstorten van overtollig kapitaal (30 aug 2026)

Op verzoek: zodra er kapitaal bijgestort wordt (of anderszins los in de
wallet komt te staan) terwijl de bot in LP_MODE met een open positie
zit, wordt dat voortaan automatisch de pool in gestort -- in plaats van
te wachten tot de eerstvolgende volledige out-of-range-herbalancering.

- lp_manager.py: nieuwe deploy_additional_capital() -- voegt willekeurig
  wallet-kapitaal toe aan een BESTAANDE positie via increaseLiquidity()
  (hergebruikt hetzelfde multicall-patroon als het al-bestaande
  claim_and_compound(), maar met gegeven bedragen i.p.v. geclaimde fees).
- regime_orchestrator.py: nieuwe _deploy_excess_capital_if_available(),
  aangeroepen elke cyclus, direct na de bestaande out-of-range-check.
  Respecteert de 50-HBAR-reserve (via de bestaande _get_swappable_hbar_
  balance()), een ondergrens (MIN_DEPLOYABLE_CAPITAL_HBAR=10, voorkomt
  triviale gas-kosten), en een eigen cooldown (DEPLOY_CAPITAL_COOLDOWN_
  SECONDS=600s). Hergebruikt de bestaande _ensure_balanced_liquidity_
  ratio() om het overtollige bedrag correct te balanceren vóór het
  bijstorten, en get_live_pool_price() voor de juiste, pool-interne
  prijs (zelfde les als de eerdere kritieke tick-bug van vandaag).

Geverifieerd op syntax EN daadwerkelijke instantiatie (beide nieuwe
instellingen bevestigd correct: 10.0 HBAR, 600.0s).

STATUS: klaar, NOG NIET gedeployed naar de VPS.

## Hysterese/dode-zone voor de gematigde-zone-drempel (30 aug 2026)

Op verzoek, naar aanleiding van een voorgestelde Focused/Balanced/Relaxed-
state-machine-strategie. Onze bestaande drie-standen-indeling (zwak/
gematigd/sterk) kwam al grotendeels overeen met dat voorstel, maar MISTE
een expliciete hysterese-regel -- bij een signaal dat rond
MODERATE_SENTIMENT_THRESHOLD (0.30) schommelde, kon de bot elke cyclus
heen-en-weer wisselen tussen normale en gematigde-zone-breedte, wat
onnodige gas-kosten had kunnen opleveren.

OPGELOST: determine_gbm_confidence_level() -> RegimeOrchestrator.
_determine_gbm_confidence_level() (stateful i.p.v. een losse functie).
Instappen bij MODERATE_SENTIMENT_THRESHOLD=0.30, maar pas uitstappen bij
MODERATE_ZONE_EXIT_THRESHOLD=0.20 (lager) -- tussen deze twee drempels in
blijft de bot in zijn HUIDIGE modus. Nieuwe self._in_moderate_zone-vlag
in __init__. Alle vijf aanroeplocaties bijgewerkt. Functioneel getest met
een schommelend signaal (0.15->0.31->0.29->0.32->0.25->0.22->0.18) --
bevestigd: blijft correct in gematigde modus tot het signaal duidelijk
onder de uitstapdrempel zakt, geen enkel "stuiteren".

De oude, stateloze functie is bewust BEHOUDEN onder een nieuwe naam
(determine_gbm_confidence_level_stateless()) voor eventueel losstaand
gebruik/tests, maar de live bot gebruikt nu uitsluitend de nieuwe,
stateful methode.

**Nog NIET meegenomen uit het bredere voorstel** (bewust, gezien de
sessie al zeer omvangrijk is):
- Een expliciete "Focused" (ultra-strakke, ±0.5-1%) modus als APARTE
  staat -- onze huidige GBM-breedte schaalt al continu met volatiliteit,
  dus bij lage sigma wordt de range al vanzelf smal, maar niet als
  EXPLICIETE, aparte state met eigen drempels.
- Hysterese op REGIME_THRESHOLD (0.55, voor volledig uitstappen) zelf --
  heeft al andere beschermingen (economische poort, regime-cooldown),
  maar geen EXPLICIETE dode-zone zoals nu bij de gematigde-zone-drempel.
- De volledige LVR-gebaseerde beslissingsmatrix als expliciet triggermechanisme
  (LVR-wiskunde staat al klaar van eerder vandaag, discrete formule
  geverifieerd, maar nog niet gekoppeld aan een live state-transitie).

## Twee zaken deze ronde: RPC-belasting-onderzoek + LP-strategievoorstel (30 aug 2026)

### 1. Onderzoek naar mogelijk zelf-veroorzaakte RPC-belasting

Op verzoek: uitgegaan van "het ligt aan de code, niet aan hashio.io".
GEVONDEN, ECHTE BUG: _get_swappable_hbar_balance() en _get_swappable_
usdc_balance() deden ELKE keer een verse RPC-aanroep, zonder enige
caching -- en werden MEERDERE keren per cyclus aangeroepen (rebalance-
check, de vandaag eerder toegevoegde kapitaal-bijstort-check, etc.).
De nieuwe kapitaal-bijstort-functie verdubbelde deze belasting nog eens
extra.

OPGELOST: korte TTL-cache (5 seconden) toegevoegd aan beide functies.
BELANGRIJKE, MEEGENOMEN CORRECTIE: de cache wordt expliciet ongeldig
gemaakt na elke succesvolle swap (in _run_swap_and_log(), de gedeelde
swap-functie) -- anders zou een her-lezing vlak na een swap (bv. binnen
_deploy_excess_capital_if_available(), na _ensure_balanced_liquidity_
ratio()'s eigen swap) een VEROUDERDE waarde kunnen teruggeven, wat
opnieuw een INSUFFICIENT_TOKEN_BALANCE-fout had kunnen veroorzaken.

EERLIJKE KANTTEKENING: dit lost een REELE, gevonden inefficiëntie op,
maar bewijst niet met zekerheid dat dit de ENIGE of zelfs de
HOOFDoorzaak was van de eerdere 502-fouten -- een directe curl-check
bevestigde destijds ook dat hashio.io zelf op dat moment een 502 gaf.
Waarschijnlijk allebei tegelijk een rol: onze eigen, licht overmatige
belasting EN een reeds-kwetsbare externe relay.

Geverifieerd op syntax EN daadwerkelijke instantiatie.

### 2. Expliciet Focused/Balanced/Relaxed-LP-strategievoorstel

lp_strategy_state_machine.py (nieuw): formaliseert onze bestaande zwak/
gematigd/sterk-indeling onder de voorgestelde namen, MET hysterese op
BEIDE overgangen (niet alleen de gematigde-zone-drempel van eerder
vandaag). Relaxed-drempels EXACT zoals voorgesteld (instappen >0.60,
uitstappen <0.45). Focused-drempels analoog (instappen <0.15,
uitstappen >0.25) -- AANNAME, geen empirisch geijkte waarde.

Functioneel getest: hysterese op beide grenzen bevestigd correct (geen
stuiteren bij een schommelend signaal rond 0.60/0.45 EN rond 0.15/0.25),
en de Balanced-scheefstand volgt correct sentiment_mu.

STATUS: dit is een LOSSTAANDE, GETESTE module -- BEWUST NOG NIET
gekoppeld aan de live bot. De bot gebruikt op dit moment nog steeds de
eerdere, functioneel vergelijkbare drie-standen-indeling
(_determine_gbm_confidence_level() in regime_orchestrator.py, met
hysterese op de gematigde-zone-drempel alleen). Wiring van dit nieuwe,
explicietere model (of vervanging van het bestaande) is een aparte,
nog te nemen beslissing voor een volgende sessie.

## KRITIEK: automatisch-bijstorten veroorzaakte een herhaal-loop (30 aug 2026)

De net-gebouwde _deploy_excess_capital_if_available() bleek in de
praktijk een herhaal-loop te veroorzaken -- elke cyclus (elke ~60s)
probeerde de bot een absurd groot, onrealistisch swap-bedrag (bv.
104.630 SAUCE, terwijl de wallet er maar ~19.617 had), wat telkens
mislukte met "INSUFFICIENT_TOKEN_BALANCE" (contract-revert). Elke
mislukte poging kost gas, dus dit had significant, doelloos kapitaal
kunnen opeten als het langer had doorgelopen.

ONDERZOCHT: alle vier aanroepen van _ensure_balanced_liquidity_ratio()
bleken al correct fresh_price (pool-schaal) te gebruiken, niet de
eerder-gevonden current_price-bug van vandaag -- de exacte oorzaak van
dit specifieke, absurde swap-bedrag is dus NOG NIET gevonden. Mogelijk
een cumulatief effect van herhaalde, deels-geslaagde eerdere pogingen
die de wallet-samenstelling steeds verder uit balans brachten, of een
aparte rekenfout in de excess_hbar_needed/usdc_to_swap-berekening zelf.

VEILIGHEIDSMAATREGEL GENOMEN: _deploy_excess_capital_if_available()
TIJDELIJK UITGESCHAKELD (de aanroep in _cycle() is uitgecommentarieerd,
de functie zelf blijft bestaan voor later hergebruik na een grondiger
onderzoek). De bot draait weer veilig verder ZONDER deze specifieke,
nieuwe functionaliteit, tot dit apart, rustig is uitgezocht en beter
getest (bv. met expliciete, stap-voor-stap-logging van elke
tussenwaarde in de berekening, niet alleen het eindresultaat).

Bot was tussentijds handmatig gestopt (docker compose stop hbar-bot) op
verzoek van de gebruiker, positie 349 en kapitaal bevestigd ongewijzigd/
veilig gebleven tijdens de stop.

## Externe feedback verwerkt (30 aug 2026)

Waardevolle, gerichte feedback ontvangen op de architectuur van vandaag.
Vier punten, twee direct gebouwd, een onderzocht (geen sluitend
antwoord), een bewust nog open gelaten.

### Punt 4 (bijstort-bug) -- onderzocht, geen sluitend antwoord
Twee hypotheses getest (gas-reservering, prijsverschuiving-tijdens-
transactie) tegen _ensure_balanced_liquidity_ratio()'s daadwerkelijke
formule, met realistische waarden. Zelfs in het meest extreme geval
(0 beschikbare HBAR) kwam de berekening uit op ~8.049 SAUCE, ver onder
de daadwerkelijk waargenomen 104.630 -- voor dat bedrag zou de wallet
~255.000 SAUCE moeten hebben bevat, wat nergens is waargenomen. Geen
sluitende verklaring gevonden; de functie blijft daarom terecht
uitgeschakeld.

### Punt 1 (trage flash-detectie) -- GEBOUWD
Nieuwe, snelle prijs-gebaseerde flash-detectie TOEGEVOEGD aan de
60-seconden-hoofdcyclus zelf (naast de bestaande, langzamere sentiment-
gebaseerde detectie elke 5 minuten). Vergelijkt de prijs met die van de
vorige cyclus; bij een beweging >3% binnen 60s (AANNAME, geen
empirisch geijkte waarde) wordt DIRECT dezelfde _trigger_flash_defense()
aangeroepen als bij een sentiment-sprong. Hergebruikt de bestaande
FlashEventResult-dataclass (i.p.v. een ad-hoc object) voor consistentie.
_trigger_flash_defense()'s Telegram-bericht aangepast zodat het correct
leesbaar blijft bij BEIDE triggertypes (sentiment EN prijs).

### Punt 3 (GBM onderschat fat tails) -- GEBOUWD
15%-extra-marge (AANNAME, exact zoals voorgesteld) toegevoegd aan de
ONDERKANT van elke GBM-berekende range, in compute_gbm_confidence_
interval(). Wiskundig geverifieerd: de verhouding tussen lower_price
met en zonder de buffer is EXACT 0.85 (15% lager), zowel via de
functie zelf als een onafhankelijke, handmatige herberekening.

### Punt 2 (LLM-confidence onbetrouwbaar, bron-consensus als alternatief)
-- BEWUST NOG NIET GEBOUWD. Vereist het herkennen/groeperen van
MEERDERE, verschillende bronnen die over hetzelfde onderwerp berichten
(deduplicatie/clustering van headlines), een aanzienlijk grotere
architecturale wijziging dan de andere drie punten. Goed idee voor een
aparte, volgende sessie.

Beide gebouwde stukken geverifieerd op syntax EN (waar van toepassing)
daadwerkelijke instantiatie/functionele test.

## Verder onderzoek naar de bijstort-bug + diagnostische logging (30 aug 2026)

Vervolgonderzoek op de eerder gevonden, onverklaarde herhaal-loop.
Twee nieuwe hypotheses systematisch getest, GEEN VAN BEIDE bevestigd:
- Grenswaarden-tests over vijf verschillende tick-range-scenario's
  (exact rond de prijs, ver erboven/eronder, zeer smal, zeer breed) x
  drie bedragen -- geen enkel scenario gaf een absurd resultaat, max
  ~580 HBAR nodig in het meest extreme geval.
- Decimalen-mismatch-hypothese (base.usdc_decimals zou 18 kunnen zijn
  i.p.v. 6 op testnet, per een bestaande code-comment) -- empirisch
  gecontroleerd: in de huidige configuratie is dit correct 6, en
  base.usdc wijst naar HETZELFDE adres als het los-hardcoded SAUCE-
  adres elders. Geen mismatch gevonden.

Gezien het exacte scenario ondanks meerdere pogingen niet te
reproduceren blijkt: UITGEBREIDE DIAGNOSTISCHE LOGGING toegevoegd aan
_ensure_balanced_liquidity_ratio() zelf (print van elke tussenwaarde:
hbar_raw, usdc_raw, needed_usdc_for_full_hbar, needed_hbar_for_full_usdc,
excess-bedragen, uiteindelijk swap-bedrag) -- dit verandert niets aan
het gedrag, maar zorgt dat een eventuele VOLGENDE, vergelijkbare
storing wel volledig te herleiden is. Actief voor ALLE aanroepen van
deze functie, dus ook de al-actieve herbalancerings-route (niet alleen
de nog-uitgeschakelde bijstort-functie) -- geeft dus ook doorlopend
extra inzicht in de reeds actieve code.

Geverifieerd op syntax EN daadwerkelijke instantiatie.

## Bijstort-functie weer aangezet, met veiligheidsklem (30 aug 2026)

Op verzoek -- belangrijk voor mainnet, waar de wallet 100% exclusief
door de bot gebruikt wordt, dus automatisch reageren op bijstortingen
is functioneel belangrijk.

TOEGEVOEGD vóór het heractiveren: harde veiligheidsklem in BEIDE
richtingen van _ensure_balanced_liquidity_ratio() -- ongeacht welke
berekening tot een swap-bedrag leidt, wordt NOOIT meer geswapt dan de
daadwerkelijke, actuele balans (met 5% marge voor afronding/gas). Bij
een berekend bedrag dat de balans overschrijdt: swap NIET uitvoeren,
duidelijke Telegram-melding sturen ("balanceringsklem geactiveerd"),
en de [balans-diagnose]-logs (eerder vandaag toegevoegd) geven de
volledige context. Dit voorkomt een HERHALING van de eerdere loop,
ook zonder de exacte, onderliggende rekenfout te kennen.

_deploy_excess_capital_if_available() weer actief aangeroepen in
_cycle() (niet langer uitgecommentarieerd).

Geverifieerd op syntax EN daadwerkelijke instantiatie.

AANBEVOLEN VOLGENDE STAP: klein, gecontroleerd testen door een
bescheiden bedrag HBAR naar de wallet te sturen en de logs (nu met
volledige [balans-diagnose]-details) op te volgen.

## Vervolgprobleem gevonden en opgelost: klem werkte, maar aanroeper negeerde het (30 aug 2026)

Na het heractiveren van de bijstort-functie: de nieuwe veiligheidsklem
WERKTE correct (blokkeerde een berekend bedrag van 107.230 SAUCE tegen
een balans van 19.617) -- maar de aanroepende functie ging DAARNA toch
door met de daadwerkelijke storting, met de balans die nog steeds niet
gebalanceerd was, wat een TWEEDE fout gaf (INSUFFICIENT_TOKEN_BALANCE).

OORZAAK: _ensure_balanced_liquidity_ratio() gaf altijd None terug
(geen retourwaarde), dus de aanroeper kon niet weten of het balanceren
daadwerkelijk was gelukt of door de klem was tegengehouden.

OPGELOST: functie retourneert nu bool (True = gelukt of niet nodig,
False = klem geactiveerd). ALLE VIER aanroeplocaties bijgewerkt om dit
te controleren en correct af te breken bij False:
1. _deploy_excess_capital_if_available() -- nieuwe check, breekt af
2. _rebalance_if_out_of_range() -- nieuwe check, stuurt een duidelijke
   Telegram-melding en breekt af i.p.v. door te gaan met heropenen
3. Het vangnet in _cycle() -- swap_success was HARDCODED op True,
   genegeerd de daadwerkelijke uitkomst; nu gebaseerd op de echte
   retourwaarde (de bestaande "if swap_success:"-check verderop werkt
   hierdoor nu ook daadwerkelijk zoals bedoeld)
4. De LP_MODE-heropeningstak in _execute_transition() -- all_succeeded
   was OOK hardcoded op True, zelfde fix toegepast

Geverifieerd op syntax EN daadwerkelijke instantiatie. Bevestigd: geen
enkele aanroep van _ensure_balanced_liquidity_ratio() laat de
retourwaarde meer ongebruikt liggen.

## DOORBRAAK: de oorzaak van de bijstort-loop eindelijk gevonden (30 aug 2026)

Dankzij de eerder toegevoegde [balans-diagnose]-logging: volledige
tussenwaarden verkregen tijdens een daadwerkelijke, live herhaling.

BEVINDING: dit is GEEN rekenfout. Empirisch bevestigd via tick_to_price():
positie 349's range [-6900,-6420] komt overeen met prijs [50,1593,
52,6256]. De daadwerkelijke, actuele prijs (50,3402) stond op dat
moment op slechts 7,33% IN die range -- vlak bij de ONDERKANT. Bij
geconcentreerde liquiditeit (Uniswap V3) vereist het toevoegen van
NIEUWE, proportionele liquiditeit dicht bij de rand van een smalle
range een extreem scheve token0:token1-verhouding -- dit is een
fundamenteel, correct wiskundig gevolg van hoe V3-liquiditeit werkt,
geen bug in onze formules. De eerder toegevoegde veiligheidsklem deed
dus PRECIES het juiste door te weigeren.

HET ECHTE PROBLEEM zat in wat er NA de klem gebeurde: de aanroeper gaf
teveel om deze (normale, verwachte) situatie -- stuurde een
alarmerende "HANDMATIGE CONTROLE"-Telegram-melding EN (vóór de
eerdere fix van vandaag) probeerde alsnog door te gaan met storten.

OPGELOST (verfijning van de eerdere klem-fix):
- Beide klem-locaties in _ensure_balanced_liquidity_ratio() sturen niet
  langer een alarmerende telegram_notify.report_error() -- alleen nog
  een stille [balans-diagnose]-logregel, met duidelijke uitleg dat dit
  waarschijnlijk komt doordat de prijs dicht bij de rand van de huidige
  range staat.
- In combinatie met de eerdere fix (aanroeper respecteert nu de
  retourwaarde en breekt correct af): er wordt in dit scenario GEEN
  ENKELE on-chain transactie meer geprobeerd -- dus ook geen sluipende
  gaskosten meer per cyclus, alleen een stille logregel.
- Het overtollige kapitaal wacht nu gewoon op de eerstvolgende,
  natuurlijke out-of-range-herbalancering, die een NIEUWE, beter
  gecentreerde range kiest (waar deze extreme verhouding zich niet
  meer voordoet).

Geverifieerd op syntax EN daadwerkelijke instantiatie.

## Drie openstaande punten afgerond (30 aug 2026)

### 1. Dagelijks 09:00-rapport: crontab geinstalleerd
Non-interactief toegevoegd (via `(crontab -l | grep -v ...; echo ...) |
crontab -`, i.p.v. het interactieve `crontab -e`). Bevestigd via
crontab -l: de volledige regel staat correct in de crontab, naast de
al-bestaande andere geplande taken (IBKR-strategie, VIX-rider, etc.).

### 2. Hysterese op REGIME_THRESHOLD (0.55) toegevoegd
_determine_target_regime() gebruikt nu self.current_regime ZELF als
geheugen (geen nieuwe status-variabele nodig) -- instappen in een
reflex-regime bij REGIME_THRESHOLD (0.55), maar pas terug naar lp_mode
bij de lagere REGIME_THRESHOLD_EXIT (0.40). Functioneel getest met een
correcte, SEQUENTIELE simulatie (current_regime daadwerkelijk bijgewerkt
tussen aanroepen, niet kunstmatig vastgezet) -- bevestigd: blijft
correct in bullish_reflex tot 0.39, blijft daarna correct in lp_mode
bij 0.42 en 0.50 (beide onder de instapdrempel), stapt pas weer in bij
0.56.

### 3. flash_defense_until gepersisteerd
bot_regime_state uitgebreid met een flash_defense_until-kolom (DB-
migratie vereist, zie hieronder). save_regime_state()/get_regime_state()
uitgebreid. TWEE plekken slaan nu op: de bestaande, algemene save-
locatie (na elke geslaagde overgang) EN een NIEUWE, EXPLICIETE
save-aanroep binnen _trigger_flash_defense() zelf (die niet via het
normale overgangs-pad loopt). Bij het opstarten: als de opgeslagen
waarde nog in de toekomst ligt, wordt de verdedigingsperiode hersteld
mét een Telegram-bevestiging.

Alle drie geverifieerd op syntax EN (waar van toepassing) daadwerkelijke
instantiatie/functionele test.

**VEREISTE DATABASE-MIGRATIE** (zelfde patroon als eerder vandaag bij
volatility_sigma) -- moet HANDMATIG gedraaid worden op de bestaande,
live database vóór het deployen van deze code:
```sql
ALTER TABLE bot_regime_state ADD COLUMN IF NOT EXISTS flash_defense_until DOUBLE PRECISION DEFAULT 0.0;
```

### Nog steeds open (grotere stukken, apart aan te pakken)
- LP-strategie-state-machine daadwerkelijk aan de live bot koppelen
- Mean-reversion-detectie aan een echte actie koppelen
- Continue LVR-formule verifiëren
- Bron-consensus-confidence (bewust, te grote wijziging)

## Continue LVR-formule alsnog volledig geverifieerd (30 aug 2026)

De eerdere "niet geverifieerd"-status (28 aug 2026) bleek een fout in
de VERIFICATIEPOGING zelf te zijn, niet in de formule: destijds werd
de tweede afgeleide van een LOSSE reserve (d²x/dP²) berekend, terwijl
Gamma in de LVR-literatuur specifiek de tweede afgeleide van de TOTALE
POOLWAARDE betekent (analoog aan een optie-Gamma).

Correct afgeleid met sympy: V(P) = 2*L*sqrt(P) (poolwaarde-functie),
Gamma = d²V/dP² = -L/(2*P^1.5), verlies-snelheid via het standaard
Ito/optie-Greeks-resultaat (-0.5*sigma^2*P^2*Gamma) = exact
0.25*sigma^2*L*sqrt(P) -- identiek aan de bestaande formule, verschil
geverifieerd als 0.

EXTRA cross-validatie: de discrete formule (al eerder bevestigd)
Taylor-ontwikkeld rond een kleine prijsverandering, met E[eps^2]=
sigma^2*dt (GBM-variantie) ingevuld -- komt EXACT overeen met de
continue snelheid * dt. Beide formules dus nu onafhankelijk,
dubbel bevestigd consistent met elkaar.

STATUS GEWIJZIGD: compute_continuous_lvr_rate() mag nu WEL gebruikt
worden voor besluitvorming (was eerder expliciet afgeraden). Nog
steeds NIET gekoppeld aan een live actie -- dat blijft een aparte,
volgende stap.

## Mean-reversion gekoppeld aan een conservatieve, echte actie (30 aug 2026)

In plaats van de complexere, oorspronkelijk voorgestelde "strakke
positie net boven de gecrashte prijs"-strategie (een geheel nieuwe
positie-plaatsingslogica, meer risico) -- een VEEL conservatievere,
veiligere actie gekozen: als mean-reversion wordt gedetecteerd TIJDENS
een actieve flash-verdedigingsperiode, wordt die periode gewoon
VROEGTIJDIG beeindigd (i.p.v. de volledige 30 minuten uit te zitten),
zodat de bot sneller weer normaal (LP_MODE) kan hervatten als de piek
een overreactie bleek.

- regime_orchestrator.py: twee nieuwe dicts (_mean_reversion_pre_event_
  score, _mean_reversion_event_score, per asset) leggen bij elke
  gedetecteerde flash-event de scores vlak-voor en tijdens vast.
- Bij elke daaropvolgende sentiment-verversing, ZOLANG de
  verdedigingsperiode nog loopt: detect_mean_reversion() aangeroepen.
  Bij bevestiging: periode direct beeindigd, gepersisteerde status
  ONMIDDELLIJK bijgewerkt (voorkomt dat een herstart vlak erna de oude,
  inmiddels-stale waarde zou herstellen), duidelijke Telegram-melding.

Geverifieerd op syntax EN daadwerkelijke instantiatie.

## LP-strategie-state-machine: BEWUST NIET GEKOPPELD (30 aug 2026)

Na overweging: het koppelen van lp_strategy_state_machine.py (expliciete
Focused/Balanced/Relaxed, volatiliteit-gedreven) aan de live bot zou
NAAST het al-bestaande, al-werkende hysterese-systeem
(_determine_gbm_confidence_level(), sentiment-gedreven) komen te
draaien -- twee PARALLELLE, deels-overlappende classificatiesystemen op
verschillende signalen (volatiliteit vs. sentiment). Het risico op
verwarrende, elkaar tegensprekende beslissingen of subtiele
integratiebugs (gezien hoeveel van dat soort bugs vandaag al zijn
gevonden in vergelijkbare, minder complexe wijzigingen) weegt op dit
moment zwaarder dan de meerwaarde. BEWUST uitgesteld tot een aparte,
toegewijde sessie die zich puur op deze ene integratie kan richten --
niet in dezelfde sessie als de rest van vandaag.

## Live pool-APR toegevoegd -- stap 1: informatief, nog geen beslissing (30 aug 2026)

Op verzoek: kan de bot strategie bepalen op basis van de huidige,
daadwerkelijke APR van de pool? Bevinding: compute_fees_apr() (correcte
implementatie van SaucerSwap's eigen formule) bestond al, maar de
docstring vermeldde EXPLICIET dat er nog geen bevestigde bron voor
volume_24h gevonden was.

GEVONDEN: GeckoTerminal's PoolSnapshot (die elke cyclus AL wordt
opgehaald voor de prijs) bevat ALLEBEI de benodigde velden
(volume_24h_usd EN liquidity_usd) -- deze werden voorheen genegeerd
(alleen .price_usd werd gebruikt). Dit vult het eerder-openstaande gat
volledig, ZONDER extra API-aanroep nodig te hebben.

GEBOUWD (bewust, stapsgewijs -- eerst alleen berekenen/loggen, NOG NIET
aan een beslissing koppelen): elke cyclus wordt nu een live, gemiddelde
pool-APR berekend en gelogd (self._cached_pool_fees_apr). Gebruikt de
pool's TOTALE liquiditeit als l_bal (SaucerSwap's eigen, gedocumenteerde
vereenvoudiging) -- geeft dus het POOL-GEMIDDELDE, niet specifiek onze
eigen, geconcentreerde positie (die doorgaans hoger ligt).

Geverifieerd op syntax, daadwerkelijke instantiatie, EN de onderliggende
compute_fees_apr()-formule zelf met realistische waarden (hoger volume
geeft correct een hogere APR).

VOLGENDE STAP (nog niet gedaan): deze live APR daadwerkelijk als signaal
meewegen in de strategiekeuze (bv. hoge APR -> pleit voor Focused/
strakke range, lage APR -> minder reden om strak te zitten) -- bewust
apart gehouden van deze eerste, veilige, informatieve stap.

## STARTPUNT VOLGENDE SESSIE: multi-positie-ondersteuning + tranche-strategie (30 aug 2026)

Belangrijk, extern aangeleverd inzicht dat de bijstort-problematiek van
vandaag verklaart en oplost -- vastgelegd als concreet startpunt voor
een aparte, toegewijde sessie (bewust NIET vanavond gebouwd, gezien de
omvang van de benodigde architectuurwijziging).

### Het kerninzicht: "tranches" i.p.v. de bestaande positie forceren

Vandaag ontdekten we (via [balans-diagnose]-logging): het bijstorten
van kapitaal in een BESTAANDE, smalle positie kan een onrealistische
swap-ratio vereisen zodra de prijs dicht bij de rand van die positie's
range staat (empirisch: prijs op 7,33% in de range gaf een benodigde
swap van 107x de beschikbare balans). Dit is GEEN bug, maar een
fundamenteel gevolg van geconcentreerde-liquiditeit-wiskunde.

DE OPLOSSING (aangeleverd voorbeeld, "Strategie B"): in plaats van de
bestaande positie te forceren via increaseLiquidity() (die de EXACTE
ratio van de bestaande, mogelijk scheve range moet matchen), open je
een NIEUWE, aparte NFT-positie met een VERS, gecentreerd bereik rond de
HUIDIGE prijs (via de al-bestaande, al-geteste open_position()/
compute_range_via_gbm()-machinerie). Dit omzeilt het ratio-probleem
volledig, en is bovendien veel goedkoper (rekenvoorbeeld 3: $0,15
swap-kosten voor een tranche vs. $6,00 voor het forceren van de
bestaande positie -- 40x goedkoper).

### Waarom dit een grote wijziging is (niet een kleine patch)

De VOLLEDIGE codebase is gebouwd rond precies EEN positie tegelijk:
- lp_manager.state (token_id, tick_lower, tick_upper, is_open) --
  enkelvoudig
- active_lp_position-databasetabel -- enkelvoudig (1 rij max)
- Elke herbalancerings-/vangnet-/rapportage-functie neemt aan dat er
  hooguit een positie is

Voor ECHTE multi-positie-ondersteuning moet dit overal aangepast worden
naar een LIJST van posities, inclusief:
- Database-schema (active_lp_position -> meerdere rijen toestaan)
- Rapportage (daily_status_report.py -- som over alle posities)
- Herbalancering: WELKE positie(s) herbalanceren bij out-of-range?
  Blijven tranches apart bestaan, of worden ze op enig moment
  samengevoegd tot een enkele, nieuwe positie?
- Sluiten (bv. bij flash-verdediging): ALLE posities moeten dan sluiten,
  niet slechts een
- Vangnet-logica: wat betekent "geen positie open" nog in een multi-
  positie-wereld?

### Drie rekenvoorbeeld-scenario's (aangeleverd, ter referentie voor de
volgende sessie -- bevestigen de bestaande economische-poort-logica en
motiveren de tranche-aanpak):
1. Focused-herbalancering: $12 kosten vs. $35,62/dag extra baten ->
   terugverdientijd 8 uur (bevestigt de bestaande economische-poort-
   aanpak, geen wijziging nodig)
2. Relaxed-verdediging: hoge APR (300%) tijdens een crash kan ONDANKS
   de aantrekkelijke fee-inkomsten alsnog een NETTO verlies betekenen
   door LVR (voorbeeld: +$82 fees, -$250 LVR, netto -$168) -- motiveert
   om LVR expliciet mee te wegen bij toekomstige Relaxed-beslissingen,
   niet puur op APR af te gaan
3. Tranche vs. volledig forceren: $0,15 vs. $6,00 swap-kosten -- de
   directe, cijfermatige onderbouwing voor de tranche-aanpak

### Architectuur-verfijningen (aangeleverde feedback, 30 aug 2026)

Belangrijke aanvullingen op het tranche-plan hierboven, om fragmentatie
en oncontroleerbare kosten te voorkomen:
- **Database-schema**: active_lp_position uitbreiden met is_primary
  (boolean) en parent_regime_id, i.p.v. simpelweg meerdere losse rijen
  toe te staan zonder onderscheid.
- **MAX_ACTIVE_TRANCHES = 3** (hardcoded limiet) -- bij het bereiken
  daarvan wordt extra kapitaal vastgehouden tot een natuurlijke
  consolidatie, NIET blind een vierde tranche geopend.
- **Lazy consolidation**: nooit puur opruimen omwille van opruimen --
  alleen samenvoegen tot een nieuwe hoofdpositie bij een macro-regime-
  wijziging, of wanneer de prijs buiten de is_primary-positie's range
  valt (dezelfde trigger als de bestaande out-of-range-herbalancering).
  **BELANGRIJKE CORRECTIE (30 aug 2026, op aangeleverde feedback)**: dit
  criterium alleen is een valstrik -- als de prijs wegdrijft van een
  SUB-tranche maar binnen de bredere range van de is_primary-positie
  blijft, merkt de bot dit NIET op (want die kijkt alleen naar de
  hoofdpositie). De sub-tranche wordt dan stilzwijgend 100% eenzijdig,
  stopt met fee-verdienen, en lijdt onopgemerkt impermanent loss.
  _rebalance_if_out_of_range() moet daarom itereren over ALLE actieve
  tranches (niet alleen is_primary) en een individuele, uit-bereik-
  geraakte sub-tranche apart sluiten/herinvesteren, los van de status
  van de hoofdpositie.
- **Flash Defense als loop**: _trigger_flash_defense() moet ALLE actieve
  posities sluiten (for-loop), met een eigen try/except PER positie --
  een mislukking bij positie 2 mag de sluiting van positie 3 niet
  blokkeren.

### Aanbevolen eerste stap voor de volgende sessie
Begin met een VEREENVOUDIGDE versie (niet meteen de volle
architectuur): tranches als aparte, MINIMAAL bijgehouden extra posities
(bv. een simpele lijst van token_id's, apart van de hoofdpositie), die
vooralsnog niet individueel actief beheerd worden (geen eigen
herbalancering per tranche) -- alleen correct meegeteld in rapportage
en meegesloten bij een volledige sluiting (flash-verdediging, etc.).
Volledige, actief beheerde multi-positie-ondersteuning is een grotere
vervolgstap daarna.

## Vervolgprobleem: mislukte balans-ophaal kon bijstorten op verkeerd been zetten (30 aug 2026)

Nieuwe fout gevonden: een 502 tijdens "USDC-balans opvragen" liet die
functie stilzwijgend 0.0 teruggeven (bestaand, algemeen foutafhandelings-
patroon), waarna de bijstort-berekening met deze mogelijk-onjuiste
data doorging en een INSUFFICIENT_TOKEN_BALANCE-fout gaf.

Gezien _get_swappable_hbar_balance()/_get_swappable_usdc_balance() op
19 plekken worden gebruikt -- te riskant om het foutafhandelings-
gedrag daar zelf te wijzigen (bv. een exception laten propageren i.p.v.
0.0 teruggeven) zonder alle 19 aanroepers te moeten narekenen.

OPGELOST met een gerichte, laag-risico vlag i.p.v. een brede wijziging:
nieuwe self._balance_fetch_failed_this_cycle, gereset aan het BEGIN van
elke cyclus, gezet op True in BEIDE balans-functies' except-blokken.
_deploy_excess_capital_if_available() checkt deze vlag vlak vóór de
daadwerkelijke storting, en slaat die cyclus over (met een stille
logregel) als er al een storing was. Andere, bestaande aanroepen van
deze twee functies blijven ongewijzigd -- deze fix raakt uitsluitend
de bijstort-functie.

Geverifieerd op syntax EN daadwerkelijke instantiatie.

## Prijs-orakel-manipulatie-check gebouwd (30 aug 2026)

Op aangeleverde feedback: vergelijkt vóór een mint de RELATIEVE
verandering van de pool's eigen prijs (slot0()) met de RELATIEVE
verandering van GeckoTerminal's prijs, sinds de vorige meting.

BELANGRIJKE CORRECTIE op het letterlijke voorstel: een DIRECTE, absolute
vergelijking (zoals voorgesteld: "IF abs(price_slot0 - price_gecko) >
3%") zou NIET werken, gezien deze twee bronnen op compleet verschillende
schalen staan (SAUCE-per-HBAR ~50 vs. USD ~0,075 -- zie de eerdere,
kritieke bevinding van vandaag over SAUCE die geen 1:1 USD-proxy is).
In plaats daarvan: RELATIEVE verandering sinds de vorige meting
vergeleken, wat wel schaal-onafhankelijk werkt.

Nieuwe methode: _check_price_oracle_divergence(). Functioneel getest met
drie scenario's: eerste meting (geen vergelijkingsmateriaal, correct
True), vergelijkbare beweging in beide bronnen (~2% in beide, correct
True), en een verdachte afwijking (pool +27%, gecko +0,1%, correct
False met een duidelijke Telegram-melding).

Gekoppeld aan de TWEE belangrijkste mint-momenten: het vangnet en de
LP_MODE-heropeningstak in _execute_transition() -- de plekken waar
daadwerkelijk NIEUW kapitaal wordt ingezet. Bewust NIET gekoppeld aan
de out-of-range-herbalancering zelf (die wordt al door een GEDETECTEERDE
prijsbeweging getriggerd, dus een controle daar zou de eigen trigger
tegenspreken).

Geverifieerd op syntax EN daadwerkelijke instantiatie.

## Evaluatie punt 3 (WHBAR-allowance + gas-buffer): reeds afgedekt

- Allowance-reset-in-reconciliatie: functioneel al gedekt -- de bestaande
  opstartvolgorde roept check_and_recover_stuck_whbar() (die de
  allowance intrekt na een unwrap) AL apart aan, direct na
  _reconcile_lp_position_on_startup(). Geen aparte wijziging nodig.
- Gas-limit-buffer (30% boven gemeten gemiddelde): GEVERIFIEERD (30 aug
  2026, na eerder als "waard om te checken" gemarkeerd) -- daadwerkelijk
  gasverbruik van een bevestigde, succesvolle mint-transactie (positie
  349 openen) opgevraagd: 716.938 tegen de ingestelde limiet van
  1.200.000, een marge van 67,4% -- ruim boven de aanbevolen 30%. Geen
  aanpassing nodig.

## Prijs-orakel-check herzien naar TWAP (30 aug 2026, na aangeleverde feedback)

Terechte kritiek op de eerste versie (cross-source: pool vs.
GeckoTerminal): zou bij NORMALE, legitieme block-to-block koers-
bewegingen valse alarmen kunnen geven, vanwege GeckoTerminal's eigen
indexerings-vertraging (tot enkele minuten) t.o.v. de pool's eigen,
onmiddellijke tick-updates.

OPGELOST via de voorgestelde TWAP-aanpak (Uniswap V3's ingebouwde
observe()-orakelfunctie), MET een noodzakelijke, vooraf uitgevoerde
haalbaarheidscheck: Uniswap V3-pools slaan STANDAARD maar 1 historische
waarneming op (cardinaliteit=1), wat een TWAP-aanroep onmogelijk zou
maken tenzij expliciet verhoogd. EMPIRISCH GEVERIFIEERD (via een live
diagnostisch script): onze pool heeft observationCardinality=1000, ruim
voldoende voor een 5-minuten-TWAP.

Nieuwe functies:
- lp_manager.py: get_twap_tick() (nieuw), observe() toegevoegd aan
  POOL_SLOT0_ABI_MINIMAL. BUG GEVONDEN EN GECORRIGEERD tijdens het
  bouwen: een handmatige "correctie" voor negatieve-getallen-afronding
  bleek OVERBODIG en FOUTIEF (Python's // rondt al correct naar beneden
  af) -- direct empirisch geverifieerd met een test-berekening
  (-7 // 2 = -4, correct; mijn eigen extra correctie gaf onterecht -5)
  vóórdat dit gedeployed werd.
- regime_orchestrator.py: _check_price_oracle_divergence() volledig
  herschreven naar tick-vs-TWAP (was: relatieve prijsverandering
  cross-source). Nieuwe drempel PRICE_ORACLE_MAX_TICK_DEVIATION=50
  ticks (~0,5%, exact zoals voorgesteld).

Tijdens het bouwen: een str_replace liet per ongeluk een deel van de
OUDE methode-definitie staan naast de nieuwe (twee overlappende
definities) -- gevonden via een grep-controle vóór het testen, en
gecorrigeerd met een precieze, regelnummer-gebaseerde verwijdering
(i.p.v. nogmaals op tekst te matchen).

VOLLEDIG LIVE GETEST tegen de daadwerkelijke pool (niet alleen
synthetisch): huidige tick en 5-minuten-TWAP-tick kwamen exact overeen
(0 ticks afwijking) onder normale marktomstandigheden -- bevestigt de
hele keten (observe()-aanroep, TWAP-berekening, drempel-vergelijking)
werkt correct zonder valse alarmen.

De oude, cross-source-tracking (_previous_pool_price) is opgeruimd
(overbodig geworden na de omschakeling naar TWAP).

## BELANGRIJKE CORRECTIE: parallelle sessie, 1 sep 2026

Tussen deze sessie (30 aug) en nu is er in een ANDERE chat (buiten dit
gesprek) verder gewerkt aan de bot -- vastgesteld en geverifieerd op
1 sep 2026. Mijn eigen, eerdere aanname dat positie 349 nog actief was,
bleek verouderd.

GEVERIFIEERDE, ACTUELE STAAT (1 sep 2026, rechtstreeks van de VPS):
- **Actieve positie is nu 350** (niet 349 -- 349 is gesloten in de andere
  sessie, om een structureel probleem op te lossen: token 349 was
  geopend tijdens het LOW-volatiliteitsregime en werd nooit herzien
  toen het regime naar HIGH verschoof, waardoor de positie permanent te
  smal bleef).
- **Nieuwe functionaliteit uit de andere sessie, bevestigd LIVE werkend**:
  _regime_drift_check() + evaluate_regime_switch_economics() (in
  lp_manager.py) -- vergelijkt de HUIDIGE positie-breedte met wat GBM nu
  zou voorstellen, en voert bij een substantiële afwijking (>30%) een
  kosten-batenanalyse uit vóór een eventuele overstap. Live bevestigd:
  correct "NIET economisch de moeite waard" gegeven bij een 66%-
  breedteverschil (netto -72,88 HBAR).
- **Al ONS eigen werk van 30 augustus blijft ook aanwezig en functioneel**
  (bevestigd via grep: _check_price_oracle_divergence, get_twap_tick,
  _balance_fetch_failed_this_cycle, etc. -- 11 vermeldingen) -- BEIDE
  sessies' werk bestaat naast elkaar zonder geconstateerd conflict.
- Totale waarde: $101,88 (1 sep), gezond, geen foutmeldingen in de logs.

Zie het volledige overdrachtsdocument (door de gebruiker geplakt, 1 sep)
voor de complete, chronologische toelichting van de andere sessie --
niet hier herhaald, maar wel als geldig, bevestigd te beschouwen.

LES VOOR MEZELF: bij een lange onderbreking tussen sessies, ALTIJD eerst
de daadwerkelijke, actuele staat verifiëren (positie-ID, bestandsdatums,
logs) vóórdat verder gebouwd wordt -- niet blind uitgaan van de laatst
bekende staat uit een eerder gesprek.

## Statusrapport uitgebreid met strategie + range-analyse (1 sep 2026)

Op verzoek: dagelijks statusrapport toont nu ook de huidige strategie
(LP_MODE/BULLISH_REFLEX/BEARISH_REFLEX, via db.get_regime_state()) en
een gezondheidsanalyse van de actieve positie's range.

Nieuwe range-analyse: toont de prijsrange (via tick_to_price()) en het
percentage waar de HUIDIGE prijs binnen die range staat (0%=onderkant,
100%=bovenkant), met een kwalitatief oordeel:
- <0% of >100%: buiten bereik (verdient geen fees)
- <15% of >85%: dicht bij de rand (kwetsbaar)
- overig: gezond gecentreerd

Geverifieerd met de exacte cijfers van eerder vandaag (tick_lower=-6900,
tick_upper=-6420, prijs=50.34) -- berekende 7,33%, EXACT gelijk aan de
eerdere, onafhankelijke handmatige berekening die destijds de
bijstort-balanceringsklem verklaarde.

Geverifieerd op syntax.

## Statusrapport verder uitgebreid: fees, breedte, historische analytics (1 sep 2026)

Op verzoek, drie nieuwe onderdelen aan daily_status_report.py toegevoegd:

### 1. Opgebouwde, nog niet geclaimde fees
Via een GESIMULEERDE collect()-aanroep (.call(), geen echte transactie)
met maximale bedragen -- standaardpatroon om te zien wat er nu geclaimd
zou kunnen worden. collect() toegevoegd aan de lokale ABI in dit bestand
(bestond al in lp_manager.py, niet hier).

### 2. Breedte van de positie (strategie-indicator)
Uitgedrukt als percentage rond de huidige prijs -- zelfde soort getal
als in de bestaande [regime-drift]-logs.

### 3. Historische waarde-analytics (dag/week/maand/jaar)
NIEUWE database-tabel portfolio_value_history (migratie vereist, zie
hieronder) -- een rij per keer dat het rapport draait (dus 1x/dag via
de crontab). NIEUWE functies in postgres_client.py:
save_portfolio_value_snapshot(), get_portfolio_value_at(days_ago) (zoekt
de DICHTSTBIJZIJNDE snapshot, met een tolerantie van de helft van de
gevraagde periode -- voorkomt een misleidende vergelijking als er nog
niet genoeg historie is, bv. een "30d"-vergelijking op basis van een
snapshot van 2 dagen oud).

Elke keer dat het rapport draait: slaat EERST de huidige waarde op,
haalt DAARNA de vergelijkingen op (zodat de eerste run meteen een
startpunt zet voor toekomstige vergelijkingen). Toont alleen periodes
waarvoor voldoende, betrouwbare historie beschikbaar is.

db.close() verplaatst van vroeg in het script naar het einde (was
eerder te vroeg, nu nog nodig voor de snapshot+analytics-aanroepen).

Geverifieerd op syntax (beide bestanden). NIET live getest tegen de
daadwerkelijke database (vereist eerst de migratie hieronder).

**VEREISTE DATABASE-MIGRATIE** (zelfde patroon als eerder):
```sql
CREATE TABLE IF NOT EXISTS portfolio_value_history (
    id SERIAL PRIMARY KEY,
    total_value_usd DOUBLE PRECISION NOT NULL,
    wallet_value_usd DOUBLE PRECISION NOT NULL,
    position_value_usd DOUBLE PRECISION NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_portfolio_value_history_recorded_at
    ON portfolio_value_history (recorded_at);
```

## Inconsistentie gevonden en opgelost: twee breedte-conventies (1 sep 2026)

Bij het draaien van het uitgebreide statusrapport viel op: mijn eigen
"Breedte"-berekening toonde 61,6%, terwijl de [regime-drift]-log
(uit de andere sessie) consistent 30,0% toonde voor DEZELFDE positie.

OORZAAK: twee verschillende formules voor hetzelfde begrip.
- Mijn (oude) formule: VOLLEDIGE breedte t.o.v. de HUIDIGE prijs --
  (boven-onder)/huidige_prijs
- _regime_drift_check()'s formule (de gevestigde conventie): HALVE
  breedte t.o.v. het MIDDEN van de range -- (boven-onder)/(2*midden)

OPGELOST: daily_status_report.py's breedte-berekening aangepast naar
EXACT dezelfde formule als _regime_drift_check() (opgezocht in de
daadwerkelijke, live broncode op de VPS). Geverifieerd met de exacte
cijfers van zonet (prijs_onder=35,2062, prijs_boven=65,3130): nieuwe
berekening geeft exact 30,0%, overeenkomstig de regime-drift-log.

Les: bij het toevoegen van nieuwe rapportage-functionaliteit naast
al-bestaande logica van een andere sessie, ALTIJD eerst de exacte,
gevestigde formules/conventies opzoeken in de broncode zelf, niet
opnieuw uitvinden op basis van een eigen aanname.

## Live webdashboard gebouwd (1 sep 2026)

Op verzoek: het analytics-mockup omgezet naar een echt, aan de database
gekoppeld, continu draaiend dashboard op de VPS. GEEN login (op
uitdrukkelijke wens, "hoeft geen login te hebben nu nog") -- daarom
BEWUST alleen aan 127.0.0.1 gebonden (bereikbaar via SSH-tunnel/lokaal
netwerk, NIET direct vanaf het publieke internet), gezien dit financiele
gegevens toont. Als dit ooit publiek toegankelijk moet worden, is
wachtwoordbeveiliging dan alsnog nodig -- zie ook de eerdere,
uitgebreide discussie over multi-user/wallet-koppeling (bewust apart
gehouden, andere kwestie).

### Nieuwe bestanden
- bot_data.py (NIEUW): gedeelde data-ophaal-logica, geextraheerd uit
  daily_status_report.py zodat het Telegram-rapport en het dashboard
  exact dezelfde, eenmaal-geverifieerde logica gebruiken.
- dashboard_server.py (NIEUW): FastAPI-app. Route "/" rendert het
  volledige dashboard (Jinja2), route "/api/history?days=N" levert
  grafiekdata voor de periode-toggle. Berekent ook de APR-gebaseerde
  projecties (30/90/180 dagen) en de 24u-waardeverandering.
- templates/dashboard.html (NIEUW): de eerder goedgekeurde mockup,
  omgezet naar een Jinja2-sjabloon met echte databinding. Grafiek en
  valuta-toggle nu volledig functioneel met live/server-aangeleverde
  data i.p.v. vaste voorbeeldwaarden.
- postgres_client.py: twee nieuwe functies -- get_portfolio_value_
  history_since(days) (volledige reeks voor de grafiek, i.t.t. get_
  portfolio_value_at() dat maar 1 vergelijkingspunt geeft) en
  get_recent_trades(limit) (voor de transactielijst).
- requirements.txt: fastapi, uvicorn, jinja2 toegevoegd.
- docker-compose.yml: nieuwe "dashboard"-service, hergebruikt dezelfde
  build als de bot (bevat nu ook de nieuwe dependencies), draait
  uvicorn op poort 8000, ALLEEN aan 127.0.0.1 gebonden.

### Geverifieerd
- Syntax van alle nieuwe/aangepaste Python-bestanden
- dashboard_server.py daadwerkelijk GEIMPORTEERD zonder fouten (vangt
  import-time-problemen die syntax-checks alleen niet zouden zien)
- Jinja2-sjabloon: geparsed, EN daadwerkelijk GERENDERD met
  representatieve testdata, EN visueel bevestigd via een screenshot
  (Playwright) -- inclusief een gevonden en gecorrigeerde bug
  (ontbrekende "d." prefix bij een variabele, waardoor "testnet" niet
  verscheen) en een bevestigde, werkende lege-transacties-staat
- NIET live getest tegen de daadwerkelijke database/VPS (kan niet
  vanuit de sandbox) -- dat is de eerstvolgende stap bij deployment

### Bekende, kleinere beperkingen (niet blokkerend)
- EUR-koers is een VASTE, benaderende omrekenfactor (0.923), geen live
  koers -- GeckoTerminal (onze enige prijsbron) geeft alleen USD.
  Nodig: een aparte EUR-koers-bron als dit precies moet kloppen.
- Transactielijst toont alleen swaps uit de trades-tabel, nog geen
  aparte positie-open/close-gebeurtenissen met hun exacte gaskosten
  (die worden nu niet los bijgehouden in een tabel) -- mogelijke latere
  uitbreiding.

## Transactielijst gecorrigeerd: swap-bedrag != kosten (1 sep 2026)

Gevonden na visuele controle van het live dashboard: de transactielijst
toonde absurd grote "kosten" (bv. -45.477 HBAR) -- dit was het VOLLEDIGE
swap-bedrag (amount_in), ten onrechte gelabeld als een kostenpost. Een
swap is geen verlies, alleen een omzetting van het ene token naar het
andere (de waarde blijft, in een andere vorm).

OPGELOST: de daadwerkelijke gasfee wordt nu apart opgevraagd (via de
transactie-ontvangstbevestiging, effectiveGasPrice * gasUsed) en getoond
als de ECHTE kostenpost. Het swap-bedrag zelf staat nu neutraal,
informatief in de omschrijving ("Swap HBAR -> SAUCE (45.477,29 SAUCE)"),
niet meer als rode kostenregel.

Efficientie-overweging bewust meegenomen: gebruikt effectiveGasPrice UIT
de ontvangstbevestiging zelf (standaard EVM-veld) i.p.v. een aparte
get_transaction()-aanroep (halveert het aantal RPC-aanroepen), EN de
RPC-client wordt eenmalig aangemaakt vóór de lus i.p.v. per transactie
(voorheen 30x opnieuw aangemaakt).

Geverifieerd op syntax EN daadwerkelijke, herhaalde import (geen
import-time-fouten).

## Uurlijkse waarde-snapshots voor de grafiek (1 sep 2026)

Op verzoek: de dashboard-grafiek kreeg voorheen maar 1x per dag een
nieuw meetpunt (via daily_status_report.py's cron). Nieuw, licht
script: hourly_snapshot.py -- slaat ELK UUR alleen een snapshot op,
BEWUST GEEN Telegram-bericht (zou spam geven). Hergebruikt
fetch_dashboard_data() (exact dezelfde berekening als het Telegram-
rapport en het dashboard).

Geverifieerd op syntax. Vereist een nieuwe crontab-regel (elk uur):
0 * * * * cd /root/hbar_bot && docker compose exec -T hbar-bot python3 hourly_snapshot.py >> /root/hbar_bot/logs/hourly_snapshot.log 2>&1

## HBAR-koersgrafiek toegevoegd, boven de waardeverandering (1 sep 2026)

Op verzoek: nieuwe grafiek met de HBAR-koers over dezelfde periode,
gepositioneerd boven de bestaande waardeverandering-grafiek, met EEN
gedeelde periode-toggle die beide grafieken tegelijk aanstuurt.

Gebruikt GeckoTerminal's EIGEN, al-bestaande OHLCV-geschiedenis
(get_historical_ohlcv() in geckoterminal_client.py, ontdekt al aanwezig)
i.p.v. dit zelf op te slaan -- geeft echte, langere historie (ook van
vóór we zelf snapshots begonnen op te slaan). Kiest een passend
candle-interval per gevraagde periode (15-minuten voor 24u, 1-uur voor
7d, 4-uur voor 30d, dagelijks voor 1j) zodat een jaar aan data niet
onleesbaar wordt.

Nieuwe endpoint: /api/price-history?days=N. Sjabloon herbouwd met een
herbruikbare maakLijnGrafiek()-JS-functie (i.p.v. gedupliceerde Chart.js-
configuratie) -- prijs-grafiek in een onderscheidend blauw (#8AB4F8,
4 decimalen), waarde-grafiek in het bestaande groen (2 decimalen).

Geverifieerd: Jinja2-syntax, daadwerkelijke rendering, EN visueel
bevestigd via een screenshot (Playwright) met representatieve testdata.

## Lege prijs-grafiek opgelost: GeckoTerminal-snelheidslimiet (1 sep 2026)

Gevonden via de live logs: GeckoTerminal's publieke API gaf 429 Too
Many Requests -- de prijs-grafiek roept dit bij elke paginaherlading en
elke toggle-klik aan, en de snelheidslimiet werd overschreden.

OPGELOST: korte cache (60 seconden, per periode) toegevoegd aan
_build_price_chart_data(). Bij een storing wordt bovendien de LAATST
BEKENDE, gecachete data teruggegeven (ook al net verlopen) i.p.v. een
lege grafiek -- beter licht verouderd dan leeg.

Functioneel getest met een nagemaakte GeckoTerminal-aanroep: bevestigd
dat een tweede aanroep binnen de cache-periode GEEN nieuwe API-aanroep
doet (1 daadwerkelijke aanroep i.p.v. 2), en identieke resultaten geeft.

## "Internal Server Error" bij gelijktijdige toegang opgelost (1 sep 2026)

Gevonden: bij het GELIJKTIJDIG openen van het dashboard op twee
apparaten (mobiel + desktop) crashte de pagina met een onbeveiligde
429-fout van GeckoTerminal, ditmaal bij get_pool_snapshot() (gebruikt
voor de actuele prijs in wallet-/positie-berekeningen) -- een andere
aanroep dan de eerder al beveiligde prijs-grafiek-historie.

OPGELOST OP DE BRON: klasse-brede (niet instantie-eigen) cache
toegevoegd aan GeckoTerminalClient.get_pool_snapshot() zelf, in
geckoterminal_client.py -- dit bestand wordt door ZOWEL de bot ALS het
dashboard ALS het Telegram-rapport gebruikt, en elke aanroeper maakt
een EIGEN instantie aan, dus een instantie-eigen cache zou niet hebben
geholpen. Korte levensduur (15s) -- ruim voldoende om gelijktijdige
aanvragen op te vangen, zonder de bot's eigen, live handelsbeslissingen
merkbaar te vertragen.

Functioneel getest: TWEE aparte, nieuwe GeckoTerminalClient()-instanties
(precies het mobiel+desktop-scenario) -- bevestigd 1 daadwerkelijke
API-aanroep i.p.v. 2, identieke resultaten.

Raakt geckoterminal_client.py, gebruikt door zowel hbar-bot als
dashboard -- BEIDE containers moeten herbouwd worden.

## Kosten-batenberekening gecorrigeerd: mainnet-basislijn -> live testnet-APR (1 sep 2026)

Gevonden na een gerichte vraag ("waarom kost dit 70 HBAR, dat lijkt me
veel"): evaluate_regime_switch_economics() gebruikte impliciet
estimate_fee_apr_for_width()'s DEFAULT, MAINNET-gekalibreerde basislijn
(1,61% bij 15%-breedte) -- terwijl onze bot op TESTNET draait, waar de
pool live gemeten 28-33% APR laat zien. Empirisch aangetoond: met de
mainnet-basislijn wordt zelfs een smalle 11,1%-range geschat op maar
~2,2% APR; met onze eigen, live APR als basislijn springt dat naar
~301% -- de mainnet-aanname onderschatte de fee-opbrengst met een
factor ~40x, wat de kosten-batenanalyse stelselmatig te pessimistisch
maakte over overstappen naar een smallere, efficiëntere range.

OPGELOST:
- lp_manager.py: evaluate_regime_switch_economics() uitgebreid met
  instelbare fee_apr_basislijn/fee_apr_basislijn_breedte-parameters
  (default: de oorspronkelijke mainnet-waarden, voor achterwaartse
  compatibiliteit als ooit zonder override aangeroepen).
- regime_orchestrator.py: _regime_drift_check()'s aanroep geeft nu
  self._cached_pool_fees_apr (de daadwerkelijke, live-gemeten testnet-
  APR, elders in dezelfde cyclus al berekend voor de "Live pool-APR"-
  logregel) door als basislijn, met fee_apr_basislijn_breedte=1.0
  (benadering: de pool-brede APR representeert ruwweg een zeer brede/
  volledige-range-positie).

Bewerking rechtstreeks op de VPS uitgevoerd (i.p.v. via GitHub-
deployment) nadat GitHub's CDN-cache herhaaldelijk een verouderde
versie van regime_orchestrator.py teruggaf, ook via de specifieke-
commit-hash-methode -- de op de VPS DRAAIENDE versie werd rechtstreeks
bevestigd (via een live grep) en vervolgens rechtstreeks, precies
bewerkt met een Python find-and-replace-script. Geverifieerd:
1 exacte match gevonden, syntax OK na de wijziging.

lp_manager.py apart nog te deployen (klaar, nog niet naar GitHub gezet
op het moment van deze notitie).

## Status aan het einde van deze sessie (1 sep 2026, ~16:15)

**Actieve positie**: token 351, breedte 10,5%, range 40,9035-50,4612
SAUCE/HBAR. Prijs staat op 86,6% in de range (dicht bij de bovenkant).

**Kapitaal**: totaal ~$101, waarvan ~$52 in de positie, de rest
(575 HBAR + 1.578 SAUCE) los in de wallet -- blijft daar bewust staan
totdat de veiligheidsklem het toestaat (zie hieronder), OP VERZOEK NIET
NU handmatig opgelost -- gebruiker wacht dit af en houdt het dashboard
in de gaten.

**Waarom het overtollige kapitaal nog niet bijgestort wordt**: positie
351 staat dicht bij de rand van zijn (smalle, 10,5%) range -- bijstorten
zou een onrealistisch grote swap vereisen (~1.959 HBAR tegen ~575
beschikbaar). De veiligheidsklem weigert dit terecht en stil (geen
Telegram-spam, alleen een logregel). Dit lost zichzelf op zodra de
positie buiten bereik loopt (nieuwe, gecentreerde range) of de
[regime-drift]-check een grote genoeg afwijking vindt.

**Bevestigd, structurele vervolgstap** (nog niet gebouwd, bewust
uitgesteld): de tranche-strategie (een aparte, tweede positie voor
overtollig kapitaal i.p.v. proberen het in een mogelijk-scheve
bestaande positie te persen) -- zie de eerdere, uitgebreide sectie
hierover verderop in dit document voor de volledige architectuur-
overwegingen.

## Belangrijke les uit deze sessie: prijsschaal-consistentie

Vandaag zijn er MEERDERE keren dezelfde kritieke bug gevonden (USD-
prijs gebruikt waar de pool-eigen SAUCE-per-HBAR-schaal nodig is) in
VERSCHILLENDE functies, gebouwd op verschillende momenten (soms in
een andere sessie). Aanbeveling voor een volgende sessie: overweeg een
grondige, EENMALIGE audit van ALLE plekken die current_price/fresh_price
gebruiken in regime_orchestrator.py, om te bevestigen dat dit patroon
nergens anders nog sluimert.

## Technische antwoorden van SaucerSwap (1 sep 2026, relevant voor de tranche-strategie)

Rechtstreeks van SaucerSwap's team, ter voorbereiding op het tranche-werk:
- mint() ondersteunt WEL volledig eenzijdige posities (amount0Desired=0
  of amount1Desired=0, tick-range volledig boven/onder de huidige prijs)
  -- bevestigd met een mainnet-voorbeeld-transactie.
- Minimale positiegrootte hangt af van de fee-tier's tickSpacing (zie
  SaucerSwap's fee-tier-documentatie), geen aparte, losse ondergrens.
- Geen bijzondere zorgen over het doorkruisen van veel niet-
  geinitialiseerde ticks (gas/revert-risico) bij een rustende,
  eenzijdige positie.
- BELANGRIJKE, STRUCTURELE VERKLARING voor de eerder vandaag gevonden
  eth_estimateGas-onbetrouwbaarheid (Price slippage check/
  INVALID_NFT_ID bij gesimuleerde mint()-aanroepen, die niet
  reproduceren bij een echt verzonden transactie): simulatie-
  transacties kunnen niet met de HTS-precompile-contract (0x167)
  interacteren, dus kunnen geen echt NFT-serienummer laten minten --
  geeft een placeholder-serienummer 0 terug, en de daaropvolgende
  overdracht van serienummer 0 veroorzaakt de INVALID_NFT_ID-fout.
  AANBEVELING: simulatie-aanroepen (eth_estimateGas/.call() op mint())
  helemaal vermijden voor dit specifieke type transactie, tenzij er een
  specifieke reden is om ze wel te gebruiken -- verklaart ook waarom
  onze eerdere fee-simulatie via collect() WEL werkte (dat mint geen
  nieuw NFT, dus geen precompile-probleem).
- Voor het detecteren of een eenzijdige positie volledig "gevuld" is:
  vergelijk de HUIDIGE tick met de min/max-ticks van de positie -- als
  de huidige tick boven/onder BEIDE grenzen ligt, is de positie er
  volledig doorheen bewogen.
- SaucerSwap's ontwikkelaars-documentatie is voor mij volledig
  leesbaar/doorzoekbaar, met name de developer-pagina's -- nuttig voor
  toekomstig, gedetailleerder opzoekwerk.

## Totaaloverzicht (stortingen + netto-resultaat) op het dashboard (1 sep 2026)

Op verzoek: "totaal aantal fees en de bijstortingen" onderaan het
dashboard. Na grondig, iteratief mirror-node-onderzoek (zie hieronder)
gekozen voor: totale stortingen (nauwkeurig) + netto-resultaat (huidige
waarde min stortingen), NIET een apart "totale fees"-getal -- dat bleek
niet betrouwbaar te reconstrueren zonder per gesloten positie (349,
350) de exacte, oorspronkelijke inleg te kennen (principaal en fees
komen in dezelfde overdracht terug bij het sluiten van een positie).

### get_total_deposits_hbar() (bot_data.py, NIEUW) -- twee iteraties nodig
Eerste versie (aannames over de mirror-node-datastructuur, niet vanuit
de sandbox te testen) gaf 0,0 HBAR terug -- FOUT: account.id-parameter
accepteert geen EVM-adres direct, en er bestaat geen apart
"payer_account_id"-veld.

Tweede versie (na live debuggen tegen de daadwerkelijke respons): eerst
het EVM-adres omzetten naar het Hedera-eigen 0.0.X-formaat via
/api/v1/accounts/{evm_adres}, en de initiator afleiden uit transaction_id
zelf (het deel vóór het eerste streepje). Gaf 7420,38 HBAR -- TE HOOG,
niet aannemelijk gegeven de huidige totale waarde van ~$101.

Derde, definitieve versie: bij het daadwerkelijk oplijsten van ELKE
meegetelde transactie (op verzoek) bleek het overgrote deel afkomstig
van initiator 0.0.7314364 -- Hedera's EIGEN JSON-RPC-relay-account, dat
ONZE EIGEN swap-/positie-transacties namens ons indient (bv. een
refundETH()-teruggave na een swap toont DIT account als "initiator",
niet onszelf). Expliciet uitgesloten naast ons eigen account. Resultaat:
2127,9987 HBAR -- BEVESTIGD DOOR DE GEBRUIKER als aannemelijk, komt
overeen met 3x testnet-faucet (0.0.2, 3x10 HBAR) + 3x eigen, handmatige
stortingen vanaf een aparte wallet (0.0.10230686, 999+999+99,9987 HBAR).

AANNAME/BEPERKING: 0.0.7314364 is een TESTNET-specifiek relay-account-
ID -- bij een mainnet-migratie moet dit opnieuw geverifieerd worden (kan
een ander account-ID zijn).

### Dashboard-integratie
- bot_data.py: fetch_dashboard_data() geeft nu ook "wallet_address"
  terug (nodig voor get_total_deposits_hbar(), voorkomt een aparte,
  overbodige RPC-client-aanmaak in dashboard_server.py).
- dashboard_server.py: berekent total_deposits_hbar en net_result_usd
  (huidige totale waarde min de dollarwaarde van de stortingen).
- templates/dashboard.html: nieuw paneel "Totaaloverzicht (sinds
  start)", met een nette lege-staat ("Niet beschikbaar") als de mirror-
  node-aanroep zou mislukken, en correcte kleur (rood bij verlies,
  groen bij winst) voor het netto-resultaat.

Geverifieerd: Jinja2-syntax, EN daadwerkelijke rendering van alle DRIE
scenario's (verlies, winst, niet-beschikbaar) met representatieve data.
NOG NIET live getest tegen de daadwerkelijke, draaiende dashboard-server
(vereist deployment).

## Fee-onderprestatie-trigger (2 sep 2026, op verzoek)

Gevonden: de bestaande _regime_drift_check() reageert uitsluitend op
sentiment/volatiliteit-gebaseerde breedte-afwijkingen -- een positie die
dicht bij de rand van zijn range staat EN structureel geen fees verdient
(waarschijnlijk omdat het actuele handelsvolume elders in de pool
plaatsvindt, buiten de smalle band, ook al is de POOL zelf wel actief)
werd hierdoor NOOIT opgemerkt als de GBM-voorgestelde breedte toevallig
niet noemenswaardig verschilde van de huidige.

NIEUW: _fee_underperformance_check() in regime_orchestrator.py -- als
een positie dicht bij de rand staat (<15% of >85%, zelfde drempel als
elders) EN de opgebouwde fees al fee_stagnation_uren_drempel uur (env
var FEE_STAGNATION_UREN_DREMPEL, default 4.0 -- AANNAME, niet empirisch
geijkt) niet meetbaar gegroeid zijn, wordt de positie proactief
hercentreerd op de HUIDIGE prijs. Geen aparte kosten-batenanalyse hier
(anders dan _regime_drift_check): bij structureel nul fee-inkomsten is
er per definitie niets te verliezen aan fee-opbrengst.

REFACTOR: sluit+balanceer+heropen-logica geextraheerd uit
_regime_drift_check() naar een gedeelde methode
_sluit_en_heropen_positie() (reden_label-parameter voor duidelijke
foutmeldingen per aanroeper) -- voorkomt gedupliceerde logica op
meerdere plekken, een probleem dat vandaag al meerdere keren zorgde
voor een fix die maar op een van de twee plekken landde.

Geverifieerd: syntax, instantiatie, EN vier functionele scenario's via
mocking (niet-dicht-bij-rand -> reset; fees groeien -> geen actie;
eerste stagnatie -> klok gestart, geen actie; langdurige stagnatie ->
actie correct getriggerd). NOG NIET live getest (vereist een
daadwerkelijk stagnerende positie, of een verkorte drempel voor een
snelle test).

### TE HERIJKEN VOOR MAINNET-LIVEGANG (op verzoek genoteerd, 2 sep 2026)

Het onderliggende principe (een positie kan dicht bij de rand staan EN
naast het echte handelsvolume zitten, ook als de POOL zelf wel actief
is) blijft ook op een drukkere mainnet-pool relevant -- waarschijnlijk
zelfs belangrijker, met echt kapitaal op het spel. Maar de HUIDIGE
drempelwaarden zijn expliciet gegokt voor de huidige, rustige
testnet-situatie, niet empirisch onderbouwd, en moeten voor mainnet
opnieuw bekeken worden:

- `fee_stagnation_uren_drempel` (env var FEE_STAGNATION_UREN_DREMPEL,
  huidige default 4.0 uur): op een veel actievere mainnet-pool zou
  "geen fee-groei" waarschijnlijk zeldzamer voorkomen (meer volume
  raakt meer prijspunten) -- deze drempel kan wellicht korter, of moet
  anders gekalibreerd worden om vals-positieven te voorkomen bij
  normale, korte stiltes.
- `FEE_GROEI_DREMPEL_HBAR` (huidige, vast-gecodeerde waarde 0.001 HBAR
  in _fee_underperformance_check()): expliciet gebaseerd op "ongeveer
  de orde van een testnet-gasfee". Op mainnet, met betekenisvollere
  bedragen, zou dit beter uitgedrukt kunnen worden als een PERCENTAGE
  van de positiewaarde, i.p.v. een vast HBAR-bedrag.

AANBEVELING: vóór mainnet-livegang empirisch herijken -- bijvoorbeeld
door te kijken hoe vaak en hoe lang deze check op mainnet-achtige
volumes daadwerkelijk zou aanslaan (vergelijkbaar met hoe de fee-APR-
basislijn vandaag al eens gecorrigeerd is van een verouderde mainnet-
aanname naar de live, werkelijk-gemeten APR).

## Git structureel gekoppeld aan de VPS (2 sep 2026)

Root cause voor herhaalde synchronisatieproblemen vandaag (GitHub-
bestanden bewerken die dan weer via wget opgehaald moesten worden, met
herhaaldelijke CDN-cache-problemen): geen echte git-koppeling, alleen
losse wget-downloads. OPGELOST: SSH-sleutel gegenereerd op de VPS
(~/.ssh/github_hbar_bot), toegevoegd aan GitHub, git geinitialiseerd in
~/hbar_bot met de HUIDIGE, daadwerkelijk-draaiende VPS-staat als
uitgangspunt (127 bestanden, inclusief eerdere, rechtstreeks-op-de-VPS
gemaakte fixes die nooit waren teruggezet naar GitHub), en geforceerd
gepusht naar GitHub main (GitHub was verouderd t.o.v. de VPS).

Vanaf nu: `git pull`/`git add . && git commit && git push` rechtstreeks
op de VPS, i.p.v. bestanden via de browser naar GitHub kopieren en dan
met wget (+nocache-trucs, soms zelfs commit-hash-methode nodig) weer
ophalen.
