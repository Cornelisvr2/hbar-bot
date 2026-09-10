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
