with open("/root/hbar_bot/mainnet_migratieplan.md", "r") as f:
    inhoud = f.read()

oud = "1. **Fee-tier van de mainnet-pool bevestigen** — momenteel een aanname (3000, zoals testnet) in `swap_executor_v2.py`. Rechtstreeks bij de pool zelf opvragen (`fee()`-call) vóór де eerste transactie."
nieuw = """1. ~~Fee-tier van de mainnet-pool bevestigen~~ **BEVESTIGD (4 sep 2026)**: de daadwerkelijke fee-tier is **1500 (0,15%)**, NIET de aanname van 3000 (0,30%) die voor testnet gold. De bot leest dit via de omgevingsvariabele `LP_FEE_TIER` (regime_orchestrator.py, regel 430) -- geen codewijziging nodig, alleen instellen in `.env`:
   ```
   LP_FEE_TIER=1500
   ```"""

aantal = inhoud.count(oud)
print(f"Aantal gevonden matches: {aantal}")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/mainnet_migratieplan.md", "w") as f:
        f.write(inhoud)
    print("Correct bijgewerkt.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
