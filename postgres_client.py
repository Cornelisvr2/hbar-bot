"""
postgres_client.py

Schrijft naar de tabellen uit db_schema.sql: sentiment_log,
strategy_signals, trades, open_positions. Asyncpg-gebaseerd, voor
gebruik in de asyncio-event-loop van main_orchestrator.py.
"""

import os
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List

import asyncpg


@dataclass
class DailyStats:
    total_trades: int
    successful_trades: int
    failed_trades: int
    avg_btc_sentiment: float
    avg_hbar_sentiment: float
    panic_overrides_triggered: int
    net_hbar_change: float
    net_usdc_change: float


class PostgresClient:
    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL")
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        if not self.dsn:
            raise EnvironmentError("DATABASE_URL niet gezet.")
        self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)

    async def close(self):
        if self._pool:
            await self._pool.close()

    async def log_sentiment(self, asset: str, headline: str, sentiment_score: float,
                              confidence: float, is_idiosyncratic: bool,
                              rationale: str = "", source: str = "llm",
                              volatility_sigma: float = 0.5) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO sentiment_log
                    (asset, headline, sentiment_score, confidence, is_idiosyncratic, rationale, source, volatility_sigma)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                asset, headline, sentiment_score, confidence, is_idiosyncratic, rationale, source, volatility_sigma,
            )
            return row["id"]

    async def log_news_event(self, asset: str, headline: str, headline_key: str, published_at,
                             source_feed: str, url: str, category: str, entity: str, novelty: str,
                             magnitude_guess: int, event_key: str, rationale: str) -> None:
        """Fase 1 (10 sep 2026): classificatie per kop naar news_events; dubbele kop = stil overslaan."""
        from datetime import datetime, timezone
        pub = datetime.fromtimestamp(published_at, tz=timezone.utc) if published_at else None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO news_events (asset, headline, headline_key, published_at, source_feed, url,
                                         category, entity, novelty, magnitude_guess, event_key, llm_rationale)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                ON CONFLICT (asset, headline_key) DO NOTHING
                """,
                asset, headline, headline_key, pub, source_feed, url,
                category, entity, novelty, magnitude_guess, event_key, rationale,
            )

    async def recent_headlines(self, hours: float = 24.0) -> list[str]:
        """
        NIEUW (10 sep 2026): headlines uit sentiment_log van de laatste
        `hours` uur -- voor ontdubbeling die een herstart overleeft (de
        in-memory set _processed_news_ids gaat bij elke herstart leeg,
        waardoor alle nieuws van de afgelopen 4u opnieuw gescoord en
        opnieuw meegewogen werd).
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT headline FROM sentiment_log WHERE created_at > now() - ($1 || ' hours')::interval",
                str(hours),
            )
            return [r["headline"] for r in rows]

    async def log_strategy_signal(self, direction: str, confidence: float, position_fraction: float,
                                    btc_score: float, hbar_score: float,
                                    panic_override_triggered: bool = False, reasoning: str = "") -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO strategy_signals
                    (direction, confidence, position_fraction, btc_score, hbar_score,
                     panic_override_triggered, reasoning)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                direction, confidence, position_fraction, btc_score, hbar_score,
                panic_override_triggered, reasoning,
            )
            return row["id"]

    async def log_trade(self, direction: str, engine: str, network: str, amount_in: float,
                          estimated_amount_out: Optional[float], actual_amount_out: Optional[float],
                          tx_hash: Optional[str], status: str,
                          strategy_signal_id: Optional[int] = None) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO trades
                    (direction, engine, network, amount_in, estimated_amount_out,
                     actual_amount_out, tx_hash, status, strategy_signal_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
                """,
                direction, engine, network, amount_in, estimated_amount_out,
                actual_amount_out, tx_hash, status, strategy_signal_id,
            )
            return row["id"]

    async def open_position(self, entry_price: float, initial_stop_loss: Optional[float],
                              trailing_distance_pct: Optional[float], quantity_hbar: float,
                              trade_id: Optional[int] = None) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO open_positions
                    (entry_price, initial_stop_loss, trailing_distance_pct,
                     highest_price_seen, quantity_hbar, trade_id, is_open)
                VALUES ($1, $2, $3, $1, $4, $5, TRUE)
                RETURNING id
                """,
                entry_price, initial_stop_loss, trailing_distance_pct, quantity_hbar, trade_id,
            )
            return row["id"]

    async def update_highest_price(self, position_id: int, highest_price: float):
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE open_positions SET highest_price_seen = $1 WHERE id = $2",
                highest_price, position_id,
            )

    async def close_position(self, position_id: int):
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE open_positions SET is_open = FALSE, closed_at = now() WHERE id = $1",
                position_id,
            )

    async def get_open_positions(self) -> List[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM open_positions WHERE is_open = TRUE")
            return [dict(r) for r in rows]

    async def save_active_lp_position(self, token_id: int, tick_lower: int, tick_upper: int):
        """
        Slaat de actieve LP-positie op, zodat de bot dit na een herstart
        kan herstellen (26 aug 2026 -- lost het "vergeet open positie na
        herstart"-probleem op). Verwijdert eerst elke bestaande rij --
        er hoort er maximaal een te zijn.
        """
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM active_lp_position")
            await conn.execute(
                "INSERT INTO active_lp_position (token_id, tick_lower, tick_upper) "
                "VALUES ($1, $2, $3)",
                token_id, tick_lower, tick_upper,
            )

    async def get_active_lp_position(self) -> Optional[dict]:
        """Geeft de opgeslagen actieve LP-positie terug, of None als er geen is."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT token_id, tick_lower, tick_upper FROM active_lp_position "
                "ORDER BY id DESC LIMIT 1"
            )
            return dict(row) if row else None

    async def clear_active_lp_position(self):
        """Verwijdert de opgeslagen actieve LP-positie (bij het sluiten ervan)."""
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM active_lp_position")

    async def log_reflex_entry(self, regime: str, entry_price: float,
                                 entry_combined_score: float) -> int:
        """
        Legt het begin van een BULLISH_REFLEX/BEARISH_REFLEX-episode vast
        (27 aug 2026) -- geeft de nieuwe episode-id terug, die bij het
        uitstappen weer gebruikt wordt om dezelfde rij bij te werken.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO reflex_episodes (regime, entry_price, entry_combined_score) "
                "VALUES ($1, $2, $3) RETURNING id",
                regime, entry_price, entry_combined_score,
            )
            return row["id"]

    async def log_reflex_exit(self, episode_id: int, exit_price: float, exit_reason: str):
        """
        Legt het einde van een reflex-episode vast, en berekent meteen het
        behaalde rendement (27 aug 2026) -- zodat we achteraf, zonder
        aparte berekening, kunnen zien of de overstap nuttig was.
        """
        async with self._pool.acquire() as conn:
            entry_row = await conn.fetchrow(
                "SELECT entry_price FROM reflex_episodes WHERE id = $1", episode_id
            )
            if not entry_row:
                return
            entry_price = entry_row["entry_price"]
            return_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else None

            await conn.execute(
                "UPDATE reflex_episodes SET exit_at = now(), exit_price = $1, "
                "exit_reason = $2, return_pct = $3 WHERE id = $4",
                exit_price, exit_reason, return_pct, episode_id,
            )

    async def save_regime_state(self, current_regime: str, trailing_entry_price: Optional[float],
                                  active_reflex_episode_id: Optional[int],
                                  flash_defense_until: float = 0.0):
        """
        Slaat de actuele regimestatus op (27 aug 2026) -- zodat de bot dit
        na een herstart correct kan herstellen, i.p.v. altijd terug te
        vallen op de default LP_MODE. Verwijdert eerst elke bestaande rij
        -- er hoort er maximaal een te zijn, net als bij active_lp_position.

        flash_defense_until (30 aug 2026): unix-timestamp tot wanneer een
        eventuele flash-verdedigingsperiode loopt -- zonder dit "vergat"
        de bot bij een herstart tijdens een actieve verdediging dat die
        nog liep, en kon het vangnet meteen weer (te vroeg) een nieuwe
        positie proberen te openen.
        """
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM bot_regime_state")
            await conn.execute(
                "INSERT INTO bot_regime_state "
                "(current_regime, trailing_entry_price, active_reflex_episode_id, flash_defense_until) "
                "VALUES ($1, $2, $3, $4)",
                current_regime, trailing_entry_price, active_reflex_episode_id, flash_defense_until,
            )

    async def get_regime_state(self) -> Optional[dict]:
        """Geeft de opgeslagen regimestatus terug, of None als er geen is."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT current_regime, trailing_entry_price, active_reflex_episode_id, "
                "flash_defense_until "
                "FROM bot_regime_state ORDER BY id DESC LIMIT 1"
            )
            return dict(row) if row else None

    async def save_portfolio_value_snapshot(self, total_value_usd: float,
                                              wallet_value_usd: float,
                                              position_value_usd: float):
        """
        Slaat een momentopname van de totale portefeuillewaarde op (1 sep
        2026, op verzoek) -- bedoeld om 1x per dag aangeroepen te worden
        (via daily_status_report.py, dat al via cron om 09:00 draait),
        zodat get_portfolio_value_at() later waarde-verandering over
        dag/week/maand/jaar kan berekenen. In tegenstelling tot
        save_regime_state()/save_active_lp_position(): GEEN bestaande
        rij verwijderen -- dit is een doorlopende, groeiende historie,
        geen enkelvoudige actuele status.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO portfolio_value_history "
                "(total_value_usd, wallet_value_usd, position_value_usd) "
                "VALUES ($1, $2, $3)",
                total_value_usd, wallet_value_usd, position_value_usd,
            )

    async def get_portfolio_value_at(self, days_ago: int) -> Optional[dict]:
        """
        Geeft de DICHTSTBIJZIJNDE opgeslagen momentopname terug van
        ongeveer `days_ago` dagen geleden (1 sep 2026) -- gebruikt de
        rij met de kleinste tijdsafstand tot dat moment, i.p.v. een
        exacte match te vereisen (die zelden zou bestaan, gezien
        snapshots doorgaans 1x per dag op een net-iets-ander tijdstip
        worden opgeslagen). Geeft None terug als er nog geen historie
        ver genoeg terug beschikbaar is.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT total_value_usd, recorded_at FROM portfolio_value_history "
                # BUGFIX (1 sep 2026): "($1 || ' days')::interval" faalde
                # met asyncpg (TypeError: expected str, got int) -- die
                # staat, anders dan een PL/pgSQL-functie, geen impliciete
                # integer-naar-tekst-omzetting toe binnen een
                # parameter-gebonden query. Opgelost met de standaard,
                # type-veilige interval-vermenigvuldiging.
                "ORDER BY ABS(EXTRACT(EPOCH FROM (recorded_at - (now() - ($1 * interval '1 day'))))) "
                "ASC LIMIT 1",
                days_ago,
            )
            return dict(row) if row else None

    async def get_portfolio_value_history_since(self, days: int) -> list[dict]:
        """
        Geeft ALLE opgeslagen momentopnamen terug van de afgelopen
        `days` dagen, oplopend gesorteerd op tijd (1 sep 2026, voor de
        dashboard-grafiek) -- in tegenstelling tot get_portfolio_value_
        at() hierboven (die ÉÉN dichtstbijzijnde rij geeft voor een
        vergelijking), is dit de VOLLEDIGE reeks voor een lijngrafiek.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT total_value_usd, recorded_at FROM portfolio_value_history "
                "WHERE recorded_at >= now() - ($1 * interval '1 day') "
                "ORDER BY recorded_at ASC",
                days,
            )
            return [dict(r) for r in rows]

    async def get_recent_trades(self, limit: int = 30) -> list[dict]:
        """Geeft de meest recente, geslaagde swaps terug (1 sep 2026, voor het dashboard)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT direction, engine, amount_in, actual_amount_out, tx_hash, created_at "
                "FROM trades WHERE status = 'success' "
                "ORDER BY created_at DESC LIMIT $1",
                limit,
            )
            return [dict(r) for r in rows]

    async def get_daily_stats(self, date: Optional[str] = None) -> DailyStats:
        date = date or datetime.now().strftime("%Y-%m-%d")
        async with self._pool.acquire() as conn:
            trade_stats = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'success') AS successful,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed
                FROM trades
                WHERE created_at::date = $1::date
                """,
                date,
            )
            sentiment_stats = await conn.fetchrow(
                """
                SELECT
                    AVG(sentiment_score) FILTER (WHERE asset = 'BTC') AS avg_btc,
                    AVG(sentiment_score) FILTER (WHERE asset = 'HBAR') AS avg_hbar
                FROM sentiment_log
                WHERE created_at::date = $1::date
                """,
                date,
            )
            panic_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM strategy_signals
                WHERE panic_override_triggered = TRUE AND created_at::date = $1::date
                """,
                date,
            )

            return DailyStats(
                total_trades=trade_stats["total"] or 0,
                successful_trades=trade_stats["successful"] or 0,
                failed_trades=trade_stats["failed"] or 0,
                avg_btc_sentiment=float(sentiment_stats["avg_btc"] or 0.0),
                avg_hbar_sentiment=float(sentiment_stats["avg_hbar"] or 0.0),
                panic_overrides_triggered=panic_count or 0,
                # Netto HBAR/USDC-verandering vereist aggregatie over trades
                # met richting -- bewust als TODO gelaten, eenvoudig toe te
                # voegen zodra er echte trade-data is om tegen te valideren.
                net_hbar_change=0.0,
                net_usdc_change=0.0,
            )


if __name__ == "__main__":
    import asyncio

    async def structure_test():
        client = PostgresClient(dsn=os.environ.get("DATABASE_URL"))
        if not client.dsn:
            print("Geen DATABASE_URL gezet -- skip live verbindingstest.")
            print("Module-structuur (publieke methoden):")
            for name in dir(client):
                if not name.startswith("_"):
                    print(f"  - {name}")
            return
        try:
            await client.connect()
            print("Verbonden met Postgres.")
            await client.close()
        except Exception as e:
            print(f"Verbindingsfout (verwacht zonder live database): {e}")

    asyncio.run(structure_test())
