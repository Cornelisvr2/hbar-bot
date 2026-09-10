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
