# Plan: nieuws en data in de macro-laag, en leren wat écht de markt beweegt

Datum: 10 sep 2026, op verzoek. Vervangt/verfijnt de sectie "Nieuws-tijdlijn,
extra nieuwsbronnen en zelflerend sentiment" in PLAN.md.

## 0. Vertrekpunt en wat de kalibratie ons leerde

- De macro-analyse (macro_analysis.py, 8 sep) heeft vijf lagen: halving-prior,
  MA200-marktstatus, trend per horizon (6m/1m/7d/24h), uitlijning, eindscore
  met drift-multiplier. Data: alleen Binance-candles. Draait in schaduwmodus.
- De nieuwslaag (RSS -> Claude Haiku -> sentiment_log -> combined score)
  geeft een RICHTINGSscore per kop. Kalibratie 10 sep (252 unieke koppen):
  Spearman met de 1u/4u-beweging is ~0, hit-rate ~50%, en de LLM heeft een
  positieve bias (+0,17 BTC, +0,27 HBAR in een dalende markt).
- Conclusie: de LLM raden laten wat de koers doet werkt niet. De LLM kan wel
  iets anders goed: CLASSIFICEREN (wat voor nieuws is dit, over wie, is het
  nieuw, hoe groot). De richting en het gewicht moeten uit de markt zelf
  komen (event-study). Dat is het hart van dit plan.

## 1. Architectuur: twee snelheden, één plek van waarheid

```
              +---------------------------+
 bronnen  --> |  news_raw (alle koppen)   |  ontdubbeld, ruisfilter (bestaat)
              +------------+--------------+
                           | LLM: classificatie (geen richting)
              +------------v--------------+
              |  news_events              |  categorie, entiteit, nieuwheid,
              |  (1 rij per gebeurtenis)  |  omvang-schatting, bron
              +------+-------------+------+
                     |             |
       SNEL (15 min) |             | LANGZAAM (dagelijks/wekelijks)
                     v             v
     flash-verdediging      event-study: abnormale beweging per
     (bestaat; alleen bij   gebeurtenis -> geleerde gewichten per
     omvang>=4 en nieuw)    categorie/bron -> narrative index (7d)
                                   |
                                   v
                        macro_analysis: laag 6 "narratief & flows"
                        + laag 7 "event-risico-kalender"
```

- Snel pad: alleen voor schokken (hack, depeg, verbod, ETF-besluit). Bestaat
  al (flash_event_model); wordt gevoed door omvang+nieuwheid i.p.v. de
  richtingsscore.
- Langzaam pad: sluit aan op de macro-analyse, in dezelfde schaduw-eerst-
  discipline: loggen, vergelijken, dan pas laten sturen.

## 2. Data-API's voor de macro-laag (naast nieuws)

Gratis tenzij anders vermeld. Cadans = hoe vaak ophalen.

### 2a. Marktstructuur en geldstromen (leidend voor bull/bear)
| Bron | Wat | Cadans | Key |
|---|---|---|---|
| Binance Futures REST (`fapi.binance.com`) | funding rate (`/fapi/v1/fundingRate`), open interest historie (`/futures/data/openInterestHist`), long/short-ratio, taker buy/sell — BTCUSDT én HBARUSDT | 1u | geen |
| CoinGecko publiek endpoint (`/global`, `/coins/{id}`) | BTC-dominantie, totale markt-cap, stablecoin-marktkapitalisatie | 1x/dag | geen (keyloos volstaat bij 1 call/dag; Demo-plan bleek betaald, ~€30/mnd, niet nodig) |
| alternative.me `/fng/` | Fear & Greed-index (historie beschikbaar) | 1x/dag | geen |
| DefiLlama (`api.llama.fi`) | TVL Hedera-chain, stablecoin-supply per chain, DEX-volumes | 1x/dag | geen |
| Farside Investors (webpagina, geen API) | dagelijkse BTC-ETF-in/uitstromen — de belangrijkste "flow"-reeks van deze cyclus | 1x/dag scrape | geen; als scrapen te fragiel: CoinGlass (betaald) |

