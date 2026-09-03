"""
stray_token_handler.py

Beheert tokens die de bot ontvangt maar niet direct kan gebruiken --
bijvoorbeeld reward-tokens uit een SaucerSwap-incentive-programma,
apart van de gewone swap-fees (die altijd in token0/token1 van de
LP-positie zelf binnenkomen, nooit in een derde token).

Principe (26 aug 2026, zelfde economische denkwijze als
compute_economic_cooldown() en should_claim_and_compound()): een
onbekend token associeren EN swappen kost gas. Dat is pas de moeite
waard als de waarde van het token die kosten met een ruime marge
overtreft.
"""

from dataclasses import dataclass
from typing import Optional

from swap_executor_v2 import SWAP_ROUTER_ABI, QUOTER_V2_ABI


HTS_PRECOMPILE_ADDRESS = "0x0000000000000000000000000000000000000167"

HTS_PRECOMPILE_ABI = [
    {
        "name": "associateToken",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "token", "type": "address"},
        ],
        "outputs": [{"name": "responseCode", "type": "int64"}],
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


@dataclass
class StrayTokenConfig:
    swap_router_address: str
    quoter_v2_address: str
    whbar_address: str
    fee_tier: int = 3000
    association_cost_hbar: float = 2.0
    swap_cost_hbar: float = 1.0
    min_worthwhile_multiple: float = 2.0


def get_token_value_in_hbar(rpc_client, config: StrayTokenConfig,
                              token_address: str, amount_raw: int) -> Optional[float]:
    """
    Vraagt een quote op om te bepalen wat een tokenbedrag waard is in HBAR.
    Geeft None terug als er geen directe pool tegen WHBAR bestaat.
    """
    if amount_raw == 0:
        return 0.0

    quoter = rpc_client.w3.eth.contract(address=config.quoter_v2_address, abi=QUOTER_V2_ABI)
    quote_params = (token_address, config.whbar_address, amount_raw, config.fee_tier, 0)

    try:
        quote_result = quoter.functions.quoteExactInputSingle(quote_params).call()
    except Exception:
        return None

    return quote_result[0] / (10 ** 8)


def should_convert_stray_token(token_value_hbar: Optional[float], config: StrayTokenConfig,
                                 already_associated: bool) -> bool:
    """
    Bepaalt of het loont om een los token te associeren (indien nodig) en
    te swappen naar HBAR. Geeft False terug als de waarde onbekend is.
    """
    if token_value_hbar is None:
        return False

    total_cost = config.swap_cost_hbar
    if not already_associated:
        total_cost += config.association_cost_hbar

    return token_value_hbar >= (total_cost * config.min_worthwhile_multiple)


def convert_stray_token_to_hbar(rpc_client, config: StrayTokenConfig,
                                  token_address: str,
                                  already_associated: bool, slippage_tolerance: float = 0.02) -> Optional[str]:
    """
    Voert de daadwerkelijke conversie uit: associeert (indien nodig) en
    swapt het VOLLEDIGE saldo van dit token naar HBAR. De aanroeper moet
    should_convert_stray_token() al zelf hebben gecheckt.
    """
    token_contract = rpc_client.w3.eth.contract(address=token_address, abi=MINIMAL_ERC20_ABI)
    balance_raw = token_contract.functions.balanceOf(rpc_client.address).call()
    if balance_raw == 0:
        return None

    if not already_associated:
        hts = rpc_client.w3.eth.contract(address=HTS_PRECOMPILE_ADDRESS, abi=HTS_PRECOMPILE_ABI)
        associate_fn = hts.functions.associateToken(rpc_client.address, token_address)
        associate_tx = rpc_client.build_and_send_transaction(associate_fn, gas_limit=2_000_000)
        associate_receipt = rpc_client.wait_for_receipt(associate_tx)
        if associate_receipt["status"] != "success":
            return None

    approve_fn = token_contract.functions.approve(config.swap_router_address, balance_raw)
    approve_tx = rpc_client.build_and_send_transaction(approve_fn)
    rpc_client.wait_for_receipt(approve_tx)

    quoter = rpc_client.w3.eth.contract(address=config.quoter_v2_address, abi=QUOTER_V2_ABI)
    quote_params = (token_address, config.whbar_address, balance_raw, config.fee_tier, 0)
    quote_result = quoter.functions.quoteExactInputSingle(quote_params).call()
    min_out_raw = int(quote_result[0] * (1 - slippage_tolerance))

    router = rpc_client.w3.eth.contract(address=config.swap_router_address, abi=SWAP_ROUTER_ABI)
    swap_params = (
        token_address, config.whbar_address, config.fee_tier,
        rpc_client.address,
        rpc_client.w3.eth.get_block("latest")["timestamp"] + 120,
        balance_raw, min_out_raw, 0,
    )
    swap_fn = router.functions.exactInputSingle(swap_params)
    swap_tx = rpc_client.build_and_send_transaction(swap_fn)
    swap_receipt = rpc_client.wait_for_receipt(swap_tx)

    return swap_tx if swap_receipt["status"] == "success" else None
