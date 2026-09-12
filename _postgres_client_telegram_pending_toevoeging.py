# Toevoegen aan de PostgresClient-klasse in postgres_client.py (zelfde stijl/
# conventie als de bestaande methods -- async with self._pool.acquire()).
# Zie migratie_telegram_pending.sql voor de bijbehorende tabel.

    async def create_pending_verzoek(self, vid: str, soort: str, omschrijving: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO telegram_pending_verzoeken (id, soort, omschrijving, status)
                VALUES ($1, $2, $3, 'open')
                """,
                vid, soort, omschrijving,
            )

    async def get_pending_verzoek(self, vid: str) -> Optional[dict]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, soort, omschrijving, status, aangemaakt
                FROM telegram_pending_verzoeken WHERE id = $1
                """,
                vid,
            )
            return dict(row) if row else None

    async def resolve_pending_verzoek(self, vid: str, status: str) -> bool:
        """
        Zet een 'open' verzoek op de gegeven status (goedgekeurd/geweigerd/
        verlopen). Retourneert False als het verzoek niet bestond of al niet
        meer 'open' was -- de WHERE status='open' maakt dit atomisch, zodat
        een dubbele tap (bv. door Telegram-retry) niet twee keer kan
        "slagen".
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE telegram_pending_verzoeken
                SET status = $2
                WHERE id = $1 AND status = 'open'
                RETURNING id
                """,
                vid, status,
            )
            return row is not None
