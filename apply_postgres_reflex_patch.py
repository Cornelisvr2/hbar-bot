"""Kleine, gerichte patch: voegt log_reflex_entry() en log_reflex_exit()
toe aan postgres_client.py, zonder het hele bestand opnieuw te plakken."""

with open("postgres_client.py", "r") as f:
    content = f.read()

old = '''    async def clear_active_lp_position(self):
        """Verwijdert de opgeslagen actieve LP-positie (bij het sluiten ervan)."""
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM active_lp_position")

'''

new = '''    async def clear_active_lp_position(self):
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

'''

assert content.count(old) == 1, f"gevonden: {content.count(old)} matches (verwacht: 1)"
content = content.replace(old, new)

with open("postgres_client.py", "w") as f:
    f.write(content)

print("Patch succesvol toegepast.")
