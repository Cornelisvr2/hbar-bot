"""
Herziene test (6 sep 2026): de vorige test gebruikte een smalle range
waar de positie zelf al bijna 100% HBAR wil -- daardoor leek "2000
HBAR + 0 USDC" ten onrechte als "geen swap nodig". Deze versie
gebruikt een brede, gecentreerde range (+/-20% rond de prijs) waar de
natuurlijke verhouding dicht bij 50/50 ligt -- zodat de kritieke,
eenzijdige scenario's zinvol getest worden.
"""
import sys, math
from unittest.mock import MagicMock
sys.path.insert(0, "/root/hbar_bot")
from lp_manager import LpManager, LpPositionConfig, price_to_tick

ADRES_KLEIN = "0x0000000000000000000000000000000000000100"
ADRES_GROOT = "0x0000000000000000000000000000000000163b5a"

config = LpPositionConfig(
    position_manager_address="0x0",
    token0=ADRES_KLEIN, token1=ADRES_GROOT,
    whbar_address=ADRES_GROOT,
    token0_decimals=6, token1_decimals=8,
)
lp = LpManager(MagicMock(), config)

prijs_mensvriendelijk = 0.08  # USDC per HBAR
prijs = 1 / prijs_mensvriendelijk  # canoniek, WHBAR per USDC
# Brede, symmetrische range rond de prijs (+/-20%) -- prijs zit
# ongeveer in het midden, dus de natuurlijke verhouding moet dicht
# bij 50/50 (in waarde) liggen.
tick_lower = price_to_tick(prijs * 0.83, 6, 8)
tick_upper = price_to_tick(prijs * 1.20, 6, 8)
print(f"Range: ticks {tick_lower} -- {tick_upper} (prijs-canoniek {prijs:.4f})")

def toon(label, hbar_h, usdc_h):
    hbar_raw = int(hbar_h * 10**8)
    usdc_raw = int(usdc_h * 10**6)
    richting, bedrag_raw = lp.compute_optimal_swap_for_position(hbar_raw, usdc_raw, prijs, tick_lower, tick_upper)
    print(f"\n{label}")
    print(f"  Start: {hbar_h:.4f} HBAR + {usdc_h:.4f} USDC")
    if richting is None:
        print(f"  Resultaat: geen swap nodig")
    elif richting == "HBAR_TO_USDC":
        print(f"  Resultaat: swap {bedrag_raw/10**8:.4f} HBAR -> USDC")
    else:
        print(f"  Resultaat: swap {bedrag_raw/10**6:.4f} USDC -> HBAR")
    return richting, bedrag_raw

print("\n" + "=" * 70)
print("SCENARIO 1 (KRITIEK): 100% eenzijdig in HBAR (na BULLISH_REFLEX)")
print("=" * 70)
richting, bedrag = toon("Volledig in HBAR, nul USDC", 2000.0, 0.0)
assert richting == "HBAR_TO_USDC" and bedrag > 0, f"MISLUKT: kreeg ({richting}, {bedrag})"
print("  >>> GESLAAGD <<<")

print("\n" + "=" * 70)
print("SCENARIO 2 (KRITIEK): 100% eenzijdig in USDC (na BEARISH_REFLEX)")
print("=" * 70)
richting, bedrag = toon("Volledig in USDC, nul HBAR", 0.0, 200.0)
assert richting == "USDC_TO_HBAR" and bedrag > 0, f"MISLUKT: kreeg ({richting}, {bedrag})"
print("  >>> GESLAAGD <<<")

print("\n" + "=" * 70)
print("SCENARIO 3: al perfect gebalanceerd")
print("=" * 70)
perfecte_usdc_raw = lp.compute_needed_usdc_for_hbar(1000_00000000, prijs, tick_lower, tick_upper)
richting, bedrag = toon("Precies de juiste verhouding", 1000.0, perfecte_usdc_raw / 10**6)
assert richting is None, f"MISLUKT: verwachtte geen swap, kreeg ({richting}, {bedrag})"
print("  >>> GESLAAGD <<<")

print("\n" + "=" * 70)
print("SCENARIO 4: controle -- na de voorgestelde swap, klopt de verhouding dan?")
print("=" * 70)
hbar_h, usdc_h = 2000.0, 0.0
richting, bedrag_raw = lp.compute_optimal_swap_for_position(
    int(hbar_h*10**8), int(usdc_h*10**6), prijs, tick_lower, tick_upper
)
swap_hbar_h = bedrag_raw / 10**8
nieuw_hbar_h = hbar_h - swap_hbar_h
nieuw_usdc_h = usdc_h + swap_hbar_h * prijs_mensvriendelijk
benodigd_usdc_na_swap_raw = lp.compute_needed_usdc_for_hbar(
    int(nieuw_hbar_h * 10**8), prijs, tick_lower, tick_upper
)
benodigd_usdc_na_swap_h = benodigd_usdc_na_swap_raw / 10**6
print(f"  Na swap: {nieuw_hbar_h:.4f} HBAR + {nieuw_usdc_h:.4f} USDC (werkelijk)")
print(f"  Positie zou willen: {nieuw_hbar_h:.4f} HBAR + {benodigd_usdc_na_swap_h:.4f} USDC (ideaal)")
verschil_pct = abs(nieuw_usdc_h - benodigd_usdc_na_swap_h) / benodigd_usdc_na_swap_h * 100
print(f"  Afwijking: {verschil_pct:.3f}%")
assert verschil_pct < 1.0, "Verhouding klopt niet na de voorgestelde swap"
print("  >>> GESLAAGD: de voorgestelde swap leidt daadwerkelijk tot de juiste verhouding. <<<")

print("\n" + "=" * 70)
print("ALLE TESTS GESLAAGD.")
print("=" * 70)
