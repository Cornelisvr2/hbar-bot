with open("/root/hbar_bot/dashboard_server.py", "r") as f:
    inhoud = f.read()

oud = "pool_apr = compute_fees_apr(snapshot.volume_24h_usd, 3000, snapshot.liquidity_usd)"
nieuw = ("fee_tier = int(os.environ.get(\"LP_FEE_TIER\", \"3000\"))  # BUGFIX (5 sep 2026, "
         "systematische audit): was hardgecodeerd op 3000, ongeacht de daadwerkelijke pool-fee-tier (1500 op mainnet)\n"
         "        pool_apr = compute_fees_apr(snapshot.volume_24h_usd, fee_tier, snapshot.liquidity_usd)")

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/dashboard_server.py", "w") as f:
        f.write(inhoud)
    print("Bijgewerkt.")
else:
    print("WAARSCHUWING: geen unieke match.")
