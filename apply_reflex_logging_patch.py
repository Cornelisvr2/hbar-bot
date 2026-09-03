"""Kleine, gerichte patch: voegt de reflex-episode-logging toe aan
regime_orchestrator.py, zonder het hele bestand opnieuw te hoeven plakken."""

with open("regime_orchestrator.py", "r") as f:
    content = f.read()

# Wijziging 1: nieuw state-veld toevoegen
old_1 = '''        self.current_regime = Regime.LP_MODE
        self.trailing_tracker: Optional[TrailingStopTracker] = None
        # Voorkomt een ongecontroleerde herhaal-lus (26 aug 2026, empirisch'''

new_1 = '''        self.current_regime = Regime.LP_MODE
        self.trailing_tracker: Optional[TrailingStopTracker] = None
        # Actieve reflex-episode-id (27 aug 2026) -- None zolang we in
        # LP_MODE zitten, anders de id van de rij in reflex_episodes die
        # bij het uitstappen wordt afgesloten met de uitstapprijs.
        self._active_reflex_episode_id: Optional[int] = None
        # Voorkomt een ongecontroleerde herhaal-lus (26 aug 2026, empirisch'''

assert content.count(old_1) == 1, f"Wijziging 1: {content.count(old_1)} matches (verwacht: 1)"
content = content.replace(old_1, new_1)

# Wijziging 2: episode-logging toevoegen bij een geslaagde overgang
old_2 = '''            return

        transition_succeeded = await self._execute_transition(target_regime, current_price, signal_id)
        self._last_transition_at = time.time()

        if transition_succeeded:
            self.current_regime = target_regime
        # Bij falen: current_regime blijft bewust ongewijzigd (de vorige,'''

new_2 = '''            return

        previous_regime = self.current_regime  # nodig om exit correct te loggen, voor overschrijven
        transition_succeeded = await self._execute_transition(target_regime, current_price, signal_id)
        self._last_transition_at = time.time()

        if transition_succeeded:
            # Reflex-episode-logging (27 aug 2026): exit loggen als we een
            # reflex-regime VERLATEN, entry loggen als we er een INSTAPPEN.
            # Beide kunnen in dezelfde overgang gebeuren (bv. bearish_reflex
            # -> bullish_reflex, zonder tussenstop in LP_MODE).
            if previous_regime in (Regime.BULLISH_REFLEX, Regime.BEARISH_REFLEX) \\
                    and self._active_reflex_episode_id is not None:
                exit_reason = "trailing_stop" if is_profit_take else "sentiment_reverted"
                await self.db.log_reflex_exit(
                    self._active_reflex_episode_id, current_price, exit_reason
                )
                self._active_reflex_episode_id = None

            if target_regime in (Regime.BULLISH_REFLEX, Regime.BEARISH_REFLEX):
                self._active_reflex_episode_id = await self.db.log_reflex_entry(
                    target_regime.value, current_price, combined_score
                )

            self.current_regime = target_regime
        # Bij falen: current_regime blijft bewust ongewijzigd (de vorige,'''

assert content.count(old_2) == 1, f"Wijziging 2: {content.count(old_2)} matches (verwacht: 1)"
content = content.replace(old_2, new_2)

with open("regime_orchestrator.py", "w") as f:
    f.write(content)

print("Beide wijzigingen succesvol toegepast.")
