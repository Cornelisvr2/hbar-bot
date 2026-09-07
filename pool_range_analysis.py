"""
pool_range_analysis.py -- (7 sep 2026) Nauwkeurige Fees-APR en LARI-schatting,
volledig on-chain, zonder SaucerSwap's REST-API (die vereist een API-key).

1. Fees-APR volgens SaucerSwap's eigen methodiek:

       Fees APR = (24u-volume x fee x 5/6) / L_bal x 365

   waarbij L_bal NIET de totale pool-TVL is, maar de waarde van de
   liquiditeit binnen een "balanced" tick-venster rond de actieve tick
   (voor fee-tier 1500: +-9,00% = +-900 ticks). Dat venster lezen we uit
   de pool zelf: tickBitmap() + ticks() geven de geinitialiseerde ticks
   en hun liquidityNet, waarmee we de actieve liquiditeit per interval
   reconstrueren en die omrekenen naar tokenbedragen (Uniswap V3-wiskunde).

2. LARI (Liquidity-Aligned Reward Initiative): rewards per twee-weekse
   epoch (SAUCE + HBAR voor de USDC-HBAR-pool), verdeeld op basis van
   liquidity-hours. Twee getallen:
   - pool-gemiddelde Reward-APR, SaucerSwap's eigen formule:
         allocatie x prijs x 26,07145 / L_bal
   - schatting voor ONZE positie: ons aandeel in de actieve liquiditeit
     (onze L / pool.liquidity()) x epoch-allocatie x epochs per jaar,
     gedeeld door onze positiewaarde.

Alle pool-calls zijn eth_call's naar het poolcontract -- bevestigd
werkend via hashio op mainnet (de quoter is het enige contract waarvan
de simulatie structureel weigert; zie swap_executor_v2.py).
"""

import os
from dataclasses import dataclass
from typing import Optional

# SaucerSwap's "balanced range" per fee-tier (docs, 6 sep 2026: voor 1500
# exact +-9,00% = +-900 ticks). Overige tiers: via .env te overschrijven
# (BALANCED_RANGE_TICKS), defaults zijn een redelijke schaling.
BALANCED_RANGE_TICKS_BY_FEE = {
    100: 100,
    500: 500,
    1500: 900,
    3000: 1800,
    10000: 6000,
}

EPOCHS_PER_YEAR = 365 / 14  # 26.07145 -- SaucerSwap's eigen constante

# LARI-allocaties voor de USDC-HBAR-pool per epoch (docs, Epoch 71,
# gecontroleerd 1 aug 2026). De DAO kan dit per epoch wijzigen; daarom
# overschrijfbaar via .env.
DEFAULT_LARI_EPOCH_SAUCE = 241_111.33
DEFAULT_LARI_EPOCH_HBAR = 19_363.27

POOL_ABI_MINIMAL = [
    {"name": "slot0", "type": "function", "stateMutability": "view", "inputs": [],
     "outputs": [{"name": "sqrtPriceX96", "type": "uint160"}, {"name": "tick", "type": "int24"},
                 {"name": "observationIndex", "type": "uint16"},
                 {"name": "observationCardinality", "type": "uint16"},
                 {"name": "observationCardinalityNext", "type": "uint16"},
                 {"name": "feeProtocol", "type": "uint8"}, {"name": "unlocked", "type": "bool"}]},
    {"name": "liquidity", "type": "function", "stateMutability": "view", "inputs": [],
     "outputs": [{"name": "", "type": "uint128"}]},
    {"name": "tickBitmap", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "wordPosition", "type": "int16"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "ticks", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "tick", "type": "int24"}],
     "outputs": [{"name": "liquidityGross", "type": "uint128"},
                 {"name": "liquidityNet", "type": "int128"},
                 {"name": "feeGrowthOutside0X128", "type": "uint256"},
                 {"name": "feeGrowthOutside1X128", "type": "uint256"},
                 {"name": "tickCumulativeOutside", "type": "int56"},
                 {"name": "secondsPerLiquidityOutsideX128", "type": "uint160"},
                 {"name": "secondsOutside", "type": "uint32"},
                 {"name": "initialized", "type": "bool"}]},
]


@dataclass
class BalancedRangeResult:
    tick_current: int
    tick_lower: int
    tick_upper: int
    active_liquidity: int          # pool.liquidity() -- L op de huidige tick
    tvl_in_range_usd: float        # L_bal in USD
    amount0_in_range: float        # mensvriendelijk (token0)
    amount1_in_range: float        # mensvriendelijk (token1)
    initialized_ticks: int