### 2b. On-chain (HBAR-specifiek — dit heeft niemand anders in zijn score)
| Bron | Wat | Cadans | Key |
|---|---|---|---|
| Hedera Mirror Node REST (`mainnet-public.mirrornode.hedera.com`) | transactievolume, nieuwe accounts, staking-totaal, HTS-activiteit, TPS | 1x/uur | geen |
| SaucerSwap API / GeckoTerminal (client bestaat) | pool-volume en TVL WHBAR/USDC, aantal swaps | 1x/uur | geen |
| mempool.space / blockchain.com | BTC-hashrate, fees, mempool-grootte (netwerkstress) | 1x/dag | geen |

### 2c. Macro-economie
| Bron | Wat | Cadans | Key |
|---|---|---|---|
| FRED API (St. Louis Fed) | DXY (DTWEXBGS), 10j-rente (DGS10), 2j (DGS2), reële rente (DFII10), Fed funds (DFF), M2, VIX (VIXCLS), S&P 500 (SP500) | 1x/dag | gratis key |
| Financial Modeling Prep, gratis tier | economische kalender (FOMC, CPI, NFP) met verwachting/uitkomst | 1x/dag | gratis key, 250 calls/dag |
| Forex Factory `ff_calendar_thisweek.json` | zelfde kalender, reserve | 1x/dag | geen |
| yfinance (onofficieel) | intraday NDX/goud/DXY als FRED te traag is | fallback | geen |

### 2d. Geplande crypto-gebeurtenissen en regulering
| Bron | Wat | Cadans | Key |
|---|---|---|---|
| CoinMarketCal API | geplande events (upgrades, listings, conferenties) per coin | 1x/dag | gratis key |
| SEC EDGAR full-text search (`efts.sec.gov/LATEST/search-index`) | ETF-filings (19b-4, S-1) met "Hedera"/"HBAR"; besluitdata | 1x/dag | geen |
| Federal Register API | regelgeving crypto (Treasury, SEC, CFTC) | 1x/dag | geen |
| Hedera treasury/HBAR Foundation-rapporten (webpagina) | vrijgaveschema HBAR (aanbodschokken) | 1x/maand | geen |

### 2e. Nieuws zelf (uit het eerdere plan, ongewijzigd)
GDELT DOC 2.0 (algemeen/financieel, gratis), CryptoPanic (client bestaat),
CryptoCompare News (gratis key), RSS uitbreiden (The Block, Decrypt,
Hedera-blog, HBAR Foundation, SaucerSwap). Betaald pas als nodig: CoinGecko
Analyst-plan. NIET: Finnhub (geen gratis tier meer).

Benodigde keys: FRED (binnen), FMP (binnen), CoinMarketCal, CryptoCompare.
Alle andere bronnen zijn keyloos. Stand 10 sep 2026.

## 3. Leren wat relevant is (en ruis negeren)

### Stap A — de LLM een andere vraag stellen
Vervang "is dit bullish/bearish?" door een classificatie met gedwongen
JSON-schema (zelfde tool-use-mechaniek als nu):
- `category`: regulering/ETF · listing/exchange · hack/security · macro-Fed ·
  adoption/partnership · tokenomics/unlock · protocol-upgrade ·
  marktcommentaar · overig
- `entity`: BTC · HBAR · markt-breed · andere coin
- `novelty`: nieuw feit / update op bekend feit / commentaar op bekend feit
- `magnitude_guess`: 1–5 (LLM-inschatting van hoe groot dit KAN zijn)
- `event_key`: korte canonieke naam ("SEC-besluit HBAR-ETF") zodat meerdere
  koppen over hetzelfde tot één gebeurtenis clusteren
Geen richting meer. Kosten gelijk aan nu (één Haiku-call per unieke kop).

### Stap B — de markt laten labelen (event-study, dagelijks via cron)
Per gebeurtenis (niet per kop) achteraf berekenen, uit Binance 5-min-candles:
- abnormaal rendement op +1u/+4u/+24u = rendement minus de normale
  verwachting (0) gedeeld door de normale volatiliteit van dat uur (uit
  gbm_range_model) -> een z-score, vergelijkbaar over dagen en assets
- abnormaal volume op dezelfde horizons
- voor HBAR: excess t.o.v. BTC (beta uit 30d-regressie i.p.v. 1)
- "al ingeprijsd": beweging op −1u vóór de eerste kop
Opslag: `news_events` krijgt kolommen `abn_ret_1h/4h/24h`, `abn_vol_*`,
`pre_move_1h`, gevuld zodra de horizon verstreken is.

