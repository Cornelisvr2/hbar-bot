# HBAR Trading Bot — Bouwplan

*Consolidatie van alle eerdere beslissingen. Voor volledige technische
details zie `PLAN.md`; voor een niet-technisch overzicht zie
`MANAGEMENT_SUMMARY.md`. Dit document is het uitvoerbare stappenplan.*

## Wat de bot doet

Twee gelijktijdige processen, gescheiden kapitaal (€1.000 elk van de
€2.000):
1. **Directioneel traden** op BTC/HBAR-nieuwssentiment (regelgebaseerd +
   Claude-LLM met verplicht tegenargument), via SaucerSwap V1 of V2
2. **LP-beheer** van de HBAR/USDC-pool, met een volatiliteits-adaptieve
   breedte en sentiment-gestuurde proactieve verschuiving, om
   impermanent loss te beperken

## Wat al klaar is

| Categorie | Modules |
|---|---|
| Sentiment | `cryptopanic_client.py`, `llm_sentiment_engine.py` (met tegenargument-veld) |
| Marktdata | `coingecko_client.py`, `geckoterminal_client.py` |
| Beslislogica | `strategy_engine.py`, `safety_override.py` |
| Positiebeheer | `position_planner.py` (directioneel), `lp_manager.py` (LP, met volatiliteits-regimes) |
| Hedera-koppeling | `hedera_rpc_client.py`, `hedera_address_utils.py`, `config.py` |
| Uitvoering | `swap_executor.py` (V1), `swap_executor_v2.py` (V2), `execute_hbar_swap_standalone.py` |
| Validatie | `backtest_pipeline.py` (mechaniek klaar, data ontbreekt nog) |
| Rapportage | `telegram_notify.py` |
| Deployment | `Dockerfile`, `docker-compose.yml`, `db_schema.sql` |

## Wat nog ontbreekt

`risk_manager.py`, `main_orchestrator.py`, `postgres_client.py` — de
drie modules die alle bovenstaande losse onderdelen tot een lopend
geheel maken.

---

## Stappenplan

### Stap 1 — `risk_manager.py` bouwen
**Waarom eerst**: alle andere modules bestaan al, maar niets dwingt de
harde grenzen af. Zonder dit kunnen `strategy_engine.py` en
`lp_manager.py` in theorie strijdig kapitaal claimen.

**Moet afdwingen**:
- De 50/50-kapitaalscheiding tussen LP en directioneel traden
- Max. trades per dag, daily loss-limit
- Dedup van nieuwsitems (voorkomt dubbele trades op hetzelfde bericht)
- Afkoelperiode na een trade (whipsaw-preventie)
- Nonce-locking/sequenties tussen losgekoppelde subprocessen

**Benodigd**: geen externe input, puur bouwen op wat er al ligt.

### Stap 2 — `postgres_client.py` bouwen
**Waarom**: `db_schema.sql` staat al klaar, maar niets schrijft ernaar.
Nodig voor de dagrapporten via `telegram_notify.py` en voor
`backtest_pipeline.py`'s logging.

**Benodigd**: `DATABASE_URL` (staat al in `.env.example`).

### Stap 3 — `main_orchestrator.py` bouwen
**Waarom**: bindt alles samen — de event-loop die stap voor stap
nieuws/marktdata ophaalt, sentiment bepaalt, door de strategie en
veiligheidslagen laat lopen, en zowel de trade-executie als het
LP-beheer aanstuurt.

**Benodigd**: stap 1 en 2 moeten af zijn.

### Stap 4 — Openstaande blokkades oplossen
Kan parallel aan stap 1-3:
- Mainnet V2-adressen (Factory, SwapRouter, QuoterV2, PositionManager)
- Fee-tier bevestigen — nu mogelijk via het GeckoTerminal-gevonden
  poolcontract (`0xc5b7...b11d`) zelf te bevragen
- USDC-associatie op het bot-account bevestigen
- Testnet-HBAR-balans op het bot-account bevestigen

**Benodigd van jou**: bevestiging/uitzoekwerk op de bovenstaande punten.

### Stap 5 — Historische data verzamelen
Vult `backtest_pipeline.py`, dat nu al staat maar leeg is:
- Historisch nieuws (CryptoPanic-archief of handmatige export)
- Historische prijzen op minuutniveau (Binance klines, gratis, geen key)
- Historische poolvolumedata (via het nieuwe `geckoterminal_client.py`)

**Benodigd**: tijd om dit te verzamelen; geen nieuwe accounts nodig
voor Binance/GeckoTerminal (beide gratis, geen key vereist voor de
gebruikte endpoints).

### Stap 6 — Fase 1: Backtesting draaien
Sentiment-drempels in `strategy_engine.py` kalibreren, de echte
few-shot-voorbeelden voor `llm_sentiment_engine.py` genereren (i.p.v.
de huidige placeholders). Duur: een middag tot een dag.

**Benodigd**: `ANTHROPIC_API_KEY` (voor de LLM-calls tijdens backtesting).

### Stap 7 — Fase 2: Een maand op testnet
`main_orchestrator.py` ononderbroken laten draaien op testnet, via
Docker Compose (`restart: always`). Bewijst operationele
betrouwbaarheid — iets wat backtesting niet kan testen.

**Benodigd**: de VPS moet dit een maand ononderbroken kunnen draaien;
`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` voor doorlopend zicht op wat
er gebeurt.

### Stap 8 — Evalueren en bijstellen
Bugs en onverwacht gedrag uit de testnet-maand oplossen voordat er
echt geld bij komt.

### Stap 9 — Fase 3: Mainnet, klein bedrag
Pas na een succesvolle stap 6 én 7-8. Start met een fractie van de
€2.000, niet het volledige bedrag in één keer.

---

## Later / bewust uitgesteld (niet blokkerend voor bovenstaand traject)

- **LP-parameter-backtest**: `geckoterminal_client.py` staat er, de
  simulatie die cooldown/regime-breedtes optimaliseert nog niet
- **SaucerSwap V3 (orderboek)**: nieuw ontdekt, nog niet geïntegreerd —
  wacht op de Orderbook API-referentie en de Risk Notice
- **Farm/epoch-weight-optimalisatie**: welke pool het meest oplevert
  aan SAUCE-rewards — wacht op dezelfde SaucerSwap-API-toegang

## Checklist — wat jij nog moet aanleveren of regelen

- [ ] Mainnet V2-contractadressen (Factory, SwapRouter, QuoterV2, PositionManager)
- [ ] Bevestiging fee-tier van de WHBAR/USDC V2-pool
- [ ] USDC-associatie op het bot-account
- [ ] Testnet-HBAR op het bot-account (via de Hedera Portal faucet)
- [ ] Historisch nieuwsarchief (CryptoPanic) verzamelen of exporteren
- [ ] `ANTHROPIC_API_KEY`, `CRYPTOPANIC_API_TOKEN`, `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in `.env`
- [ ] Een maand geduld voor Fase 2, vóór er ooit mainnet-kapitaal bij komt
