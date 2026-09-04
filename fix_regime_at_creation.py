with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

nieuwe_regels = []
verwijderd = 0
for regel in regels:
    if regel.strip().startswith("regime_at_creation=self._cached_volatility_regime.value"):
        verwijderd += 1
        continue  # deze regel overslaan, dus effectief verwijderen
    nieuwe_regels.append(regel)

print(f"Aantal verwijderde regels: {verwijderd} (moet 4 zijn)")

with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
    f.writelines(nieuwe_regels)
