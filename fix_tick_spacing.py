with open("/root/hbar_bot/lp_manager.py", "r") as f:
    inhoud = f.read()

oud = """DEFAULT_TICK_SPACING_BY_FEE = {
    100: 1,      # 0.01%
    500: 10,     # 0.05%
    3000: 60,    # 0.3%
    10000: 200,  # 1%
}"""

nieuw = """DEFAULT_TICK_SPACING_BY_FEE = {
    100: 1,      # 0.01%
    500: 10,     # 0.05%
    1500: 30,    # 0.15% -- SaucerSwap-specifieke fee-tier (geen standaard
                 # Uniswap V3-waarde), bevestigd via de mainnet-factory's
                 # eigen feeAmountTickSpacing() (4 sep 2026, tijdens de
                 # mainnet-migratie -- dit is de fee-tier van de daadwerkelijke,
                 # liquide WHBAR/USDC-pool)
    3000: 60,    # 0.3%
    10000: 200,  # 1%
}"""

aantal = inhoud.count(oud)
print(f"Aantal gevonden matches: {aantal}")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/lp_manager.py", "w") as f:
        f.write(inhoud)
    print("Correct bijgewerkt.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