### Stap C — gewichten leren (wekelijks via cron, zoals recalibrate_cron)
Tabel `news_weights(asset, category, novelty, source) -> gewicht`:
- gewicht = gemiddelde |abnormale beweging| van die groep, gedeeld door het
  basisniveau (gemiddelde |beweging| rond willekeurige momenten), met
  krimping naar 1 bij weinig waarnemingen (n<20)
- richting per groep = tekenconsistentie van de excess-return; alleen
  gebruiken als die > 65% is over n>=20, anders richtingloos
- groepen met gewicht <= 1,1 (niet beter dan toeval) = RUIS: gewicht 0.
  Verwachting: "marktcommentaar", "commentaar op bekend feit" en de meeste
  Google-News-bronnen belanden hier vanzelf. Dat is het zelflerende
  ruisfilter — het regelfilter van 10 sep blijft ervoor staan als goedkope
  eerste zeef.
- bronbetrouwbaarheid = zelfde berekening per bron; bronnen die structureel
  ná de beweging publiceren (pre_move groot, abn_ret klein) krijgen laag
  gewicht, ongeacht de inhoud.
Pas na >= 1.000 gelabelde gebeurtenissen: logistische regressie op
Claude-embeddings + categorie als vervanging van de opzoektabel. Eerder niet.

### Stap D — koppeling aan de macro-analyse
- Laag 6 "narratief & flows": narrative_index(asset) = som over 7 dagen van
  gewicht × richting × verval(halfwaardetijd 2 dagen), plus de flow-reeksen
  uit 2a (ETF-flows, funding, stablecoin-supply) elk genormaliseerd op hun
  eigen 90d-z-score. Startgewicht in de eindscore: 0,15 (kleinste laag).
- Laag 7 "event-risico-kalender": FOMC/CPI/NFP, ETF-besluitdata, grote
  unlocks. Binnen ±2u van zo'n moment: geen nieuwe reflex-entries, range
  breder. Dit is de betrouwbaarste toepassing van nieuws, want de tijd is
  vooraf bekend.
- Flash-verdediging (snel pad): trigger op magnitude_guess >= 4 én
  novelty = nieuw feit én categorie in {hack, regulering, depeg, macro-Fed},
  i.p.v. op een sprong in de richtingsscore.
- De huidige richtingsscore: gewicht in de combined score naar nul zodra
  laag 6 in schaduw meeloopt; tot die tijd recentreren op het 30d-gemiddelde
  per asset (bias-correctie).

### Stap E — meten of het werkt (elke maand, vast script)
- kalibratie_sentiment.py uitbreiden naar news_events: per categorie de
  abnormale beweging t.o.v. basisniveau; |magnitude_guess| vs |beweging|;
  horizon 24u erbij.
- Succescriterium laag 6: Spearman(narrative_index, 7d-forward excess
  return) > 0,15 over >= 8 weken schaduw. Onder die grens blijft het schaduw.
- Succescriterium ruisfilter: aandeel koppen met gewicht 0 stijgt, terwijl
  het aantal gemiste flash-events (achteraf: |abn_ret_1h| > 3 z zonder
  gebeurtenis in de log) niet toeneemt.

## 4. Volgorde en doorlooptijd

| Fase | Wat | Wanneer |
|---|---|---|
| 1 | Tabellen `news_raw`, `news_events`, `news_weights`; LLM-prompt naar classificatie (stap A); richtingsscore recentreren; nieuws-tijdlijn op dashboard | deze week |
| 2 | Bronnen 2e + keyloze data 2a/2b/2c inladen naar `macro_inputs(ts, bron, reeks, waarde)`; kalender (laag 7) meteen actief — dat is risicobeheer, geen voorspelling | week 2 |
| 3 | Event-study-cron (stap B) en gewichten-cron (stap C) draaien, alleen loggen | week 2–3, daarna verzamelen |
| 4 | Laag 6 in schaduw naast de bestaande macro-score; maandelijkse meting (stap E) | vanaf week 4, minimaal 8 weken |
| 5 | Pas bij gehaald criterium: laag 6 laat range-asymmetrie sturen; embeddings-model overwegen | ~week 12+ |

Wat we NIET doen: de LLM richting laten raden, nieuws als koop/verkoop-
signaal, betaalde data voordat de gratis reeksen bewezen bijdragen, en het
model laten sturen vóór acht weken schaduw.
