"""
Systematische audit (5 sep 2026, op verzoek) -- doorzoekt alle actief
gebruikte bestanden op de bekende risico-patronen die vandaag herhaaldelijk
tot bugs leidden bij de mainnet-migratie:

1. Hardgecodeerde testnet-adressen/waarden (bv. het testnet-SAUCE-adres)
2. resolve_testnet_*() aangeroepen ZONDER een HEDERA_NETWORK-check ernaast
3. Hardgecodeerde fee_tier=3000 (i.p.v. uit config/env gelezen)
4. price_to_tick/tick_to_price/compute_amount0_for_amount1/
   compute_amount1_for_amount0/compute_position_amounts aangeroepen met
   self._hbar_decimals/self._usdc_decimals (semantisch) i.p.v.
   lp.config.token0_decimals/token1_decimals (canoniek) -- of andersom,
   afhankelijk van of ze gekoppeld zijn aan canonieke of semantische ticks
5. get_live_pool_price() aangeroepen met lp.config.token0/token1
   (canoniek) waar een semantische (whbar/usdc) prijs bedoeld is
6. Losse, hardgecodeerde decimalen-paren (8, 6) of (6, 8) i.p.v. via
   config/constanten
"""
import subprocess

with open("/root/hbar_bot_audit_bestanden.txt") as f:
    bestanden = [regel.strip() for regel in f if regel.strip()]

patronen = {
    "1. Testnet-adres hardgecodeerd (SAUCE 0.0.1183558)": r"0\.0\.1183558",
    "2. resolve_testnet_ zonder schijnbare netwerk-check op dezelfde/vorige regel": r"resolve_testnet_(addresses|v2_addresses)\(\)",
    "3. Hardgecodeerde fee_tier=3000": r"[^_]3000[,)]",
    "4a. price_to_tick/tick_to_price met self\\._hbar_decimals": r"(price_to_tick|tick_to_price)\([^)]*self\._hbar_decimals",
    "4b. compute_amount.*_for_amount.* met self\\._hbar_decimals": r"compute_amount\d_for_amount\d\([^)]*\n?[^)]*self\._hbar_decimals",
    "4c. compute_position_amounts met self\\._hbar_decimals": r"compute_position_amounts\([^)]*\n?[^)]*self\._hbar_decimals",
    "5. get_live_pool_price met lp.config.token0/token1 (canoniek)": r"get_live_pool_price\([^)]*config\.token0",
    "6. Losse (8, 6) of (6, 8) decimalen-paren": r"[^.\w](8, 6|6, 8)[,)]",
}

import re
for label, patroon in patronen.items():
    print(f"\n{'='*70}")
    print(f"PATROON: {label}")
    print('='*70)
    for bestand in bestanden:
        pad = f"/root/hbar_bot/{bestand}"
        try:
            with open(pad, "r") as f:
                inhoud = f.read()
        except FileNotFoundError:
            continue
        for m in re.finditer(patroon, inhoud, re.MULTILINE):
            regelnummer = inhoud[:m.start()].count("\n") + 1
            regel_inhoud = inhoud.split("\n")[regelnummer - 1].strip()
            print(f"  {bestand}:{regelnummer}: {regel_inhoud[:100]}")
