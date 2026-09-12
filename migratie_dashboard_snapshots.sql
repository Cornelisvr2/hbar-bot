-- Dashboard snapshot-tabel (fase 1 lees-architectuur, 12 sep 2026).
-- De bot/writer schrijft hier elke paar minuten de volledige dashboard-status
-- als JSON weg. Het dashboard leest de LAATSTE rij (huidige stand) en de
-- historie (voor grafieken). Zo doet het dashboard geen live on-chain calls
-- meer bij het laden -> instant.
CREATE TABLE IF NOT EXISTS dashboard_snapshots (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload     JSONB NOT NULL          -- de volledige _build_dashboard_context()-dict
);
CREATE INDEX IF NOT EXISTS dashboard_snapshots_ts_idx ON dashboard_snapshots (ts DESC);

-- Opruimen: houd ~30 dagen historie (genoeg voor de grafieken). Los te draaien
-- of via cron: DELETE FROM dashboard_snapshots WHERE ts < now() - interval '30 days';
