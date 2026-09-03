"""
lp_manager.py

Actief beheer van een concentrated liquidity positie in de SaucerSwap V2
HBAR/USDC-pool, specifiek voor gebruik tijdens HOLD-signalen van de
strategy_engine (rustige/neutrale sentiment-periodes). Vult het concept
in dat in PLAN.md als "later" stond genoteerd, nu gescopet naar het
enige paar dat we gebruiken: HBAR/USDC.

Kernidee (Gemini-gesprek, "Uithoudingsvermogen"-module):
- Bij HOLD: open een smalle liquiditeitspositie rond de huidige prijs
- Monitor of de prijs uit de marge loopt -> zo ja: positie sluiten,
  herbalanceren, nieuwe positie rond de nieuwe prijs
- Bij een sterk sentiment-signaal (BUY/SELL of paniek-override):
  EERST de LP-positie intrekken, dan pas de swap uitvoeren -- anders
  zit kapitaal vast in de pool tijdens een crash

BELANGRIJK -- V2 CLMM werkt met 'ticks', niet met simpele prijzen. Een
tick-index correspondeert met een specifieke prijs via de formule
price = 1.0001^tick. Deze module rekent dit voor je om, maar het
tickSpacing van de pool (afhankelijk van de fee-tier) moet kloppen --
zie DEFAULT_TICK_SPACING_BY_FEE hieronder, geverifieerd tegen Uniswap
V3's standaardwaarden (SaucerSwap V2 is een 1-op-1 fork daarvan).
"""

import math
import time
import statistics
import requests
from dataclasses import dataclass
from typing import Optional, List, Tuple
from enum import Enum

from hedera_rpc_client import HederaRpcClient


