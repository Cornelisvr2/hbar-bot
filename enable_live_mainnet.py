with open("/root/hbar_bot/.env", "r") as f:
    inhoud = f.read()

inhoud = inhoud.replace("DRY_RUN=true", "DRY_RUN=false")

with open("/root/hbar_bot/.env", "w") as f:
    f.write(inhoud)

with open("/root/hbar_bot/.env", "r") as f:
    for regel in f:
        if regel.startswith(("HEDERA_NETWORK", "DRY_RUN", "LP_FEE_TIER")):
            print(regel.strip())
