-- Fase 1 nieuws/macro-plan (10 sep 2026): classificatie per gebeurtenis
-- (geen richting) + plek voor de markt-labels uit de event-study.
-- Draaien op een bestaande database (db_schema.sql loopt alleen bij een
-- verse volume):  docker compose exec -T database psql -U hbar_bot -d hbar_bot < migratie_news_events.sql
CREATE TABLE IF NOT EXISTS news_events (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at    TIMESTAMPTZ,
    asset           TEXT NOT NULL,              -- feed waaruit de kop kwam (BTC/HBAR)
    headline        TEXT NOT NULL,
    headline_key    TEXT NOT NULL,              -- genormaliseerd (rss_news_client.normalize_headline)
    source_feed     TEXT,
    url             TEXT,
    -- LLM-classificatie (geen richting)
    category        TEXT NOT NULL,              -- regulering_etf | listing_exchange | hack_security | macro_fed | adoption_partnership | tokenomics_unlock | protocol_upgrade | marktcommentaar | overig
    entity          TEXT NOT NULL,              -- BTC | HBAR | markt_breed | andere_coin
    novelty         TEXT NOT NULL,              -- nieuw_feit | update | commentaar
    magnitude_guess SMALLINT NOT NULL,          -- 1..5
    event_key       TEXT NOT NULL,              -- canonieke naam, clustert koppen over dezelfde gebeurtenis
    llm_rationale   TEXT,
    -- Markt-labels (event-study, later gevuld door cron)
    pre_move_1h     DOUBLE PRECISION,
    abn_ret_1h      DOUBLE PRECISION,
    abn_ret_4h      DOUBLE PRECISION,
    abn_ret_24h     DOUBLE PRECISION,
    abn_vol_1h      DOUBLE PRECISION,
    abn_vol_4h      DOUBLE PRECISION,
    exc_ret_1h      DOUBLE PRECISION,           -- alleen HBAR: t.o.v. BTC
    exc_ret_4h      DOUBLE PRECISION,
    exc_ret_24h     DOUBLE PRECISION,
    labeled_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS news_events_created_idx ON news_events (created_at);
CREATE INDEX IF NOT EXISTS news_events_event_key_idx ON news_events (event_key);
CREATE UNIQUE INDEX IF NOT EXISTS news_events_asset_headline_key_idx ON news_events (asset, headline_key);

-- Geleerde gewichten (wekelijkse cron, fase 3); nu al aangemaakt zodat de
-- code er vanaf het begin tegenaan kan lezen (leeg = gewicht 1 overal).
CREATE TABLE IF NOT EXISTS news_weights (
    asset       TEXT NOT NULL,
    dimension   TEXT NOT NULL,                  -- category | novelty | source
    value       TEXT NOT NULL,
    weight      DOUBLE PRECISION NOT NULL,      -- |abnormale beweging| / basisniveau; 0 = ruis
    direction   DOUBLE PRECISION,               -- +1/-1 als tekenconsistentie > 65% over n>=20, anders NULL
    n           INTEGER NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asset, dimension, value)
);
-- Fase 2 nieuws/macro-plan (10 sep 2026): opslag voor externe datareeksen
-- en de event-risico-kalender (laag 7).
-- docker compose exec -T database psql -U hbar_bot -d hbar_bot < migratie_macro_inputs.sql
CREATE TABLE IF NOT EXISTS macro_inputs (
    source      TEXT NOT NULL,          -- fred | fmp | binance_fut | fng | defillama | coingecko | mirrornode
    series      TEXT NOT NULL,          -- DGS10, funding_BTCUSDT, fear_greed, ...
    ts          TIMESTAMPTZ NOT NULL,   -- waarnemingstijd (dag- of uurstempel)
    value       DOUBLE PRECISION NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, series, ts)
);
CREATE INDEX IF NOT EXISTS macro_inputs_series_ts_idx ON macro_inputs (series, ts DESC);

CREATE TABLE IF NOT EXISTS event_calendar (
    source      TEXT NOT NULL,          -- fmp | forexfactory | coinmarketcal | sec
    name        TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,   -- geplande tijd (UTC)
    country     TEXT,
    impact      TEXT,                   -- high | medium | low
    asset       TEXT,                   -- BTC/HBAR/markt_breed (crypto-events)
    estimate    DOUBLE PRECISION,
    previous    DOUBLE PRECISION,
    actual      DOUBLE PRECISION,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, name, ts)
);
CREATE INDEX IF NOT EXISTS event_calendar_ts_idx ON event_calendar (ts);
-- Backfill 2 jaar (10 sep 2026): candles + ruwe nieuwskoppen uit archieven.
-- docker compose exec -T database psql -U hbar_bot -d hbar_bot < migratie_backfill.sql
CREATE TABLE IF NOT EXISTS candles_5m (
    symbol  TEXT NOT NULL,            -- BTC | HBAR
    ts      TIMESTAMPTZ NOT NULL,     -- open-tijd van de candle (UTC)
    open    DOUBLE PRECISION NOT NULL,
    high    DOUBLE PRECISION NOT NULL,
    low     DOUBLE PRECISION NOT NULL,
    close   DOUBLE PRECISION NOT NULL,
    volume  DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (symbol, ts)
);

CREATE TABLE IF NOT EXISTS news_raw (
    id            BIGSERIAL PRIMARY KEY,
    asset         TEXT NOT NULL,            -- BTC | HBAR | MACRO
    headline      TEXT NOT NULL,
    headline_key  TEXT NOT NULL,
    published_at  TIMESTAMPTZ NOT NULL,
    source        TEXT,                     -- coindesk_archive | gdelt
    source_name   TEXT,                     -- uitgever
    url           TEXT,
    classified    BOOLEAN NOT NULL DEFAULT FALSE,
    skipped       TEXT,                     -- reden als niet geclassificeerd (ruis, dubbel, te klein)
    UNIQUE (asset, headline_key)
);
CREATE INDEX IF NOT EXISTS news_raw_published_idx ON news_raw (published_at);
CREATE INDEX IF NOT EXISTS news_raw_todo_idx ON news_raw (classified) WHERE classified = FALSE;
