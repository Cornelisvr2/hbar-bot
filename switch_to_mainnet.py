# --- .env bijwerken ---
with open("/root/hbar_bot/.env", "r") as f:
    env_inhoud = f.read()

env_inhoud = env_inhoud.replace("HEDERA_NETWORK=testnet", "HEDERA_NETWORK=mainnet")
env_inhoud = env_inhoud.replace("DRY_RUN=false", "DRY_RUN=true")
if "LP_FEE_TIER" not in env_inhoud:
    env_inhoud = env_inhoud.replace(
        "HEDERA_NETWORK=mainnet",
        "HEDERA_NETWORK=mainnet\nLP_FEE_TIER=1500",
    )

with open("/root/hbar_bot/.env", "w") as f:
    f.write(env_inhoud)
print("--- .env bijgewerkt ---")

# --- config.py bijwerken ---
with open("/root/hbar_bot/config.py", "r") as f:
    config_inhoud = f.read()

oud = 'HEDERA_NETWORK = "testnet"  # \'testnet\' of \'mainnet\''
nieuw = 'HEDERA_NETWORK = "mainnet"  # \'testnet\' of \'mainnet\''
aantal = config_inhoud.count(oud)
print(f"config.py -- aantal matches: {aantal}")
if aantal == 1:
    config_inhoud = config_inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/config.py", "w") as f:
        f.write(config_inhoud)
    print("config.py bijgewerkt.")
else:
    print("WAARSCHUWING: geen unieke match in config.py -- NIET aangepast.")

# --- Bevestiging ---
print("\n--- Verificatie ---")
with open("/root/hbar_bot/.env", "r") as f:
    for regel in f:
        if regel.startswith(("HEDERA_NETWORK", "DRY_RUN", "LP_FEE_TIER")):
            print(f".env: {regel.strip()}")
with open("/root/hbar_bot/config.py", "r") as f:
    for regel in f:
        if regel.startswith("HEDERA_NETWORK"):
            print(f"config.py: {regel.strip()}")
