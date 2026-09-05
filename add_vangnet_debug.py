with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

doelregel = "        seconds_since_last_safetynet_attempt = time.time() - self._last_safetynet_attempt_at\n"
gevonden_op = [i for i, regel in enumerate(regels) if regel == doelregel]
print(f"Aantal exacte matches: {len(gevonden_op)}")

if len(gevonden_op) == 1:
    i = gevonden_op[0]
    debug_regel = (
        '        print(f"[DEBUG-vangnet] regime={self.current_regime}, '
        'lp_manager={self.lp_manager is not None}, '
        'is_open={self.lp_manager.state.is_open if self.lp_manager else \'N/A\'}, '
        'seconds_since={time.time() - self._last_safetynet_attempt_at:.1f}, '
        'cooldown={self.safetynet_retry_cooldown_seconds}")\n'
    )
    regels.insert(i, debug_regel)
    with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
        f.writelines(regels)
    print("Diagnostische regel toegevoegd.")
else:
    print("WAARSCHUWING: geen unieke match.")