class VolatilityRegime(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


# Range-breedte per regime -- periodiek herzien (bv. elke paar uur), niet
# continu op elke prijsbeweging. Zie compute_volatility_regime().
RANGE_WIDTH_BY_REGIME = {
    # Geijkt op SaucerSwap's officiele "Focused/Balanced/Relaxed"-presets
    # voor fee-tier 3000 (0.30%), zie docs.saucerswap.finance/protocol/
    # saucerswap-v2 (26 aug 2026) -- i.p.v. eigen, ongekalibreerde
    # schattingen.
    VolatilityRegime.LOW: 0.05,     # "Focused": maximale fee-opbrengst
    VolatilityRegime.NORMAL: 0.15,  # "Balanced": weekly-volatiliteit + marge
    VolatilityRegime.HIGH: 0.30,    # "Relaxed": lange-termijn-trends, minst onderhoud
}

# Drempels op basis van rolling standaarddeviatie van uurrendementen.
# Zelfde soort aanpak als coingecko_client.py's beta-berekening, maar dan
# voor volatiliteit i.p.v. correlatie.
VOLATILITY_LOW_THRESHOLD = 0.01   # <1% stdev per uur
VOLATILITY_HIGH_THRESHOLD = 0.03  # >3% stdev per uur


def compute_volatility_regime(hourly_returns: List[float]) -> VolatilityRegime:
    """
    hourly_returns: recente uurrendementen (bv. laatste 24-48u).
    Bepaalt in welk regime we zitten -- bedoeld om periodiek (elke paar
    uur) aangeroepen te worden, niet bij elke prijs-poll, om overmatig
    herbalanceren te voorkomen.

    LET OP (27 aug 2026): deze functie kijkt ALLEEN naar marktvolatiliteit,
    niet naar economie (kapitaalgrootte, herbalancerings-kosten). Voor de
    daadwerkelijke regime-selectie in de levende bot gebruikt
    select_optimal_volatility_regime() hieronder, die WEL rekening houdt
    met de economie. Deze functie blijft bestaan als eenvoudiger bouwsteen
    (en voor eventuele toekomstige, andere toepassingen).
    """
    if len(hourly_returns) < 3:
        return VolatilityRegime.NORMAL  # te weinig data, val terug op default

    vol = statistics.pstdev(hourly_returns)

    if vol < VOLATILITY_LOW_THRESHOLD:
        return VolatilityRegime.LOW
    elif vol > VOLATILITY_HIGH_THRESHOLD:
        return VolatilityRegime.HIGH
    else:
        return VolatilityRegime.NORMAL


def simulate_rebalance_frequency(prices: List[float], width: float) -> Tuple[int, float]:
    """
    Simuleert: begin een range gecentreerd op de eerste prijs, loop door
    de historische prijzen, en tel hoe vaak de prijs de range verlaat
    (= een herbalancering, waarna een NIEUWE range wordt gestart
    gecentreerd op de prijs op dat moment).

    Geeft (aantal_herbalanceringen, gemiddelde_cyclusduur_in_uren) terug.

    Verplaatst vanuit analyze_range_width.py (27 aug 2026) naar hier, als
    herbruikbare bouwsteen voor zowel handmatige analyse als de levende
    economisch-bewuste regime-selectie hieronder.
    """
    if not prices:
        return 0, 0.0

    rebalance_count = 0
    cycle_lengths = []
    cycle_start_idx = 0
    center_price = prices[0]
    lower_bound = center_price * (1 - width)
    upper_bound = center_price * (1 + width)

    for i, price in enumerate(prices):
        if price < lower_bound or price > upper_bound:
            rebalance_count += 1
            cycle_lengths.append(i - cycle_start_idx)
            cycle_start_idx = i
            center_price = price
            lower_bound = center_price * (1 - width)
            upper_bound = center_price * (1 + width)

    avg_cycle_hours = (sum(cycle_lengths) / len(cycle_lengths)) if cycle_lengths else len(prices)
    return rebalance_count, avg_cycle_hours


def estimate_fee_apr_for_width(width: float, known_fee_apr_at_width: float = 0.0161,
                                 known_width: float = 0.15) -> float:
    """
    Schaalt een bekende, empirisch gemeten fee-APR (standaard: 1.61% bij
    15%-breedte, GeckoTerminal, mainnet SAUCE/WHBAR 0.3%-pool) naar een
    andere breedte, met de standaard Uniswap-V3-vuistregel: concentratie
    (en dus fee-opbrengst per eenheid kapitaal) is ruwweg omgekeerd
    evenredig met de breedte.

    Verplaatst vanuit analyze_range_width.py (27 aug 2026).
    """
    return known_fee_apr_at_width * (known_width / width)


def compute_il_v2(price_ratio: float) -> float:
    """
    Standaard impermanent-loss-formule voor een volledige-range (V2-stijl)
    positie, bij een prijsverandering met factor price_ratio (P_eind/P_begin).
    Geeft altijd <= 0 terug (verlies t.o.v. gewoon vasthouden).

    Gevalideerd tegen bekende, veelgeciteerde referentiewaarden (27 aug
    2026): bij x2 prijsstijging -5.72%, bij x4 -20.00%.
    """
    if price_ratio <= 0:
        return 0.0
    return (2 * math.sqrt(price_ratio)) / (1 + price_ratio) - 1


def select_optimal_volatility_regime(hourly_prices: List[float], capital_hbar: float,
                                       rebalance_cost_hbar: float = 2.0) -> VolatilityRegime:
    """
    Economisch-bewuste regime-selectie (27 aug 2026, HERZIEN met
    impermanent loss) -- vervangt compute_volatility_regime() als bron
    voor de levende bot. Simuleert, voor elk van LOW/NORMAL/HIGH, een
    volledige cyclus-per-cyclus doorloop (fee-opbrengst, impermanent
    loss EN herbalancerings-kosten) over de meegegeven historische
    prijzen, en kiest het regime met de hoogste verwachte netto winst.

    KRITIEKE HERZIENING (27 aug 2026): de eerdere versie rekende alleen
    fee-opbrengst tegen herbalancerings-kosten, zonder impermanent loss.
    Een volledige backtest (met IL, over twee onafhankelijke periodes)
    liet zien dat dit het beeld compleet omdraaide -- IL schaalt met
    dezelfde concentratiefactor als fees, en overschaduwt bij realistische
    HBAR-volatiliteit de fee-opbrengst ruimschoots bij smallere ranges.
    HIGH (breed) wint in de praktijk vrijwel altijd bij de recente
    HBAR-volatiliteit; de eerdere, IL-loze versie koos ten onrechte
    stelselmatig LOW.

    hourly_prices: historische uurprijzen (dezelfde bron als
    compute_volatility_regime() gebruikt -- via BinanceKlinesClient).
    capital_hbar: huidige, daadwerkelijke wallet-waarde in HBAR-termen.
    """
    if len(hourly_prices) < 10:
        return VolatilityRegime.NORMAL  # te weinig data, val terug op default

    total_days = len(hourly_prices) / 24
    best_regime = VolatilityRegime.NORMAL
    best_net_profit = float("-inf")

    for regime, width in RANGE_WIDTH_BY_REGIME.items():
        concentration_factor = 1 / width
        fee_apr = estimate_fee_apr_for_width(width)

        rebalance_count = 0
        total_il_loss = 0.0
        center_price = hourly_prices[0]
        lower_bound = center_price * (1 - width)
        upper_bound = center_price * (1 + width)

        for price in hourly_prices:
            if price < lower_bound or price > upper_bound:
                price_ratio = price / center_price
                il_v2 = compute_il_v2(price_ratio)
                total_il_loss += capital_hbar * il_v2 * concentration_factor

                rebalance_count += 1
                center_price = price
                lower_bound = center_price * (1 - width)
                upper_bound = center_price * (1 + width)

        fee_income = capital_hbar * fee_apr * (total_days / 365)
        cost = rebalance_count * rebalance_cost_hbar
        net_profit = fee_income + total_il_loss - cost  # total_il_loss is al negatief

        if net_profit > best_net_profit:
            best_net_profit = net_profit
            best_regime = regime

    return best_regime


def evaluate_regime_switch_economics(hourly_prices: List[float], capital_hbar: float,
                                       current_width: float, new_width: float,
                                       rebalance_cost_hbar: float = 2.0,
                                       fee_apr_basislijn: float = 0.0161,
                                       fee_apr_basislijn_breedte: float = 0.15) -> dict:
    """
    NIEUW (1 sep 2026, op verzoek): vergelijkt de verwachte netto-
    opbrengst (fee-inkomsten min impermanent loss min herbalancerings-
    kosten) van de HUIDIGE positie-breedte met een NIEUWE, GBM-
    voorgestelde breedte, over dezelfde historische periode als
    select_optimal_volatility_regime() hierboven gebruikt -- hergebruikt
    exact dezelfde simulatie-aanpak (fee_apr via estimate_fee_apr_for_
    width(), IL via compute_il_v2()).

    Bepaalt of een overstap (sluiten + heropenen, met de bijbehorende
    kosten van 2x rebalance_cost_hbar) daadwerkelijk economisch de
    moeite waard is, niet alleen OF de nieuwe breedte "beter" is in
    isolatie -- gebruikt door RegimeOrchestrator._regime_drift_check()
    in regime_orchestrator.py, die niet langer de discrete LOW/NORMAL/
    HIGH-indeling gebruikt maar rechtstreeks vergelijkt met wat de
    doorlopende GBM-methode nu zou voorstellen.

    BUGFIX (1 sep 2026, gevonden na een vraag over een onverwacht hoge
    -70 HBAR-uitkomst): fee_apr_basislijn/fee_apr_basislijn_breedte zijn
    nu instelbaar, met als DEFAULT nog steeds de oorspronkelijke,
    mainnet-gekalibreerde waarde (1,61% bij 15%-breedte) voor
    achterwaartse compatibiliteit. De AANROEPER (_regime_drift_check())
    geeft nu de LIVE, daadwerkelijk gemeten testnet-pool-APR door --
    de mainnet-basislijn onderschatte de fee-opbrengst op onze huidige,
    veel actievere testnet-pool met een factor ~40x, wat de berekening
    stelselmatig te pessimistisch maakte over een overstap naar een
    smallere, efficiëntere range.

    Args:
        hourly_prices: historische uurprijzen (via BinanceKlinesClient)
        capital_hbar: TOTAAL kapitaal in HBAR-termen (los + in de
                      positie, via RegimeOrchestrator._get_total_
                      capital_hbar())
        current_width: huidige, actieve breedte (fractie, bv. 0.05 = 5%)
        new_width: door GBM voorgestelde nieuwe breedte (fractie)
        rebalance_cost_hbar: geschatte kosten van ÉÉN sluit- of open-
                              transactie, in HBAR
        fee_apr_basislijn: bekende fee-APR bij fee_apr_basislijn_breedte,
                            gebruikt om te schalen naar andere breedtes
        fee_apr_basislijn_breedte: de breedte waarbij fee_apr_basislijn
                                     is gemeten/geldt

    Returns:
        dict met "should_switch" (bool), "net_benefit_hbar" (float,
        positief = overstappen loont), en de twee losse simulatie-
        uitkomsten ter referentie/logging.
    """
    def _simuleer(width: float) -> float:
        concentration_factor = 1 / width
        fee_apr = estimate_fee_apr_for_width(width, fee_apr_basislijn, fee_apr_basislijn_breedte)

        rebalance_count = 0
        total_il_loss = 0.0
        center_price = hourly_prices[0]
        lower_bound = center_price * (1 - width)
        upper_bound = center_price * (1 + width)

        for price in hourly_prices:
            if price < lower_bound or price > upper_bound:
                price_ratio = price / center_price
                il_v2 = compute_il_v2(price_ratio)
                total_il_loss += capital_hbar * il_v2 * concentration_factor
                rebalance_count += 1
                center_price = price
                lower_bound = center_price * (1 - width)
                upper_bound = center_price * (1 + width)

        total_days = len(hourly_prices) / 24
        fee_income = capital_hbar * fee_apr * (total_days / 365)
        cost = rebalance_count * rebalance_cost_hbar
        return fee_income + total_il_loss - cost  # total_il_loss is al negatief

    net_profit_current = _simuleer(current_width)
    net_profit_new = _simuleer(new_width)

    switch_cost_hbar = 2 * rebalance_cost_hbar
    net_benefit_of_switching = (net_profit_new - net_profit_current) - switch_cost_hbar

    return {
        "should_switch": net_benefit_of_switching > 0,
        "net_benefit_hbar": net_benefit_of_switching,
        "net_profit_current_width": net_profit_current,
        "net_profit_new_width": net_profit_new,
        "switch_cost_hbar": switch_cost_hbar,
    }


# Uniswap V3-standaard (SaucerSwap V2 is hierop gebaseerd): elke fee-tier
# hoort bij een vaste tickSpacing. Dit MOET kloppen anders faalt mint().
DEFAULT_TICK_SPACING_BY_FEE = {
    100: 1,      # 0.01%
    500: 10,     # 0.05%
    3000: 60,    # 0.3%
    10000: 200,  # 1%
}

POSITION_MANAGER_ABI = [
    {
        "name": "mint",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [{
            "name": "params", "type": "tuple",
            "components": [
                {"name": "token0", "type": "address"},
                {"name": "token1", "type": "address"},
                {"name": "fee", "type": "uint24"},
                {"name": "tickLower", "type": "int24"},
                {"name": "tickUpper", "type": "int24"},
                {"name": "amount0Desired", "type": "uint256"},
                {"name": "amount1Desired", "type": "uint256"},
                {"name": "amount0Min", "type": "uint256"},
                {"name": "amount1Min", "type": "uint256"},
                {"name": "recipient", "type": "address"},
                {"name": "deadline", "type": "uint256"},
            ],
        }],
        "outputs": [
            {"name": "tokenId", "type": "uint256"},
            {"name": "liquidity", "type": "uint128"},
            {"name": "amount0", "type": "uint256"},
            {"name": "amount1", "type": "uint256"},
        ],
    },
    {
        "name": "decreaseLiquidity",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [{
            "name": "params", "type": "tuple",
            "components": [
                {"name": "tokenId", "type": "uint256"},
                {"name": "liquidity", "type": "uint128"},
                {"name": "amount0Min", "type": "uint256"},
                {"name": "amount1Min", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ],
        }],
        "outputs": [
            {"name": "amount0", "type": "uint256"},
            {"name": "amount1", "type": "uint256"},
        ],
    },
    {
        "name": "increaseLiquidity",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [{
            "name": "params", "type": "tuple",
            "components": [
                {"name": "tokenSN", "type": "uint256"},
                {"name": "amount0Desired", "type": "uint256"},
                {"name": "amount1Desired", "type": "uint256"},
                {"name": "amount0Min", "type": "uint256"},
                {"name": "amount1Min", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ],
        }],
        "outputs": [
            {"name": "liquidity", "type": "uint128"},
            {"name": "amount0", "type": "uint256"},
            {"name": "amount1", "type": "uint256"},
        ],
    },
    {
        "name": "collect",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [{
            "name": "params", "type": "tuple",
            "components": [
                {"name": "tokenId", "type": "uint256"},
                {"name": "recipient", "type": "address"},
                {"name": "amount0Max", "type": "uint128"},
                {"name": "amount1Max", "type": "uint128"},
            ],
        }],
        "outputs": [
            {"name": "amount0", "type": "uint256"},
            {"name": "amount1", "type": "uint256"},
        ],
    },
    {
        "name": "positions",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [
            {"name": "token0", "type": "address"},
            {"name": "token1", "type": "address"},
            {"name": "fee", "type": "uint24"},
            {"name": "tickLower", "type": "int24"},
            {"name": "tickUpper", "type": "int24"},
            {"name": "liquidity", "type": "uint128"},
            {"name": "feeGrowthInside0LastX128", "type": "uint256"},
            {"name": "feeGrowthInside1LastX128", "type": "uint256"},
            {"name": "tokensOwed0", "type": "uint128"},
            {"name": "tokensOwed1", "type": "uint128"},
        ],
    },
    {
        "name": "Transfer",
        "type": "event",
        "anonymous": False,
        "inputs": [
            {"name": "from", "type": "address", "indexed": True},
            {"name": "to", "type": "address", "indexed": True},
            {"name": "tokenId", "type": "uint256", "indexed": True},
        ],
    },
    {
        "name": "multicall",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [{"name": "data", "type": "bytes[]"}],
        "outputs": [{"name": "results", "type": "bytes[]"}],
    },
    {
        "name": "refundETH",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [],
        "outputs": [],
    },
    {
        "name": "unwrapWHBAR",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {"name": "amountMinimum", "type": "uint256"},
            {"name": "recipient", "type": "address"},
        ],
        "outputs": [],
    },
]


V2_FACTORY_ABI_MINIMAL = [
    {
        "name": "getPool", "type": "function", "stateMutability": "view",
        "inputs": [
            {"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"},
            {"name": "fee", "type": "uint24"},
        ],
        "outputs": [{"name": "pool", "type": "address"}],
    },
]

POOL_SLOT0_ABI_MINIMAL = [
    {
        "name": "slot0", "type": "function", "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"},
            {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"},
            {"name": "feeProtocol", "type": "uint8"},
            {"name": "unlocked", "type": "bool"},
        ],
    },
    {
        # Voor TWAP-berekening (30 aug 2026, op aangeleverde feedback) --
        # standaard Uniswap-V3-oracle-functie, geeft de CUMULATIEVE tick
        # terug op elk gevraagd moment in het verleden (secondsAgos, in
        # seconden vóór nu). TWAP over een periode = het verschil in
        # cumulatieve tick, gedeeld door het tijdsverschil.
        "name": "observe", "type": "function", "stateMutability": "view",
        "inputs": [{"name": "secondsAgos", "type": "uint32[]"}],
        "outputs": [
            {"name": "tickCumulatives", "type": "int56[]"},
            {"name": "secondsPerLiquidityCumulativeX128s", "type": "uint160[]"},
        ],
    },
]


def get_live_pool_price(rpc_client, factory_address: str, token0: str, token1: str,
                          fee_tier: int, token0_decimals: int, token1_decimals: int) -> float:
    """
    Haalt de prijs RECHTSTREEKS uit de pool zelf (via slot0()'s tick),
    i.p.v. via een externe indexeringsdienst zoals GeckoTerminal (26 aug
    2026, gevonden na herhaalde "Price slippage check"-fouten bij grotere
    LP-posities die niet optraden bij kleine test-bedragen).

    GeckoTerminal kan een eigen indexerings-vertraging hebben t.o.v. de
    daadwerkelijke, live on-chain staat -- de pool zelf beoordeelt onze
    mint()-transactie echter altijd tegen zijn EIGEN, actuele prijs. Deze
    functie elimineert dat verschil als mogelijke foutbron, door de
    tick-range en amount-berekeningen te baseren op exact dezelfde bron
    die de pool zelf gebruikt.

    Geeft de prijs terug in dezelfde conventie als current_price elders
    in dit bestand (token1 per token0, mensvriendelijk).
    """
    factory = rpc_client.w3.eth.contract(address=factory_address, abi=V2_FACTORY_ABI_MINIMAL)
    pool_address = factory.functions.getPool(token0, token1, fee_tier).call()

    pool = rpc_client.w3.eth.contract(address=pool_address, abi=POOL_SLOT0_ABI_MINIMAL)
    slot0 = pool.functions.slot0().call()
    current_tick = slot0[1]

    raw_price = 1.0001 ** current_tick
    return raw_price * (10 ** (token0_decimals - token1_decimals))


def get_twap_tick(rpc_client, factory_address: str, token0: str, token1: str,
                    fee_tier: int, seconds_ago: int = 300) -> int:
    """
    Vraagt de TWAP-tick (time-weighted average) van de pool op over de
    afgelopen `seconds_ago` seconden, via Uniswap V3's ingebouwde
    observe()-orakelfunctie (30 aug 2026, op aangeleverde feedback --
    ter vervanging van een cross-source-vergelijking met GeckoTerminal,
    die bij normale, legitieme block-to-block koersbewegingen te veel
    valse alarmen zou geven vanwege GeckoTerminal's eigen indexerings-
    vertraging).

    Vereist dat de pool's observationCardinality groot genoeg is om
    `seconds_ago` seconden terug te kunnen kijken -- geverifieerd
    empirisch (30 aug 2026): onze testnet-pool heeft cardinaliteit 1000,
    ruim voldoende voor 300 seconden (5 minuten).

    Geeft de TWAP-tick terug als geheel getal (afgerond naar beneden,
    zoals Uniswap's eigen conventie bij een negatieve deling).
    """
    factory = rpc_client.w3.eth.contract(address=factory_address, abi=V2_FACTORY_ABI_MINIMAL)
    pool_address = factory.functions.getPool(token0, token1, fee_tier).call()
    pool = rpc_client.w3.eth.contract(address=pool_address, abi=POOL_SLOT0_ABI_MINIMAL)

    tick_cumulatives, _ = pool.functions.observe([seconds_ago, 0]).call()
    tick_cumulative_delta = tick_cumulatives[1] - tick_cumulatives[0]

    # Python's "//"-operator rondt AL correct naar beneden af bij een
    # negatieve teller (floor-deling, matcht Uniswap's eigen conventie)
    # -- GEEN extra correctie nodig. (30 aug 2026: eerdere versie had
    # hier een overbodige, FOUTIEVE extra aftrekking die de uitkomst
    # met 1 verschoof; verwijderd na directe verificatie met Python's
    # eigen //-gedrag op een negatief testgeval.)
    return tick_cumulative_delta // seconds_ago


def compute_amount0_for_amount1(amount1_raw: int, current_price: float,
                                  tick_lower: int, tick_upper: int,
                                  token0_decimals: int, token1_decimals: int) -> int:
    """
    De OMGEKEERDE afleiding van compute_amount1_for_amount0() -- nodig
    wanneer amount1 (bv. SAUCE) de daadwerkelijk beperkende factor is
    (bv. veel HBAR maar weinig SAUCE in de wallet), zodat amount0 correct
    wordt afgeleid van de kleinere, werkelijk beschikbare kant, i.p.v.
    andersom (26 aug 2026, gevonden bij het vangnet in
    regime_orchestrator.py).

    Formule: L = amount1 / (sqrtP - sqrtPLower)
             amount0 = L * (sqrtPUpper - sqrtP) / (sqrtP * sqrtPUpper)
    """
    raw_price = current_price * (10 ** (token1_decimals - token0_decimals))
    sqrt_price = math.sqrt(raw_price)
    sqrt_price_lower = math.sqrt(1.0001 ** tick_lower)
    sqrt_price_upper = math.sqrt(1.0001 ** tick_upper)

    sqrt_price = max(sqrt_price_lower, min(sqrt_price, sqrt_price_upper))

    if sqrt_price == sqrt_price_lower:
        return 0  # volledig in token1, geen token0 nodig

    liquidity = amount1_raw / (sqrt_price - sqrt_price_lower)
    amount0_raw = liquidity * (sqrt_price_upper - sqrt_price) / (sqrt_price * sqrt_price_upper)

    return int(amount0_raw)


def compute_amount1_for_amount0(amount0_raw: int, current_price: float,
                                  tick_lower: int, tick_upper: int,
                                  token0_decimals: int, token1_decimals: int) -> int:
    """
    Leidt het WISKUNDIG CORRECTE amount1 af uit amount0 en de gekozen
    tick-range -- exact het principe achter Uniswap V3 SDK's
    Position.fromAmount0() (24 aug 2026, toegevoegd na een gevonden
    aandachtspunt in de officiele docs).

    Zonder dit zouden amount0/amount1 onafhankelijk van elkaar gekozen
    worden, wat bij een verhouding die niet precies aansluit bij de
    tick-range een "Price slippage check"-fout kan veroorzaken -- los
    van een eventuele fout in de tick-berekening zelf.

    Formule (Uniswap V3-whitepaper): bij een prijs binnen de range geldt
    L = amount0 * (sqrtP * sqrtPUpper) / (sqrtPUpper - sqrtP)
    amount1 = L * (sqrtP - sqrtPLower)
    """
    raw_price = current_price * (10 ** (token1_decimals - token0_decimals))
    sqrt_price = math.sqrt(raw_price)
    sqrt_price_lower = math.sqrt(1.0001 ** tick_lower)
    sqrt_price_upper = math.sqrt(1.0001 ** tick_upper)

    # Als de huidige prijs buiten de range valt (zou niet moeten gebeuren
    # bij een vers geopende positie rond de huidige prijs, maar defensief
    # afgehandeld): begrenzen binnen de range.
    sqrt_price = max(sqrt_price_lower, min(sqrt_price, sqrt_price_upper))

    if sqrt_price_upper == sqrt_price:
        return 0  # volledig in token0, geen token1 nodig

    liquidity = amount0_raw * (sqrt_price * sqrt_price_upper) / (sqrt_price_upper - sqrt_price)
    amount1_raw = liquidity * (sqrt_price - sqrt_price_lower)

    return int(amount1_raw)


def should_claim_and_compound(tokens_owed0_raw: int, tokens_owed1_raw: int,
                                current_price: float, token0_decimals: int, token1_decimals: int,
                                claim_and_compound_cost_hbar: float = 2.0,
                                min_worthwhile_multiple: float = 2.0) -> bool:
    """
    Bepaalt of het loont om opgebouwde, nog niet geinde fees te claimen en
    direct te herinvesteren in dezelfde positie (26 aug 2026, zelfde
    economisch principe als compute_economic_cooldown()).

    Fees die in de pool blijven staan gaan NIET verloren of verlopen niet
    -- ze blijven gewoon oplopen als tokensOwed0/tokensOwed1 totdat je ze
    claimt. Er is dus geen enkele haast om vaak te claimen; het enige
    nadeel van wachten is dat het geclaimde bedrag zelf niet meewerkt aan
    de liquiditeit (en dus geen extra fees genereert) totdat je het
    daadwerkelijk herinvesteert.

    claim_and_compound_cost_hbar: geschatte gaskosten van collect() +
    increaseLiquidity() samen (~2 HBAR, gebaseerd op vergelijkbare
    multicall-operaties gemeten 24-26 aug 2026 op testnet).

    min_worthwhile_multiple: de opgebouwde waarde moet minstens dit
    veelvoud van de kosten bedragen voordat het de moeite waard is --
    een marge van 2x (standaard) voorkomt dat je nét quitte speelt na
    de transactiekosten.

    Geeft True terug als claimen+herinvesteren nu economisch de moeite waard is.
    """
    owed0_value = tokens_owed0_raw / (10 ** token0_decimals)
    owed1_value_in_token0_terms = (tokens_owed1_raw / (10 ** token1_decimals)) / current_price \
        if current_price > 0 else 0

    # Totale opgebouwde waarde, uitgedrukt in token0-termen (doorgaans WHBAR
    # in onze pools, dus direct vergelijkbaar met de HBAR-gaskosten).
    total_owed_value_token0 = owed0_value + owed1_value_in_token0_terms

    return total_owed_value_token0 >= (claim_and_compound_cost_hbar * min_worthwhile_multiple)


def compute_fees_apr(volume_24h: float, fee_tier: int, l_bal: float) -> float:
    """
    Berekent de Fees-APR van een pool, exact volgens SaucerSwap's eigen
    formule (docs.saucerswap.finance/protocol/saucerswap-v2, 26 aug 2026):

        Fees APR = (24u-volume x (fee x 5/6)) / L_bal x 365

    fee_tier: in hundredths of a bip (bv. 3000 voor 0.30%) -- zelfde
        eenheid als overal elders in dit project.
    l_bal: totale liquiditeit geaggregeerd over een "balanced range"
        (SaucerSwap's eigen definitie). Bij gebrek aan een exacte match
        kan de pool's totale TVL als praktische benadering dienen -- de
        gangbare vereenvoudiging die de meeste DeFi-trackers toepassen,
        maar wijkt af van SaucerSwap's precieze interne metriek.

    LET OP: volume_24h moet door de aanroeper worden aangeleverd -- er is
    nog GEEN bevestigde databron hiervoor gevonden in SaucerSwap's REST
    API (de /v2/pools-endpoint geeft wel liquidity/amountA/amountB, maar
    geen volume-veld). Dit is een correcte implementatie van de formule
    zelf; een betrouwbare volume-bron vinden is een aparte, nog
    openstaande stap.
    """
    if l_bal <= 0:
        return 0.0

    fee_rate = (fee_tier / 1_000_000) * (5 / 6)  # fee_tier is in hundredths of a bip
    daily_fee_income = volume_24h * fee_rate
    return (daily_fee_income / l_bal) * 365


def compute_economic_cooldown(capital_value_hbar: float, fee_apr: float,
                                rebalance_cost_hbar: float = 2.0,
                                min_cooldown_seconds: float = 1800) -> float:
    """
    Berekent de economisch verantwoorde minimale wachttijd tussen twee
    herbalanceringen -- ter vervanging van de eerdere vaste 4-uur-gok
    (26 aug 2026).

    Principe: herbalanceren is pas de moeite waard als de gemiste
    fee-inkomsten (door buiten de range te staan) de kosten van het
    herbalanceren zelf overtreffen.

    capital_value_hbar: waarde van de positie, in HBAR-equivalent.
    fee_apr: verwacht jaarlijks fee-rendement van de pool (bv. 0.20 voor
        20%) -- idealiter uit SaucerSwap's eigen volumedata afgeleid,
        voorlopig een instelbare parameter met een redelijke default.
    rebalance_cost_hbar: empirisch vastgestelde gas-kosten van een volledige
        close+open-cyclus (~2 HBAR, gemeten 24-26 aug 2026 op TESTNET).
    min_cooldown_seconds: praktische ondergrens (voorkomt reageren op
        ruis binnen enkele minuten).

    GEEN bovengrens (bewust, 26 aug 2026): bij realistische testnet-
    positiegroottes (tientallen tot honderden HBAR) loopt de economisch
    verantwoorde cooldown al snel op tot dagen -- soms maanden bij kleine
    posities, gezien de vaste ~2 HBAR gaskosten per cyclus. Dit is geen
    bug maar een eerlijke weerspiegeling van de economie op deze schaal.

    BELANGRIJK VOOR MAINNET: deze aanname (rebalance_cost_hbar=2,
    gebaseerd op TESTNET-gasprijzen) moet opnieuw bekeken worden zodra
    er daadwerkelijk richting mainnet wordt gegaan -- mainnet-gaskosten
    en de dan daadwerkelijk ingezette kapitaalomvang kunnen tot een heel
    andere uitkomst leiden. Zie PLAN.md.

    Geeft de cooldown in seconden terug.
    """
    if capital_value_hbar <= 0 or fee_apr <= 0:
        return float("inf")  # geen zinnige fee-inkomsten te verwachten -- nooit economisch de moeite waard

    fee_income_per_hour_hbar = (capital_value_hbar * fee_apr) / (365 * 24)
    if fee_income_per_hour_hbar <= 0:
        return float("inf")

    breakeven_hours = rebalance_cost_hbar / fee_income_per_hour_hbar
    breakeven_seconds = breakeven_hours * 3600

    return max(min_cooldown_seconds, breakeven_seconds)


def price_to_tick(price: float, token0_decimals: int, token1_decimals: int) -> int:
    """
    Zet een 'gewone' prijs (token1 per token0) om naar een tick-index.
    price = 1.0001^tick, gecorrigeerd voor het decimalenverschil tussen
    de twee tokens.

    KRITIEK GECORRIGEERD (24 aug 2026, empirisch gevonden bij de eerste
    echte LP-positie-poging): de exponent stond omgekeerd. Uniswap V3's
    interne prijs is altijd token1_raw/token0_raw (in kleinste eenheden).
    Bij WHBAR (8 dec, token0) en SAUCE (6 dec, token1) geldt:
    mensvriendelijke_prijs = interne_prijs * 10^(token0_decimals -
    token1_decimals) -- dus om van mensvriendelijk terug naar intern te
    gaan moet je delen, niet vermenigvuldigen met die factor. Geverifieerd
    met een bekend rekenvoorbeeld (1 BTC @ 30.000 USDC): de oude formule
    gaf een factor 10.000 te hoog resultaat.
    """
    adjusted_price = price * (10 ** (token1_decimals - token0_decimals))
    tick = math.log(adjusted_price) / math.log(1.0001)
    return int(round(tick))


def nearest_usable_tick(tick: int, tick_spacing: int) -> int:
    """Rondt een tick af naar het dichtstbijzijnde geldige veelvoud van tickSpacing."""
    return round(tick / tick_spacing) * tick_spacing


def tick_to_price(tick: int, token0_decimals: int, token1_decimals: int) -> float:
    """
    Omgekeerde van price_to_tick() (29 aug 2026, voor het dagelijkse
    statusrapport) -- zet een tick-index terug om naar een 'gewone',
    mensvriendelijke prijs.
    """
    adjusted_price = 1.0001 ** tick
    return adjusted_price / (10 ** (token1_decimals - token0_decimals))


def compute_position_amounts(liquidity: int, tick_lower: int, tick_upper: int,
                               current_price: float, token0_decimals: int,
                               token1_decimals: int) -> tuple[float, float]:
    """
    Berekent hoeveel token0 (bv. HBAR) en token1 (bv. SAUCE/USDC) een
    ACTIEVE, bestaande LP-positie op dit moment daadwerkelijk bevat (29
    aug 2026, voor het dagelijkse statusrapport). Standaard Uniswap-V3-
    wiskunde, zelf afgeleid en geverifieerd (grensgevallen op P=Pa en
    P=Pb geven correct 0 terug voor resp. token1 en token0).

    Werkt bewust met RUWE prijzen/ticks door de hele berekening heen
    (P_raw = 1.0001^tick, dezelfde conventie als de on-chain liquidity-
    waarde zelf gebruikt) -- pas HELEMAAL AAN HET EIND wordt omgerekend
    naar mensvriendelijke eenheden. Dit voorkomt een subtiele
    schaalfout die zou ontstaan door price_to_tick()/tick_to_price()'s
    mensvriendelijke, decimalen-gecorrigeerde prijzen rechtstreeks in de
    liquidity-formule te gebruiken.

    Geeft (amount0, amount1) terug in mensvriendelijke eenheden.
    """
    price_lower_raw = 1.0001 ** tick_lower
    price_upper_raw = 1.0001 ** tick_upper
    current_price_raw = current_price * (10 ** (token1_decimals - token0_decimals))

    if current_price_raw <= price_lower_raw:
        amount0_raw = liquidity * (1 / math.sqrt(price_lower_raw) - 1 / math.sqrt(price_upper_raw))
        amount1_raw = 0.0
    elif current_price_raw >= price_upper_raw:
        amount0_raw = 0.0
        amount1_raw = liquidity * (math.sqrt(price_upper_raw) - math.sqrt(price_lower_raw))
    else:
        amount0_raw = liquidity * (1 / math.sqrt(current_price_raw) - 1 / math.sqrt(price_upper_raw))
        amount1_raw = liquidity * (math.sqrt(current_price_raw) - math.sqrt(price_lower_raw))

    return (amount0_raw / (10 ** token0_decimals), amount1_raw / (10 ** token1_decimals))


@dataclass
class LpPositionConfig:
    position_manager_address: str
    token0: str  # LET OP: moet alfabetisch/numeriek de kleinste van de twee adressen zijn
    token1: str
    whbar_address: Optional[str] = None  # nodig om te bepalen welke kant HBAR is (voor de payable-waarde)
    whbar_helper_address: Optional[str] = None  # nodig voor het correct unwrappen (24 aug 2026)
    factory_address: Optional[str] = None  # nodig om mintFee() op te vragen
    mirror_node_url: Optional[str] = None  # nodig voor de exchange-rate-lookup bij mintFee()
    fee_tier: int = 3000
    range_width_pct: float = 0.05  # +/- 5% rond de huidige prijs
    token0_decimals: int = 8   # WHBAR
    token1_decimals: int = 6   # USDC (of 18 op testnet, zie config.py)
    deadline_seconds: int = 120


@dataclass
class LpPositionState:
    token_id: Optional[int]
    tick_lower: Optional[int]
    tick_upper: Optional[int]
    is_open: bool = False
    last_rebalance_at: Optional[float] = None  # unix timestamp


FACTORY_MINT_FEE_ABI = [
    {
        "name": "mintFee",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],  # in tinycent (US)
    },
]


