with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

doelregel = "        if (time.time() - self._last_capital_deploy_at) < self.deploy_capital_cooldown_seconds:\n"
gevonden_op = [i for i, regel in enumerate(regels) if regel == doelregel]
print(f"Aantal exacte matches: {len(gevonden_op)}")

if len(gevonden_op) == 1:
    i = gevonden_op[0]
    regels[i] = (
        "        if (not bypass_cooldown and "
        "(time.time() - self._last_capital_deploy_at) < self.deploy_capital_cooldown_seconds):\n"
    )
    with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
        f.writelines(regels)
    print("Correct bijgewerkt, regel-gebaseerd.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
    for i, regel in enumerate(regels):
        if "deploy_capital_cooldown_seconds" in regel and "if" in regel:
            print(f"Regel {i}: {repr(regel)}")
