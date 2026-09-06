with open("/root/hbar_bot/mainnet_migratieplan.md", "a") as f:
    f.write("""

## Te bouwen: nauwkeurige Fees-APR via tick-bereik-liquiditeit (6 sep 2026)

Onze huidige `compute_fees_apr()` gebruikt de TOTALE pool-TVL als
noemer (L_bal), wat een SYSTEMATISCHE ONDERSCHATTING geeft t.o.v.
SaucerSwap's eigen weergave (9,4% bij ons vs. 30,96% Fees-APR in hun
eigen interface, voor dezelfde pool op hetzelfde moment).

BEVESTIGD via SaucerSwap's officiele documentatie
(docs.saucerswap.finance/protocol/saucerswap-v2): hun formule
gebruikt L_bal = de liquiditeit GEAGGREGEERD over een specifiek,
gedefinieerd "balanced"-tickbereik, NIET de totale pool-liquiditeit.

Voor onze fee-tier (1500 = 0,15%) is dat bereik EXACT gedefinieerd:
**+/- 9,00% prijsrange = +/- 900 ticks rond de huidige, actieve tick.**

### Wat te bouwen
Een functie die, gegeven de huidige tick en de pool zelf, de
liquiditeit AGGREGEERT over het venster [huidige_tick - 900,
huidige_tick + 900] -- dit vereist het doorlopen van de pool's
tick-bitmap en het optellen van `liquidityNet`-waarden binnen dat
venster (standaard Uniswap V3-mechanisme, niet SaucerSwap-specifiek --
er bestaat waarschijnlijk al bruikbare Uniswap V3-SDK-achtige
Python-code hiervoor, of het is met de bestaande Solidity-ABI
(tickBitmap() + ticks()-functies op het pool-contract) zelf te bouwen).

### Referentietabel (uit de officiele docs, voor ALLE fee-tiers)
| Fee tier | Balanced-prijsrange | Balanced-tickrange |
|----------|---------------------|---------------------|
| 0.05%    | +/- 1.00%           | +/- 100 ticks       |
| 0.15%    | +/- 9.00%           | +/- 900 ticks       |
| 0.30%    | +/- 15.00%          | +/- 1,500 ticks     |
| 1.00%    | +/- 30.00%          | +/- 3,000 ticks     |

### Prioriteit
Laag risico (puur een rapportagecijfer, geen invloed op kapitaal-
veiligheid of handelslogica), maar wel gewenst voor een correct beeld
van de daadwerkelijke, haalbare rendement-verwachting.
""")
print("Notitie toegevoegd.")