def _sqrt_price_at_tick(tick: int) -> float:
    return 1.0001 ** (tick / 2)


def _amounts_for_interval(liquidity: int, sqrt_a: float, sqrt_b: float,
                          sqrt_current: float) -> tuple[float, float]:
    """Token0/token1 (raw, ongeschaald) voor liquiditeit L over [a, b]."""
    if liquidity <= 0:
        return 0.0, 0.0
    if sqrt_current <= sqrt_a:          # prijs onder het interval: alles token0
        return liquidity * (1 / sqrt_a - 1 / sqrt_b), 0.0
    if sqrt_current >= sqrt_b:          # prijs boven het interval: alles token1
        return 0.0, liquidity * (sqrt_b - sqrt_a)
    return (liquidity * (1 / sqrt_current - 1 / sqrt_b),
            liquidity * (sqrt_current - sqrt_a))


def balanced_range_ticks(fee_tier: int) -> int:
    env = os.environ.get("BALANCED_RANGE_TICKS")
    if env:
        return int(env)
    return BALANCED_RANGE_TICKS_BY_FEE.get(fee_tier, 900)


def compute_balanced_range_tvl(w3, pool_address: str, fee_tier: int, tick_spacing: int,
                               token0_decimals: int, token1_decimals: int,
                               token0_price_usd: float, token1_price_usd: float,
                               half_width_ticks: Optional[int] = None) -> BalancedRangeResult:
    pool = w3.eth.contract(address=pool_address, abi=POOL_ABI_MINIMAL)
    slot0 = pool.functions.slot0().call()
    sqrt_current = slot0[0] / (2 ** 96)
    tick_current = slot0[1]
    active_liquidity = pool.functions.liquidity().call()

    half = half_width_ticks if half_width_ticks is not None else balanced_range_ticks(fee_tier)
    tick_lo = tick_current - half
    tick_hi = tick_current + half

    # Geinitialiseerde ticks binnen [tick_lo, tick_hi] via de bitmap.
    comp_lo = tick_lo // tick_spacing
    comp_hi = -(-tick_hi // tick_spacing)  # ceil
    word_lo, word_hi = comp_lo >> 8, comp_hi >> 8
    initialized: list[int] = []
    for word in range(word_lo, word_hi + 1):
        bits = pool.functions.tickBitmap(word).call()
        if bits == 0:
            continue
        for bit in range(256):
            if bits >> bit & 1:
                comp = (word << 8) + bit
                if comp_lo <= comp <= comp_hi:
                    initialized.append(comp * tick_spacing)
    initialized.sort()

    liquidity_net: dict[int, int] = {}
    for t in initialized:
        liquidity_net[t] = pool.functions.ticks(t).call()[1]

    # Omhoog lopen vanaf de huidige tick: bij het passeren van tick t
    # (omhoog) L += liquidityNet(t). Omlaag: L -= liquidityNet(t).
    amount0 = 0.0
    amount1 = 0.0

    L = active_liquidity
    prev = tick_current
    for t in [x for x in initialized if x > tick_current]:
        a0, a1 = _amounts_for_interval(L, _sqrt_price_at_tick(prev), _sqrt_price_at_tick(min(t, tick_hi)), sqrt_current)
        amount0 += a0; amount1 += a1
        if t >= tick_hi:
            break
        L += liquidity_net[t]
        prev = t
    else:
        if prev < tick_hi:
            a0, a1 = _amounts_for_interval(L, _sqrt_price_at_tick(prev), _sqrt_price_at_tick(tick_hi), sqrt_current)
            amount0 += a0; amount1 += a1

    L = active_liquidity
    prev = tick_current
    for t in sorted([x for x in initialized if x <= tick_current], reverse=True):
        a0, a1 = _amounts_for_interval(L, _sqrt_price_at_tick(max(t, tick_lo)), _sqrt_price_at_tick(prev), sqrt_current)
        amount0 += a0; amount1 += a1
        if t <= tick_lo:
            break
        L -= liquidity_net[t]
        prev = t
    else:
        if prev > tick_lo:
            a0, a1 = _amounts_for_interval(L, _sqrt_price_at_tick(tick_lo), _sqrt_price_at_tick(prev), sqrt_current)
            amount0 += a0; amount1 += a1

    amount0_h = amount0 / (10 ** token0_decimals)
    amount1_h = amount1 / (10 ** token1_decimals)
    tvl = amount0_h * token0_price_usd + amount1_h * token1_price_usd
    return BalancedRangeResult(
        tick_current=tick_current, tick_lower=tick_lo, tick_upper=tick_hi,
        active_liquidity=active_liquidity, tvl_in_range_usd=tvl,
        amount0_in_range=amount0_h, amount1_in_range=amount1_h,
        initialized_ticks=len(initialized),
    )


def compute_fees_apr_balanced(volume_24h_usd: float, fee_tier: int, tvl_in_range_usd: float) -> float:
    """SaucerSwap's Fees-APR met de correcte, 'balanced range'-noemer."""
    if tvl_in_range_usd <= 0:
        return 0.0
    fee_rate = (fee_tier / 1_000_000) * (5 / 6)
    return (volume_24h_usd * fee_rate / tvl_in_range_usd) * 365


@dataclass
class LariEstimate:
    epoch_sauce: float
    epoch_hbar: float
    epoch_value_usd: float          # totale allocatie van de pool per epoch, in USD
    pool_reward_apr: float          # SaucerSwap's pool-gemiddelde Reward-APR
    our_liquidity_share: float      # onze L / actieve pool-L (0 als out-of-range)
    our_reward_per_epoch_usd: float
    our_reward_apr: float           # t.o.v. onze positiewaarde


def lari_epoch_allocation() -> tuple[float, float]:
    return (float(os.environ.get("LARI_EPOCH_SAUCE", DEFAULT_LARI_EPOCH_SAUCE)),
            float(os.environ.get("LARI_EPOCH_HBAR", DEFAULT_LARI_EPOCH_HBAR)))


def estimate_lari(tvl_in_range_usd: float, our_liquidity: int, pool_active_liquidity: int,
                  position_in_range: bool, position_value_usd: float,
                  sauce_price_usd: float, hbar_price_usd: float) -> LariEstimate:
    epoch_sauce, epoch_hbar = lari_epoch_allocation()
    epoch_value = epoch_sauce * sauce_price_usd + epoch_hbar * hbar_price_usd
    pool_apr = (epoch_value * EPOCHS_PER_YEAR / tvl_in_range_usd) if tvl_in_range_usd > 0 else 0.0
    share = (our_liquidity / pool_active_liquidity) if (position_in_range and pool_active_liquidity > 0) else 0.0
    our_epoch = epoch_value * share
    our_apr = (our_epoch * EPOCHS_PER_YEAR / position_value_usd) if position_value_usd > 0 else 0.0
    return LariEstimate(epoch_sauce, epoch_hbar, epoch_value, pool_apr, share, our_epoch, our_apr)


# ---------------------------------------------------------------------------
# Gerealiseerde LARI-uitkeringen (airdrops) via de mirrornode
# ---------------------------------------------------------------------------
LARI_PAYER_ACCOUNTS = [a.strip() for a in os.environ.get(
    "LARI_PAYER_ACCOUNTS", "0.0.3946522").split(",") if a.strip()]
SAUCE_TOKEN_ID = os.environ.get("SAUCE_TOKEN_ID", "0.0.731861")


@dataclass
class LariRealized:
    sauce_received: float
    hbar_received: float
    airdrop_count: int
    last_timestamp: Optional[float]


def fetch_realized_lari(account_id: str, mirror_base: str = "https://mainnet.mirrornode.hedera.com",
                        max_pages: int = 20) -> LariRealized:
    """
    Telt alle SAUCE- en HBAR-credits op ons account op die door een van
    de LARI-payer-accounts zijn geinitieerd (transaction_id begint met dat
    account). Dezelfde payer-lijst wordt door bot_data.get_total_deposits_
    hbar() gebruikt om deze credits NIET als eigen storting te tellen.
    """
    import requests
    sauce = 0.0
    hbar = 0.0
    count = 0
    last_ts = None
    url = f"{mirror_base}/api/v1/transactions?account.id={account_id}&limit=100&order=desc"
    for _ in range(max_pages):
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()
        for tx in data.get("transactions", []):
            payer = tx.get("transaction_id", "").split("-")[0]
            if payer not in LARI_PAYER_ACCOUNTS or tx.get("result") != "SUCCESS":
                continue
            hit = False
            for tt in tx.get("token_transfers", []):
                if tt.get("account") == account_id and tt.get("token_id") == SAUCE_TOKEN_ID and tt.get("amount", 0) > 0:
                    sauce += tt["amount"] / 1e6
                    hit = True
            for tr in tx.get("transfers", []):
                if tr.get("account") == account_id and tr.get("amount", 0) > 0:
                    hbar += tr["amount"] / 1e8
                    hit = True
            if hit:
                count += 1
                ts = float(tx["consensus_timestamp"])
                last_ts = max(last_ts or 0, ts)
        nxt = data.get("links", {}).get("next")
        if not nxt:
            break
        url = mirror_base + nxt
    return LariRealized(sauce, hbar, count, last_ts)


# ---------------------------------------------------------------------------
# Prijs van SAUCE (nodig om de LARI-allocatie in USD te waarderen)
# ---------------------------------------------------------------------------
SAUCE_EVM_ADDRESS = "0x00000000000000000000000000000000000b2ad5"
_sauce_price_cache: dict = {"at": 0.0, "price": 0.0}


def fetch_sauce_price_usd(ttl_seconds: int = 300) -> float:
    """SAUCE/USD via GeckoTerminal (zelfde bron als de HBAR-prijs elders)."""
    import time
    import requests
    if time.time() - _sauce_price_cache["at"] < ttl_seconds and _sauce_price_cache["price"] > 0:
        return _sauce_price_cache["price"]
    url = f"https://api.geckoterminal.com/api/v2/simple/networks/hedera-hashgraph/token_price/{SAUCE_EVM_ADDRESS}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    prices = r.json()["data"]["attributes"]["token_prices"]
    price = float(next(iter(prices.values())))
    _sauce_price_cache.update(at=time.time(), price=price)
    return price


# ---------------------------------------------------------------------------
# Alles-in-een helper voor bot, dashboard en Telegram-rapport
# ---------------------------------------------------------------------------
def compute_pool_metrics(w3, factory_address: str, whbar_address: str, quote_address: str,
                         fee_tier: int, tick_spacing: int, quote_decimals: int,
                         hbar_price_usd: float, quote_price_usd: float, volume_24h_usd: float,
                         our_liquidity: int = 0, our_tick_lower: Optional[int] = None,
                         our_tick_upper: Optional[int] = None, position_value_usd: float = 0.0,
                         sauce_price_usd: Optional[float] = None) -> dict:
    """
    Geeft een dict met:
      fees_apr_balanced, tvl_in_range_usd, tick_current, active_liquidity,
      lari (LariEstimate) -- of lari=None als er geen SAUCE-prijs is.
    quote_address is USDC op mainnet (SAUCE op testnet); whbar_decimals=8.
    """
    factory_abi = [{"name": "getPool", "type": "function", "stateMutability": "view",
                    "inputs": [{"name": "a", "type": "address"}, {"name": "b", "type": "address"},
                               {"name": "fee", "type": "uint24"}],
                    "outputs": [{"name": "pool", "type": "address"}]}]
    factory = w3.eth.contract(address=factory_address, abi=factory_abi)
    pool_address = factory.functions.getPool(whbar_address, quote_address, fee_tier).call()
    if int(pool_address, 16) == 0:
        raise RuntimeError(f"Geen pool voor fee_tier={fee_tier}")

    whbar_is_token0 = int(whbar_address, 16) < int(quote_address, 16)
    if whbar_is_token0:
        t0_dec, t1_dec, p0, p1 = 8, quote_decimals, hbar_price_usd, quote_price_usd
    else:
        t0_dec, t1_dec, p0, p1 = quote_decimals, 8, quote_price_usd, hbar_price_usd

    rng = compute_balanced_range_tvl(w3, pool_address, fee_tier, tick_spacing, t0_dec, t1_dec, p0, p1)
    fees_apr = compute_fees_apr_balanced(volume_24h_usd, fee_tier, rng.tvl_in_range_usd)

    lari = None
    if sauce_price_usd is None:
        try:
            sauce_price_usd = fetch_sauce_price_usd()
        except Exception:
            sauce_price_usd = None
    if sauce_price_usd:
        in_range = (our_tick_lower is not None and our_tick_upper is not None
                    and our_tick_lower <= rng.tick_current < our_tick_upper)
        lari = estimate_lari(rng.tvl_in_range_usd, our_liquidity, rng.active_liquidity,
                             in_range, position_value_usd, sauce_price_usd, hbar_price_usd)

    return {
        "pool_address": pool_address,
        "fees_apr_balanced": fees_apr,
        "tvl_in_range_usd": rng.tvl_in_range_usd,
        "tick_current": rng.tick_current,
        "range_ticks": (rng.tick_lower, rng.tick_upper),
        "active_liquidity": rng.active_liquidity,
        "initialized_ticks": rng.initialized_ticks,
        "sauce_price_usd": sauce_price_usd,
        "lari": lari,
    }
