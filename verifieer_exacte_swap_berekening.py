"""
Test compute_optimal_swap_for_position() in vier scenario's, inclusief
de EXACT door de gebruiker beschreven kritieke gevallen: 100%
eenzijdig kapitaal in beide richtingen -- de scenario's waarin de
OUDE "helft van het tekort"-heuristiek nooit zou slagen.
"""
import sys
from unittest.mock import MagicMock
sys.path.insert(0, "/root/hbar_bot")
from lp_manager import LpManager, LpPositionConfig

ADRES_KLEIN = "0x0000000000000000000000000000000000000100"
ADRES_GROOT = "0x0000000000000000000000000000000000163b5a"

config = LpPositionConfig(
    position_manager_address="0x0",
    token0=ADRES_KLEIN,   # USDC (mainnet-achtig: USDC is de kleinste)
    token1=ADRES_GROOT,   # WHBAR
    whbar_address=ADRES_GROOT,
    token0_decimals=6,    # USDC
    token1_decimals=8,    # WHBAR
)
lp = LpManager(MagicMock(), config)

prijs = 1 / 0.08  # canoniek, WHBAR per USDC (12.5)
tick_lower, tick_upper = 69270, 71370  # zelfde range als de live mainnet-poging

def toon(label, hbar_h, usdc_h):
    hbar_raw = int(hbar_h * 10**8)
    usdc_raw = int(usdc_h * 10**6)
    richting, bedrag_raw = lp.compute_optimal_swap_for_position(hbar_raw, usdc_raw, prijs, tick_lower, tick_upper)
    print(f"\n{label}")
    print(f"  Start: {hbar_h:.4f} HBAR + {usdc_h:.4f} USDC")
    if richting is None:
        print(f"  Resultaat: geen swap nodig (al voldoende gebalanceerd)")
    elif richting == "HBAR_TO_USDC":
        print(f"  Resultaat: swap {bedrag_raw/10**8:.4f} HBAR -> USDC")
    else:
        print(f"  Resultaat: swap {bedrag_raw/10**6:.4f} USDC -> HBAR")
    return richting, bedrag_raw

print("=" * 70)
print("SCENARIO 1: onze daadwerkelijke, huidige mainnet-situatie")
print("=" * 70)
toon("Huidige wallet-inhoud", 2065.3832, 23.1721)

print()
print("=" * 70)
print("SCENARIO 2 (KRITIEK): 100% eenzijdig in HBAR (na BULLISH_REFLEX)")
print("=" * 70)
richting, bedrag = toon("Volledig in HBAR, nul USDC", 2000.0, 0.0)
assert richting == "HBAR_TO_USDC", "MOET een HBAR->USDC-swap voorstellen"
assert bedrag > 0, "Bedrag moet positief zijn"
print("  >>> GESLAAGD: een concreet, uitvoerbaar swap-bedrag werd berekend. <<<")

print()
print("=" * 70)
print("SCENARIO 3 (KRITIEK): 100% eenzijdig in USDC (na BEARISH_REFLEX)")
print("=" * 70)
richting, bedrag = toon("Volledig in USDC, nul HBAR", 0.0, 200.0)
assert richting == "USDC_TO_HBAR", "MOET een USDC->HBAR-swap voorstellen"
assert bedrag > 0, "Bedrag moet positief zijn"
print("  >>> GESLAAGD: een concreet, uitvoerbaar swap-bedrag werd berekend. <<<")

print()
print("=" * 70)
print("SCENARIO 4: al perfect gebalanceerd -- geen swap nodig")
print("=" * 70)
# Bereken eerst wat de perfecte verhouding is, test dan of DIE geen swap triggert
_, test_usdc_needed_raw = lp.compute_needed_usdc_for_hbar(1000_00000000, prijs, tick_lower, tick_upper), None
perfecte_usdc_raw = lp.compute_needed_usdc_for_hbar(1000_00000000, prijs, tick_lower, tick_upper)
richting, bedrag = toon("Precies de juiste verhouding", 1000.0, perfecte_usdc_raw / 10**6)
assert richting is None, "Zou GEEN swap moeten voorstellen bij een al-perfecte verhouding"
print("  >>> GESLAAGD: correct herkend dat geen swap nodig is. <<<")

print("\n" + "=" * 70)
print("ALLE TESTS GESLAAGD.")
print("=" * 70)
