with open("/root/hbar_bot/regime_orchestrator.py", "r") as f:
    regels = f.readlines()

doelregel = "            deployable_hbar = max(0.0, total_hbar_balance - reserve_hbar)\n"
gevonden_op = [i for i, regel in enumerate(regels) if regel == doelregel]
print(f"Aantal exacte matches: {len(gevonden_op)}")

if len(gevonden_op) == 1:
    i = gevonden_op[0]
    debug_regel = (
        '            print(f"[DEBUG-vangnet2] total_hbar_balance={total_hbar_balance:.4f}, '
        'reserve_hbar={reserve_hbar:.4f}, deployable_hbar={deployable_hbar:.4f}")\n'
    )
    regels.insert(i + 1, debug_regel)
    with open("/root/hbar_bot/regime_orchestrator.py", "w") as f:
        f.writelines(regels)
    print("Diagnostische regel toegevoegd.")
else:
    print("WAARSCHUWING: geen unieke match.")
