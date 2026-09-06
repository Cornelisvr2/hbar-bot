"""
Pure rekentest (geen transacties, geen netwerkverbinding) om te
verifiëren dat compute_needed_usdc_for_hbar/compute_needed_hbar_for_usdc
correct werken in BEIDE scenario's: testnet-achtig (WHBAR=token0) en
mainnet-achtig (USDC=token0) -- zonder dat we het risico lopen dit
tegen echte fondsen te testen.
"""
import sys
from unittest.mock import MagicMock
sys.path.insert(0, "/root/hbar_bot")
from lp_manager import LpManager, LpPositionConfig, compute_amount0_for_amount1, compute_amount1_for_amount0

# Realistische, fictieve adressen -- LET OP: puur voor deze rekentest,
# de numerieke volgorde bepaalt welke "kleinste" is (canoniek token0).
ADRES_KLEIN = "0x0000000000000000000000000000000000000100"   # kleinste
ADRES_GROOT = "0x0000000000000000000000000000000000163b5a"   # grootste

print("=" * 70)
print("SCENARIO 1: testnet-achtig (WHBAR is toevallig de kleinste, dus token0)")
print("=" * 70)
config_testnet = LpPositionConfig(
    position_manager_address="0x0",
    token0=ADRES_KLEIN,  # WHBAR
    token1=ADRES_GROOT,  # USDC
    whbar_address=ADRES_KLEIN,
    token0_decimals=8,   # WHBAR
    token1_decimals=6,   # USDC
)
lp_testnet = LpManager(MagicMock(), config_testnet)

prijs = 0.08  # USDC per HBAR, canoniek EN semantisch identiek hier
tick_lower, tick_upper = -71700, -70680  # zelfde range als eerdere, succesvolle test
hbar_raw = 250_00000000  # 250 HBAR, 8 decimalen

nieuw_resultaat = lp_testnet.compute_needed_usdc_for_hbar(hbar_raw, prijs, tick_lower, tick_upper)
oud_resultaat = compute_amount1_for_amount0(hbar_raw, prijs, tick_lower, tick_upper, 8, 6)
print(f"Nieuwe methode:  {nieuw_resultaat}")
print(f"Oude aanroep:    {oud_resultaat}")
print(f"IDENTIEK: {nieuw_resultaat == oud_resultaat}")

print()
print("=" * 70)
print("SCENARIO 2: mainnet-achtig (USDC is de kleinste, dus token0 -- WHBAR is token1)")
print("=" * 70)
config_mainnet = LpPositionConfig(
    position_manager_address="0x0",
    token0=ADRES_KLEIN,  # USDC (nu de kleinste!)
    token1=ADRES_GROOT,  # WHBAR
    whbar_address=ADRES_GROOT,  # LET OP: nu is WHBAR het GROTE adres
    token0_decimals=6,   # USDC
    token1_decimals=8,   # WHBAR
)
lp_mainnet = LpManager(MagicMock(), config_mainnet)

# Zelfde prijs/range/hbar_raw als hierboven, maar nu in de CANONIEKE
# schaal (token1_per_token0 = WHBAR_per_USDC = 1/0.08 = 12.5)
prijs_canoniek = 1 / prijs
# De range moet ook in canonieke termen -- gebruik de spiegel-ticks
tick_lower_canoniek, tick_upper_canoniek = -tick_upper, -tick_lower

nieuw_resultaat2 = lp_mainnet.compute_needed_usdc_for_hbar(
    hbar_raw, prijs_canoniek, tick_lower_canoniek, tick_upper_canoniek
)
print(f"Nieuwe methode (mainnet-achtig): {nieuw_resultaat2}")
print(f"Verwacht: in dezelfde GROOTTEORDE als scenario 1 ({oud_resultaat}), NIET biljoenen")
verschil_pct = abs(nieuw_resultaat2 - oud_resultaat) / oud_resultaat * 100
print(f"Verschil t.o.v. scenario 1: {verschil_pct:.2f}% (kleine afwijking door tick-afronding is normaal)")

if nieuw_resultaat2 > 0 and nieuw_resultaat2 < oud_resultaat * 10:
    print("\n>>> GESLAAGD: resultaat is redelijk, geen absurd getal. <<<")
else:
    print("\n>>> WAARSCHUWING: resultaat lijkt nog steeds onredelijk -- verder onderzoek nodig. <<<")
