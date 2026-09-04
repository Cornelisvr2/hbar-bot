with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

doelregels = []
for i, regel in enumerate(regels):
    if "self.lp_manager.config.token0, self.lp_manager.config.token1" in regel:
        # Bekijk de volgende 3 regels om te zien wat er als decimalen wordt meegegeven
        context = "".join(regels[i:i+4])
        doelregels.append((i, context))

for i, context in doelregels:
    print(f"=== Regel {i} ===")
    print(context)
    print()