WHBAR_HELPER_ABI = [
    {
        "name": "unwrapWhbar",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "wad", "type": "uint256"}],
        "outputs": [],
    },
    {
        "name": "wrapWhbar",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [],
        "outputs": [],
    },
]

MINIMAL_ERC20_ABI = [
    {
        "name": "balanceOf", "type": "function", "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "approve", "type": "function", "stateMutability": "nonpayable",
        "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
]


class LpManager:
    def __init__(self, rpc_client: HederaRpcClient, config: LpPositionConfig):
        self.rpc_client = rpc_client
        self.config = config
        self.position_manager = rpc_client.w3.eth.contract(
            address=config.position_manager_address, abi=POSITION_MANAGER_ABI
        )
        self.factory = None
        if config.factory_address:
            self.factory = rpc_client.w3.eth.contract(
                address=config.factory_address, abi=FACTORY_MINT_FEE_ABI
            )
        self.whbar_helper = None
        if config.whbar_helper_address:
            self.whbar_helper = rpc_client.w3.eth.contract(
                address=config.whbar_helper_address, abi=WHBAR_HELPER_ABI
            )
        self.whbar_token = None
        if config.whbar_address:
            self.whbar_token = rpc_client.w3.eth.contract(
                address=config.whbar_address, abi=MINIMAL_ERC20_ABI
            )
        self.state = LpPositionState(token_id=None, tick_lower=None, tick_upper=None)

        tick_spacing = DEFAULT_TICK_SPACING_BY_FEE.get(config.fee_tier)
        if tick_spacing is None:
            raise ValueError(
                f"Onbekende fee_tier {config.fee_tier} -- geen bekende tickSpacing. "
                f"Verifieer dit tegen de daadwerkelijke pool voordat je verdergaat."
            )
        self.tick_spacing = tick_spacing

    def _deadline(self) -> int:
        import time
        return int(time.time()) + self.config.deadline_seconds

    def compute_range(self, current_price: float,
                       volatility_regime: VolatilityRegime = VolatilityRegime.NORMAL,
                       sentiment_direction: float = 0.0) -> tuple[int, int]:
        """
        Berekent tickLower/tickUpper, nu met twee onafhankelijke aanpassingen
        bovenop de basis symmetrische marge:

        1. volatility_regime bepaalt de BREEDTE (LOW=smal, HIGH=breed) --
           bedoeld om periodiek te verversen, niet elke poll-cyclus.
        2. sentiment_direction (-1.0 tot +1.0, bv. de combined_score uit
           strategy_engine) schuift de range asymmetrisch VOORUIT in de
           verwachte richting, zodat de positie minder snel uit de marge
           loopt als sentiment gelijk krijgt. Bij sentiment_direction=0
           blijft de range symmetrisch zoals voorheen.
        """
        width = RANGE_WIDTH_BY_REGIME[volatility_regime]

        # Asymmetrische verschuiving: bij sterk positief sentiment leunt de
        # range naar boven (meer ruimte om te stijgen, iets minder naar
        # beneden), en omgekeerd. skew=0.4 betekent: bij sentiment=+1.0
        # verschuift het midden van de range 40% van de breedte omhoog.
        max_skew_fraction = 0.4
        skew = sentiment_direction * max_skew_fraction * width

        lower_price = current_price * (1 - width + skew)
        upper_price = current_price * (1 + width + skew)

        tick_lower = price_to_tick(lower_price, self.config.token0_decimals, self.config.token1_decimals)
        tick_upper = price_to_tick(upper_price, self.config.token0_decimals, self.config.token1_decimals)

        tick_lower = nearest_usable_tick(tick_lower, self.tick_spacing)
        tick_upper = nearest_usable_tick(tick_upper, self.tick_spacing)

        return tick_lower, tick_upper

    def compute_range_via_gbm(self, current_price: float, sentiment_mu: float,
                                volatility_sigma: float, historical_hourly_volatility: float,
                                horizon_hours: float = 4.0,
                                confidence_level: float = 0.80,
                                macro_regime: str = "sideways") -> tuple[int, int]:
        """
        Vervangt compute_range()'s discrete LOW/NORMAL/HIGH-indeling door
        een doorlopend berekende range, via Geometric Brownian Motion
        (28 aug 2026, zie gbm_range_model.py voor de volledige wiskunde
        en kalibratie-aannames).

        sentiment_mu: geaggregeerde LLM-sentiment-score (-1.0 tot 1.0,
            LlmSentimentEngine.aggregate_with_decay()) -- verwacht dat de
            aanroeper hier AL apply_regime_bias() op heeft toegepast
            (nieuws-niveau-asymmetrie), voordat dit binnenkomt.
        volatility_sigma: geaggregeerde LLM-onzekerheidsscore (0.0 tot
            1.0, LlmSentimentEngine.aggregate_volatility_with_decay()).
        historical_hourly_volatility: ECHTE, gemeten uurvolatiliteit
            (Binance-data) -- de empirische basis waarop volatility_sigma
            een multiplier toepast.
        horizon_hours: over hoeveel uur de betrouwbaarheidsband berekend
            wordt (standaard 4u, matcht VOLATILITY_REGIME_REFRESH_SECONDS'
            herzieningsinterval).
        macro_regime: "bull"/"bear"/"sideways" (28 aug 2026) -- geeft een
            AANVULLENDE, macro-niveau drift-versterking bovenop de
            nieuws-niveau-asymmetrie, zie gbm_range_model.py.
        """
        from gbm_range_model import compute_gbm_confidence_interval

        result = compute_gbm_confidence_interval(
            current_price=current_price,
            sentiment_mu=sentiment_mu,
            volatility_sigma=volatility_sigma,
            historical_hourly_volatility=historical_hourly_volatility,
            horizon_hours=horizon_hours,
            confidence_level=confidence_level,
            macro_regime=macro_regime,
        )

        tick_lower = price_to_tick(result.lower_price, self.config.token0_decimals, self.config.token1_decimals)
        tick_upper = price_to_tick(result.upper_price, self.config.token0_decimals, self.config.token1_decimals)

        tick_lower = nearest_usable_tick(tick_lower, self.tick_spacing)
        tick_upper = nearest_usable_tick(tick_upper, self.tick_spacing)

        return tick_lower, tick_upper

    def is_price_out_of_range(self, current_price: float) -> bool:
        """Checkt of de huidige prijs nog binnen de actieve positie-marge valt."""
        if not self.state.is_open:
            return False

        current_tick = price_to_tick(
            current_price, self.config.token0_decimals, self.config.token1_decimals
        )
        return current_tick < self.state.tick_lower or current_tick > self.state.tick_upper

    def _get_mint_fee_tinybar(self) -> int:
        """
        Vraagt de actuele mint-fee op (Factory.mintFee(), in tinycent US)
        en rekent 'm om naar tinybar via de mirror-node exchange-rate-API
        -- exact het patroon uit de officiele SaucerSwap-docs
        (developers/v2/liquidity/liquidity-position-fee, 23 aug 2026).

        Geeft 0 terug als factory_address of mirror_node_url ontbreekt,
        zodat de aanroeper hier zelf een beslissing over kan nemen i.p.v.
        een stille crash.
        """
        if not self.factory or not self.config.mirror_node_url:
            return 0

        tinycent = self.factory.functions.mintFee().call()
        if tinycent == 0:
            return 0

        response = requests.get(
            f"{self.config.mirror_node_url}/api/v1/network/exchangerate", timeout=10
        )
        response.raise_for_status()
        current_rate = response.json()["current_rate"]
        cent_equivalent = current_rate["cent_equivalent"]
        hbar_equivalent = current_rate["hbar_equivalent"]

        cent_to_hbar_ratio = cent_equivalent / hbar_equivalent
        tinybar = round(tinycent / cent_to_hbar_ratio)
        return tinybar

    def _ensure_token_approval(self, token_address: str, amount_raw: int):
        """Regelt een approve() voor een willekeurig (niet-WHBAR) token richting de PositionManager."""
        token_contract = self.rpc_client.w3.eth.contract(address=token_address, abi=MINIMAL_ERC20_ABI)
        approve_fn = token_contract.functions.approve(self.config.position_manager_address, amount_raw)
        approve_tx = self.rpc_client.build_and_send_transaction(approve_fn)
        self.rpc_client.wait_for_receipt(approve_tx)
        # Korte pauze: de RPC-relay's eigen nonce-tracking kan iets achterlopen
        # op de daadwerkelijke bevestiging, wat tot "Nonce too low" leidde bij
        # de daaropvolgende transactie (25 aug 2026, empirisch gevonden).
        time.sleep(2)

    def open_position(self, amount0_desired: int, amount1_desired: int,
                       current_price: float, slippage_tolerance: float = 0.02,
                       volatility_regime: VolatilityRegime = VolatilityRegime.NORMAL,
                       sentiment_direction: float = 0.0,
                       gas_limit_override: Optional[int] = None,
                       precomputed_tick_range: Optional[tuple[int, int]] = None) -> int:
        """
        Opent een nieuwe LP-positie rond de huidige prijs. Geeft de
        token_id van de nieuwe NFT-positie terug.

        precomputed_tick_range (28 aug 2026): als meegegeven, slaat deze
        functie de interne compute_range()-berekening (LOW/NORMAL/HIGH-
        indeling) over en gebruikt in plaats daarvan deze al-berekende
        (tick_lower, tick_upper) -- de route die het nieuwe, GBM-
        gebaseerde model gebruikt (zie regime_orchestrator.py en
        compute_range_via_gbm()). volatility_regime/sentiment_direction
        worden dan genegeerd.

        Volgt het officiele SaucerSwap-patroon (docs.saucerswap.finance,
        23 aug 2026): mint() en refundETH() gebundeld via multicall().

        DEFINITIEVE FIX (27 aug 2026, op direct advies van SaucerSwap's
        eigen support): de eerdere aanname dat je HBAR gewoon als native
        msg.value kunt meesturen en het contract dat intern automatisch
        wrapt, bleek ONJUIST -- de PositionManager verwacht daadwerkelijk
        ECHTE, al-bestaande WHBAR-ERC20-tokens in de wallet (via
        transferFrom, net als elk ander token), niet een automatische
        wrap-tijdens-mint(). Zonder dit expliciet zelf te doen faalde
        mint() stilzwijgend met een lege revert-reden -- SPECIFIEK
        merkbaar bij het initialiseren van NIEUWE tick-grenzen (smalle,
        nog-nooit-gebruikte ranges), wat verklaart waarom brede ranges
        (die vaker al-bestaande, eerder geinitialiseerde ticks hergebruiken)
        dit probleem niet lieten zien.

        Oplossing: eerst expliciet WhbarHelper.wrapWhbar() aanroepen om
        native HBAR om te zetten in echte WHBAR-ERC20-tokens, DAARNA pas
        de normale approve()+mint()-stroom, met een MINIMALE msg.value
        (alleen voor de mint-fee, niet meer voor de tokenkant zelf).
        """
        # Stap 1: HBAR EXPLICIET inwikkelen tot echte WHBAR-ERC20-tokens
        # (26 aug 2026 -- zie uitgebreide toelichting hierboven).
        if self.config.whbar_address and self.whbar_helper:
            whbar_lower = self.config.whbar_address.lower()
            whbar_amount_needed = None
            if self.config.token0.lower() == whbar_lower:
                whbar_amount_needed = amount0_desired
                whbar_decimals = self.config.token0_decimals
            elif self.config.token1.lower() == whbar_lower:
                whbar_amount_needed = amount1_desired
                whbar_decimals = self.config.token1_decimals

            if whbar_amount_needed is not None:
                wrap_value_wei = whbar_amount_needed * (10 ** (18 - whbar_decimals))
                wrap_fn = self.whbar_helper.functions.wrapWhbar()
                wrap_tx = self.rpc_client.build_and_send_transaction(wrap_fn, value_wei=wrap_value_wei)
                self.rpc_client.wait_for_receipt(wrap_tx)
                time.sleep(2)  # zelfde nonce-timing-marge als elders in dit bestand

        # KRITIEK, empirisch gevonden 24 aug 2026: het niet-WHBAR-token
        # (bv. SAUCE, USDC) heeft een voorafgaande approve() nodig richting
        # de PositionManager. Zonder dit faalt mint() stilzwijgend met een
        # lege revert-reden. Geldt nu, na de wrap-fix hierboven, ook voor
        # WHBAR zelf -- het is nu gewoon een normaal ERC20-token in de
        # wallet, net als SAUCE/USDC.
        #
        # AANVULLENDE FIX (27 aug 2026): een KLEINE marge (0.5%) bovenop
        # het exacte, berekende bedrag goedkeuren -- niet het bedrag zelf
        # dat aan mint() wordt doorgegeven. mint() berekent zijn eigen
        # liquiditeitswaarde (L) intern via Solidity's integer-wiskunde,
        # terwijl wij dat bedrag vooraf benaderen via Python's floating-
        # point-wiskunde, wat een kleine afrondingsafwijking kan geven.
        APPROVAL_SAFETY_MARGIN = 1.005
        self._ensure_token_approval(self.config.token0, int(amount0_desired * APPROVAL_SAFETY_MARGIN))
        self._ensure_token_approval(self.config.token1, int(amount1_desired * APPROVAL_SAFETY_MARGIN))

        if precomputed_tick_range is not None:
            tick_lower, tick_upper = precomputed_tick_range
        else:
            tick_lower, tick_upper = self.compute_range(current_price, volatility_regime, sentiment_direction)

        params = (
            self.config.token0,
            self.config.token1,
            self.config.fee_tier,
            tick_lower,
            tick_upper,
            amount0_desired,
            amount1_desired,
            int(amount0_desired * (1 - slippage_tolerance)),
            int(amount1_desired * (1 - slippage_tolerance)),
            self.rpc_client.address,
            self._deadline(),
        )

        # Bepaal de payable HBAR-waarde: als token0 of token1 WHBAR is,
        # moet het BIJBEHORENDE amount_desired als msg.value meegestuurd
        # worden zodat het contract dat intern kan wrappen.
        # Payable-waarde: de WHBAR-kant van amount0/1_desired staat in
        # WHBAR's EIGEN kleinste eenheid (token0_decimals/token1_decimals,
        # standaard 8) -- maar msg.value wordt door de EVM-relay
        # geinterpreteerd in de 18-decimalen-wei-conventie (zelfde als
        # get_hbar_balance() elders gebruikt). Die twee verschillen, en
        # moeten hier expliciet omgerekend worden -- anders exact
        # dezelfde decimalen-fout als eerder vandaag al meermaals
        # gevonden en opgelost.
        #
        # HERZIENE FIX (27 aug 2026): beide betaalroutes tegelijk
        # gebruiken -- de wrap+approve-stap hierboven (stap 1) EN de
        # msg.value hier. Alleen de wrap-route weglaten gaf een nieuwe,
        # vroege revert ("MF", laag gasverbruik) -- vermoedelijk
        # controleert mint() altijd of msg.value > 0 zodra een van de
        # tokens WHBAR is, ongeacht of er al vooraf gewrapt is.
        # refundETH() (al onderdeel van de multicall) stuurt het
        # ongebruikte deel gewoon terug, dus dubbel is hier veilig.
        payable_value = 0
        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() == whbar_lower:
                decimal_correction = 10 ** (18 - self.config.token0_decimals)
                payable_value = amount0_desired * decimal_correction
            elif self.config.token1.lower() == whbar_lower:
                decimal_correction = 10 ** (18 - self.config.token1_decimals)
                payable_value = amount1_desired * decimal_correction

        # Mint-fee toevoegen (in tinybar, ook omgerekend naar de
        # 18-decimalen-wei-conventie: 1 tinybar = 10^-8 HBAR = 10^10 wei).
        mint_fee_tinybar = self._get_mint_fee_tinybar()
        if mint_fee_tinybar > 0:
            payable_value += mint_fee_tinybar * (10 ** 10)

        mint_encoded = self.position_manager.encode_abi("mint", args=[params])
        refund_eth_encoded = self.position_manager.encode_abi("refundETH", args=[])

        multicall_fn = self.position_manager.functions.multicall([mint_encoded, refund_eth_encoded])
        tx_hash = self.rpc_client.build_and_send_transaction(
            multicall_fn, value_wei=payable_value, gas_limit=gas_limit_override,
        )
        receipt = self.rpc_client.wait_for_receipt(tx_hash)

        if receipt["status"] != "success":
            raise RuntimeError(f"LP-positie openen mislukt: {tx_hash}")

        token_id = self._extract_token_id_from_mint(tx_hash)

        self.state.token_id = token_id
        self.state.tick_lower = tick_lower
        self.state.tick_upper = tick_upper
        self.state.is_open = True

        return token_id

    def _extract_token_id_from_mint(self, tx_hash: str) -> int:
        """
        Haalt de tokenId van de zojuist gemintte LP-positie-NFT op uit de
        Transfer-event-logs van de transactie (ERC721 mint = Transfer van
        het nul-adres naar de ontvanger, met tokenId als derde indexed
        argument). Betrouwbaarder dan raden of aannemen.
        """
        raw_receipt = self.rpc_client.w3.eth.get_transaction_receipt(tx_hash)
        transfer_events = self.position_manager.events.Transfer().process_receipt(raw_receipt)

        if not transfer_events:
            raise RuntimeError(
                f"Geen Transfer-event gevonden in mint-transactie {tx_hash} -- "
                f"kan tokenId niet vaststellen. Controleer handmatig via HashScan."
            )

        # Bij een mint is er precies één Transfer-event (van 0x0 naar de ontvanger).
        return transfer_events[0]["args"]["tokenId"]

    def claim_and_compound(self, token_id: int, current_price: float,
                             claim_and_compound_cost_hbar: float = 2.0,
                             min_worthwhile_multiple: float = 2.0,
                             slippage_tolerance: float = 0.15) -> Optional[str]:
        """
        Claimt opgebouwde fees (collect()) en herinvesteert ze direct in
        dezelfde positie (increaseLiquidity()) -- maar ALLEEN als dat
        economisch de moeite waard is, via should_claim_and_compound()
        (26 aug 2026, zelfde principe als de herbalanceer-cooldown).

        Geeft de tx_hash terug bij daadwerkelijke actie, of None als het
        (nog) niet de moeite waard was -- dat laatste is het normale,
        verwachte pad bij de meeste aanroepen.
        """
        position_data = self.position_manager.functions.positions(token_id).call()
        tokens_owed0_raw = position_data[8]
        tokens_owed1_raw = position_data[9]

        if not should_claim_and_compound(
            tokens_owed0_raw, tokens_owed1_raw, current_price,
            self.config.token0_decimals, self.config.token1_decimals,
            claim_and_compound_cost_hbar, min_worthwhile_multiple,
        ):
            return None  # normale pad: nog niet genoeg opgebouwd om de moeite waard te zijn

        collect_params = (token_id, self.rpc_client.address, 2**128 - 1, 2**128 - 1)
        collect_fn = self.position_manager.functions.collect(collect_params)
        collect_tx = self.rpc_client.build_and_send_transaction(collect_fn)
        collect_receipt = self.rpc_client.wait_for_receipt(collect_tx)

        if collect_receipt["status"] != "success":
            return None

        # Zelfde niet-WHBAR-approve-stap als bij open_position().
        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() != whbar_lower:
                self._ensure_token_approval(self.config.token0, tokens_owed0_raw)
            if self.config.token1.lower() != whbar_lower:
                self._ensure_token_approval(self.config.token1, tokens_owed1_raw)

        min0 = int(tokens_owed0_raw * (1 - slippage_tolerance))
        min1 = int(tokens_owed1_raw * (1 - slippage_tolerance))
        increase_params = (token_id, tokens_owed0_raw, tokens_owed1_raw, min0, min1, self._deadline())
        increase_encoded = self.position_manager.encode_abi("increaseLiquidity", args=[increase_params])
        refund_eth_encoded = self.position_manager.encode_abi("refundETH")

        payable_value = 0
        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() == whbar_lower:
                payable_value = tokens_owed0_raw * (10 ** (18 - self.config.token0_decimals))
            elif self.config.token1.lower() == whbar_lower:
                payable_value = tokens_owed1_raw * (10 ** (18 - self.config.token1_decimals))

        mint_fee_tinybar = self._get_mint_fee_tinybar()
        if mint_fee_tinybar > 0:
            payable_value += mint_fee_tinybar * (10 ** 10)

        multicall_fn = self.position_manager.functions.multicall([increase_encoded, refund_eth_encoded])
        increase_tx = self.rpc_client.build_and_send_transaction(multicall_fn, value_wei=payable_value)
        increase_receipt = self.rpc_client.wait_for_receipt(increase_tx)

        return increase_tx if increase_receipt["status"] == "success" else None

    def deploy_additional_capital(self, token_id: int, amount0_desired: int, amount1_desired: int,
                                    slippage_tolerance: float = 0.15) -> Optional[str]:
        """
        Voegt WILLEKEURIG wallet-kapitaal toe aan een bestaande, open
        positie via increaseLiquidity() (30 aug 2026, op verzoek: zodra
        er kapitaal bijgestort wordt terwijl de bot in LP_MODE staat,
        moet dat automatisch de pool in gaan, i.p.v. los in de wallet te
        blijven liggen tot de volgende volledige herbalancering).

        Anders dan claim_and_compound() hierboven (die WERKT VANUIT
        geclaimde fees, via collect()): deze functie gebruikt de gegeven
        amount0_desired/amount1_desired rechtstreeks -- bedoeld voor
        vers wallet-saldo (bv. een handmatige bijstorting), niet voor
        opgebouwde fees. Zelfde onderliggende increaseLiquidity()+
        refundETH()-multicall-patroon als claim_and_compound().

        Geeft de tx_hash terug bij succes, of None bij een mislukking.
        """
        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() != whbar_lower:
                self._ensure_token_approval(self.config.token0, amount0_desired)
            if self.config.token1.lower() != whbar_lower:
                self._ensure_token_approval(self.config.token1, amount1_desired)

        min0 = int(amount0_desired * (1 - slippage_tolerance))
        min1 = int(amount1_desired * (1 - slippage_tolerance))
        increase_params = (token_id, amount0_desired, amount1_desired, min0, min1, self._deadline())
        increase_encoded = self.position_manager.encode_abi("increaseLiquidity", args=[increase_params])
        refund_eth_encoded = self.position_manager.encode_abi("refundETH")

        payable_value = 0
        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() == whbar_lower:
                payable_value = amount0_desired * (10 ** (18 - self.config.token0_decimals))
            elif self.config.token1.lower() == whbar_lower:
                payable_value = amount1_desired * (10 ** (18 - self.config.token1_decimals))

        mint_fee_tinybar = self._get_mint_fee_tinybar()
        if mint_fee_tinybar > 0:
            payable_value += mint_fee_tinybar * (10 ** 10)

        multicall_fn = self.position_manager.functions.multicall([increase_encoded, refund_eth_encoded])
        increase_tx = self.rpc_client.build_and_send_transaction(multicall_fn, value_wei=payable_value)
        increase_receipt = self.rpc_client.wait_for_receipt(increase_tx)

        return increase_tx if increase_receipt["status"] == "success" else None

    def check_and_recover_stuck_whbar(self) -> float:
        """
        Checkt of er WHBAR (ERC20, niet-unwrapped) in de wallet staat, en
        unwrapt dit automatisch naar native HBAR als dat zo is (28 aug
        2026). Dit kan gebeuren als een eerdere close_position()
        halverwege faalde -- de decrease+collect-stap gelukt, maar de
        aparte, daaropvolgende unwrap-stap niet (bv. door een tijdelijke
        RPC-storing). Empirisch gevonden: 109.52 WHBAR bleef zo een tijd
        onopgemerkt vast zitten, omdat de bestaande balans-controles
        alleen naar NATIVE HBAR keken, nooit naar deze aparte
        WHBAR-ERC20-balans.

        Geeft het aantal (in whole HBAR) teruggewonnen WHBAR terug, of
        0.0 als er niets te doen was.
        """
        if not self.whbar_token or not self.whbar_helper:
            return 0.0

        whbar_balance_raw = self.whbar_token.functions.balanceOf(self.rpc_client.address).call()
        if whbar_balance_raw == 0:
            return 0.0

        approve_fn = self.whbar_token.functions.approve(
            self.config.whbar_helper_address, whbar_balance_raw
        )
        approve_tx = self.rpc_client.build_and_send_transaction(approve_fn)
        self.rpc_client.wait_for_receipt(approve_tx)
        time.sleep(2)

        unwrap_fn = self.whbar_helper.functions.unwrapWhbar(whbar_balance_raw)
        unwrap_tx = self.rpc_client.build_and_send_transaction(unwrap_fn, gas_limit=1_000_000)
        self.rpc_client.wait_for_receipt(unwrap_tx)

        # Goedkeuring meteen weer intrekken (28 aug 2026, op advies van
        # SaucerSwap's eigen support: geen open allowance naar het
        # WHBAR-contract laten staan na gebruik).
        revoke_fn = self.whbar_token.functions.approve(self.config.whbar_helper_address, 0)
        revoke_tx = self.rpc_client.build_and_send_transaction(revoke_fn)
        self.rpc_client.wait_for_receipt(revoke_tx)

        return whbar_balance_raw / (10 ** 8)

    def close_position(self, token_id: int, liquidity: Optional[int] = None) -> str:
        """
        Trekt alle liquiditeit terug en int de opgebouwde fees.

        DEFINITIEF GECORRIGEERD (24 aug 2026, empirisch bevestigd op
        testnet): de PositionManager's eigen unwrapWHBAR() (net als de
        SwapRouter's variant) unwrapt NIET wat al naar de gebruiker is
        gestuurd via collect(). De eerdere multicall-bundeling met
        unwrapWHBAR loste dus niets op.

        De WERKELIJK correcte route: decrease + collect (die stuurt de
        WHBAR al naar de gebruiker via recipient=self.rpc_client.address),
        en DAARNA een aparte aanroep naar WhbarHelper.unwrapWhbar() (die
        zelf weer een voorafgaande approve() nodig heeft, want WhbarHelper
        haalt de WHBAR actief op via safeTransferFrom()).

        liquidity: als niet opgegeven, wordt de actuele waarde eerst
        opgehaald via positions(tokenId).
        """
        if liquidity is None:
            position_data = self.position_manager.functions.positions(token_id).call()
            liquidity = position_data[5]  # index verschoven na verwijderen nonce/operator (26 aug 2026)

        calls = []

        if liquidity > 0:
            decrease_params = (token_id, liquidity, 0, 0, self._deadline())
            calls.append(self.position_manager.encode_abi("decreaseLiquidity", args=[decrease_params]))

        collect_params = (token_id, self.rpc_client.address, 2**128 - 1, 2**128 - 1)
        calls.append(self.position_manager.encode_abi("collect", args=[collect_params]))

        multicall_fn = self.position_manager.functions.multicall(calls)
        tx_hash = self.rpc_client.build_and_send_transaction(multicall_fn)
        receipt = self.rpc_client.wait_for_receipt(tx_hash)
        time.sleep(2)  # nonce-timing-fix, ook hier nodig gebleken (26 aug 2026)

        self.state = LpPositionState(token_id=None, tick_lower=None, tick_upper=None, is_open=False)

        if receipt["status"] != "success" or not self.whbar_helper or not self.whbar_token:
            return tx_hash if receipt["status"] == "success" else None

        # Positie gesloten -- nu de daadwerkelijk ontvangen WHBAR unwrappen
        # (indien deze pool WHBAR bevatte; anders is de balans gewoon 0).
        whbar_balance_raw = self.whbar_token.functions.balanceOf(self.rpc_client.address).call()
        if whbar_balance_raw == 0:
            return tx_hash

        approve_fn = self.whbar_token.functions.approve(
            self.config.whbar_helper_address, whbar_balance_raw
        )
        approve_tx = self.rpc_client.build_and_send_transaction(approve_fn)
        self.rpc_client.wait_for_receipt(approve_tx)
        time.sleep(2)  # zelfde nonce-timing-fix als in _ensure_token_approval (26 aug 2026)

        unwrap_fn = self.whbar_helper.functions.unwrapWhbar(whbar_balance_raw)
        unwrap_tx = self.rpc_client.build_and_send_transaction(unwrap_fn, gas_limit=1_000_000)
        self.rpc_client.wait_for_receipt(unwrap_tx)

        # Goedkeuring intrekken na gebruik (28 aug 2026, op advies van
        # SaucerSwap's eigen support: geen open allowance naar het
        # WHBAR-contract laten staan). Bewust NA de eigenlijke unwrap, en
        # met een eigen try/except -- als dit specifieke stapje faalt
        # (bv. door een RPC-hik), mag dat de rest van close_position()
        # niet alsnog als mislukt laten gelden, want de daadwerkelijke
        # positie-sluiting is dan al lang voltooid.
        try:
            time.sleep(2)
            revoke_fn = self.whbar_token.functions.approve(self.config.whbar_helper_address, 0)
            revoke_tx = self.rpc_client.build_and_send_transaction(revoke_fn)
            self.rpc_client.wait_for_receipt(revoke_tx)
        except Exception:
            pass  # niet kritiek -- check_and_recover_stuck_whbar() dekt eventuele resten af

        return tx_hash

    def rebalance_if_needed(self, current_price: float, amount0: int, amount1: int,
                              volatility_regime: VolatilityRegime = VolatilityRegime.NORMAL,
                              sentiment_direction: float = 0.0,
                              proactive_threshold: float = 0.6,
                              fee_apr: float = 0.20,
                              cooldown_seconds: Optional[float] = None) -> bool:
        """
        Twee triggers voor herbalanceren, allebei onderworpen aan dezelfde
        cooldown om te voorkomen dat de proactieve sentiment-trigger en de
        reactieve prijs-trigger elkaar opjagen tot te frequent herbalanceren:

        1. REACTIEF: de prijs is al buiten de huidige marge.
        2. PROACTIEF: sentiment is sterk genoeg om de range vast te
           verschuiven vóórdat de prijs er daadwerkelijk buiten valt.

        cooldown_seconds: als niet opgegeven, wordt deze ECONOMISCH berekend
        via compute_economic_cooldown() -- ter vervanging van de eerdere
        vaste 4-uur-gok (26 aug 2026). fee_apr is een instelbare aanname
        over het verwachte fee-rendement van de pool; idealiter later
        vervangen door een live opgevraagde waarde uit SaucerSwap's
        volumedata zodra die betrouwbaar beschikbaar is.

        Geeft True terug als er geherbalanceerd is.
        """
        import time

        if cooldown_seconds is None:
            capital_value_hbar = amount0 / (10 ** self.config.token0_decimals) * current_price \
                if self.config.token0 == self.config.whbar_address \
                else amount0 / (10 ** self.config.token0_decimals)
            # Bij benadering: amount0 is uitgedrukt in WHBAR-termen als token0
            # WHBAR is, anders een grove schatting -- dit hoeft niet exact te
            # zijn, het bepaalt alleen de ORDE VAN GROOTTE van de cooldown.
            cooldown_seconds = compute_economic_cooldown(capital_value_hbar, fee_apr)

        if self.state.last_rebalance_at is not None:
            elapsed = time.time() - self.state.last_rebalance_at
            if elapsed < cooldown_seconds:
                return False  # cooldown actief, ongeacht trigger-type

        needs_reactive_rebalance = self.is_price_out_of_range(current_price)
        needs_proactive_rebalance = (
            self.state.is_open and abs(sentiment_direction) >= proactive_threshold
        )

        if not needs_reactive_rebalance and not needs_proactive_rebalance:
            return False

        if self.state.token_id is not None:
            self.close_position(self.state.token_id)  # liquidity wordt nu automatisch opgehaald
            # LET OP (23 aug 2026, zelfde categorie fix als regime_orchestrator.py):
            # amount0/amount1 zijn de oorspronkelijk MEEGEGEVEN parameters,
            # niet wat er daadwerkelijk uit close_position() terugkwam
            # (inclusief opgebouwde fees, en een mogelijk andere token0/
            # token1-verhouding door prijsbeweging binnen de oude range).
            # De aanroeper (LpOrchestrator, momenteel inactief sinds de
            # RegimeOrchestrator-pivot) moet daarom na een rebalance de
            # WERKELIJKE wallet-balans opvragen en die gebruiken, niet
            # simpelweg dezelfde amount0/amount1 doorgeven aan
            # open_position() hieronder. Deze functie zelf kan dat niet
            # oplossen zonder een balans-query, die hoort in de aanroeper
            # thuis (zie RegimeOrchestrator._get_swappable_hbar_balance()
            # /_get_swappable_usdc_balance() als voorbeeld-patroon).

        self.open_position(
            amount0, amount1, current_price,
            volatility_regime=volatility_regime,
            sentiment_direction=sentiment_direction,
        )
        self.state.last_rebalance_at = time.time()
        return True


if __name__ == "__main__":
    config = LpPositionConfig(
        position_manager_address="0x0000000000000000000000000000000000000001",
        token0="0x0000000000000000000000000000000000000002",
        token1="0x0000000000000000000000000000000000000003",
        fee_tier=3000,
    )

    current_price = 0.065

    scenarios = [
        ("Normale volatiliteit, geen sentiment", VolatilityRegime.NORMAL, 0.0),
        ("Lage volatiliteit, geen sentiment (smalle range)", VolatilityRegime.LOW, 0.0),
        ("Hoge volatiliteit, geen sentiment (brede range)", VolatilityRegime.HIGH, 0.0),
        ("Normale volatiliteit, sterk positief sentiment (range schuift omhoog)", VolatilityRegime.NORMAL, 0.9),
        ("Hoge volatiliteit, sterk negatief sentiment (breed + naar beneden)", VolatilityRegime.HIGH, -0.9),
    ]

    for label, regime, sentiment in scenarios:
        tick_lower_raw = None
        width = RANGE_WIDTH_BY_REGIME[regime]
        skew = sentiment * 0.4 * width
        lower_price = current_price * (1 - width + skew)
        upper_price = current_price * (1 + width + skew)
        print(f"\n{label}")
        print(f"  Range: {lower_price:.4f} -- {upper_price:.4f} (breedte={width:.0%}, skew={skew:+.3f})")

    print("\n--- Volatiliteits-regime detectie testen ---")
    low_vol_returns = [0.002, -0.003, 0.001, 0.004, -0.002]
    high_vol_returns = [0.05, -0.08, 0.06, -0.04, 0.07]
    print(f"Lage-vol returns -> regime: {compute_volatility_regime(low_vol_returns).value}")
    print(f"Hoge-vol returns -> regime: {compute_volatility_regime(high_vol_returns).value}")
