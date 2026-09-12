-- Telegram pending-verzoeken (12 sep 2026) -- vervangt de in-memory _pending-dict
-- in telegram_webhook.py. Reden: een los CLI-proces (bv. `--test`) en de
-- draaiende dashboard-server zijn twee aparte OS-processen die geen geheugen
-- delen -- een verzoek aangemaakt door het ene proces was onvindbaar voor het
-- andere ("verzoek onbekend/verlopen" bij elke tap). Door de staat in Postgres
-- te zetten ziet elk proces (CLI-scripts, de webhook-handler, en eventuele
-- toekomstige extra workers) dezelfde, actuele staat.
--
-- Toepassen op de bestaande, live database:
--   docker compose exec -T database psql -U hbar_bot -d hbar_bot < migratie_telegram_pending.sql

CREATE TABLE IF NOT EXISTS telegram_pending_verzoeken (
    id           TEXT PRIMARY KEY,             -- het verzoek_id (uuid4 hex, 12 tekens)
    soort        TEXT NOT NULL,                -- bv. "test", "login", later "actie_2fa"
    omschrijving TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'open',  -- open | goedgekeurd | geweigerd | verlopen
    aangemaakt   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS telegram_pending_verzoeken_aangemaakt_idx
    ON telegram_pending_verzoeken (aangemaakt);

-- Opruimen: oude verzoeken hebben geen waarde meer na hun TTL (120s) plus een
-- ruime marge. Los te draaien of via de bestaande cron-structuur:
--   DELETE FROM telegram_pending_verzoeken WHERE aangemaakt < now() - interval '1 day';
