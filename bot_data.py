# bot_data.py
#
# Gedeelde data-ophaal-logica (1 sep 2026, bij het bouwen van het
# webdashboard) -- geextraheerd uit daily_status_report.py zodat zowel
# het Telegram-rapport als het nieuwe, live webdashboard exact dezelfde,
# eenmaal-geverifieerde logica gebruiken (geen duplicatie, geen risico
# dat de twee uit elkaar gaan lopen).

import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses
from swap_executor import ERC20_ABI
from hedera_address_utils import hedera_id_to_evm_address
from lp_manager import compute_position_amounts, get_live_pool_price, tick_to_price
from geckoterminal_client import GeckoTerminalClient
from postgres_client import PostgresClient

HEDERA_NETWORK = os.environ.get("HEDERA_NETWORK", "testnet")

V2_POSITION_MANAGER_ABI = [
    {
        "name": "positions", "type": "function", "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [
            {"name": "token0", "type": "address"}, {"name": "token1", "type": "address"},
            {"name": "fee", "type": "uint24"}, {"name": "tickLower", "type": "int24"},
            {"name": "tickUpper", "type": "int24"}, {"name": "liquidity", "type": "uint128"},
            {"name": "feeGrowthInside0LastX128", "type": "uint256"},
            {"name": "feeGrowthInside1LastX128", "type": "uint256"},
            {"name": "tokensOwed0", "type": "uint128"}, {"name": "tokensOwed1", "type": "uint128"},
        ],
    },
    {
        "name": "collect", "type": "function", "stateMutability": "payable",
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
]

STRATEGIE_NAMEN = {
    "lp_mode": "LP_MODE (actief in de pool)",
    "bullish_reflex": "BULLISH_REFLEX (volledig uitgestapt, alles in HBAR)",
    "bearish_reflex": "BEARISH_REFLEX (volledig uitgestapt, alles in SAUCE)",
}


async def fetch_dashboard_data(db: PostgresClient) -> dict:
    """
    Verzamelt alle live data die zowel het Telegram-rapport als het
    webdashboard nodig hebben, in een enkele, gestructureerde dict.
    `db` moet al verbonden zijn (db.connect() al aangeroepen) -- deze
    functie sluit de verbinding zelf NIET, dat blijft de
    verantwoordelijkheid van de aanroeper.
    """
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    settings = NETWORK_SETTINGS[HEDERA_NETWORK]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, private_key)
    base = resolve_testnet_addresses()
    v2 = resolve_testnet_v2_addresses()

    hbar_balance = float(client.get_hbar_balance())

    sauce_address = hedera_id_to_evm_address("0.0.1183558")
    sauce_contract = client.w3.eth.contract(address=sauce_address, abi=ERC20_ABI)
    sauce_balance = sauce_contract.functions.balanceOf(client.address).call() / (10 ** 6)

    whbar_contract = client.w3.eth.contract(address=base.whbar_token, abi=ERC20_ABI)
    whbar_stuck = whbar_contract.functions.balanceOf(client.address).call() / (10 ** 8)

    gecko = GeckoTerminalClient()
    hbar_price_usd = gecko.get_pool_snapshot().price_usd

    pool_price_sauce_per_hbar = get_live_pool_price(
        client, v2.factory, base.whbar_token, sauce_address, 3000, 8, 6,
    )
    sauce_price_usd = hbar_price_usd / pool_price_sauce_per_hbar if pool_price_sauce_per_hbar > 0 else 0.0

    positie = await db.get_active_lp_position()
    regimestatus = await db.get_regime_state()

    position_data = None
    if positie:
        position_manager = client.w3.eth.contract(
            address=v2.position_manager, abi=V2_POSITION_MANAGER_ABI
        )
        on_chain = position_manager.functions.positions(positie["token_id"]).call()
        liquidity = on_chain[5]

        positie_hbar, positie_sauce = compute_position_amounts(
            liquidity, positie["tick_lower"], positie["tick_upper"],
            pool_price_sauce_per_hbar, token0_decimals=8, token1_decimals=6,
        )
        positie_waarde_usd = positie_hbar * hbar_price_usd + positie_sauce * sauce_price_usd

        UINT128_MAX = (2 ** 128) - 1
        try:
            fee_amount0_raw, fee_amount1_raw = position_manager.functions.collect(
                (positie["token_id"], client.address, UINT128_MAX, UINT128_MAX)
            ).call({"from": client.address})
            fee_hbar = fee_amount0_raw / (10 ** 8)
            fee_sauce = fee_amount1_raw / (10 ** 6)
        except Exception as e:
            print(f"[waarschuwing] Kon opgebouwde fees niet opvragen: {e}")
            fee_hbar, fee_sauce = 0.0, 0.0
        fee_waarde_usd = fee_hbar * hbar_price_usd + fee_sauce * sauce_price_usd

        prijs_onder = tick_to_price(positie["tick_lower"], 8, 6)
        prijs_boven = tick_to_price(positie["tick_upper"], 8, 6)
        if prijs_boven > prijs_onder:
            positie_in_range_pct = (
                (pool_price_sauce_per_hbar - prijs_onder) / (prijs_boven - prijs_onder) * 100
            )
        else:
            positie_in_range_pct = 50.0

        if positie_in_range_pct < 0 or positie_in_range_pct > 100:
            range_status = "buiten_bereik"
        elif positie_in_range_pct < 15 or positie_in_range_pct > 85:
            range_status = "dicht_bij_rand"
        else:
            range_status = "gezond"

        centrum = (prijs_boven + prijs_onder) / 2
        breedte_pct = (prijs_boven - prijs_onder) / (2 * centrum) * 100 if centrum > 0 else 0.0

        position_data = {
            "token_id": positie["token_id"],
            "hbar": positie_hbar, "sauce": positie_sauce, "value_usd": positie_waarde_usd,
            "tick_lower": positie["tick_lower"], "tick_upper": positie["tick_upper"],
            "price_lower": prijs_onder, "price_upper": prijs_boven,
            "width_pct": breedte_pct, "in_range_pct": positie_in_range_pct,
            "range_status": range_status,
            "fee_hbar": fee_hbar, "fee_sauce": fee_sauce, "fee_value_usd": fee_waarde_usd,
        }

    wallet_value_usd = hbar_balance * hbar_price_usd + sauce_balance * sauce_price_usd
    position_value_usd = position_data["value_usd"] if position_data else 0.0
    total_value_usd = wallet_value_usd + position_value_usd

    huidig_regime = regimestatus["current_regime"] if regimestatus else "lp_mode"

    # BUGFIX (3 sep 2026, gevonden na een verwarrende Telegram-melding):
    # het label was voorheen een STATISCHE tekst per regime ("LP_MODE
    # (actief in de pool)"), ongeacht of er daadwerkelijk een open
    # positie was -- misleidend zodra LP_MODE actief is maar de positie
    # (nog) niet geopend is (bv. na een mislukte heropening).
    if huidig_regime == "lp_mode" and position_data is None:
        regime_label = "LP_MODE (geen actieve positie -- wacht op herintrede)"
    else:
        regime_label = STRATEGIE_NAMEN.get(huidig_regime, huidig_regime)

    return {
        "hbar_price_usd": hbar_price_usd,
        "sauce_price_usd": sauce_price_usd,
        "pool_price_sauce_per_hbar": pool_price_sauce_per_hbar,
        "wallet": {"hbar": hbar_balance, "sauce": sauce_balance, "value_usd": wallet_value_usd},
        "wallet_address": client.address,
        "whbar_stuck": whbar_stuck,
        "position": position_data,
        "current_regime": huidig_regime,
        "current_regime_label": regime_label,
        "total_value_usd": total_value_usd,
    }


def get_total_deposits_hbar(account_evm_address: str) -> float:
    """
    Berekent het TOTALE, ooit ingezette kapitaal (1 sep 2026, op verzoek:
    "alle kapitaal ooit ingezet, inclusief de eerste, oorspronkelijke
    storting") door de VOLLEDIGE, historische transactiegeschiedenis van
    de wallet op te vragen via de Hedera mirror node, en daarin de
    GENUINE, externe stortingen te onderscheiden van geld dat gewoon
    terugkomt van onze eigen swaps/transacties.

    HERBOUWD (1 sep 2026, na live debuggen tegen de daadwerkelijke
    mirror-node-respons) -- de eerste versie had twee fundamentele
    aannames die niet klopten:
    1. De account-velden in transfers/token_transfers gebruiken het
       Hedera-EIGEN 0.0.X-formaat, niet het EVM-adres -- vereist eerst
       een opzoekactie (accounts/{evm_adres}) om het juiste, native
       account-ID te krijgen.
    2. Er bestaat geen apart "payer_account_id"-veld -- de initiator
       staat in transaction_id zelf (het deel VOOR het eerste
       streepje, bv. "0.0.7314364" in "0.0.7314364-1788271548-...").

    Onderscheid: een ECHTE storting is een POSITIEVE overdracht naar ons
    account, in een transactie die NIET door onszelf werd geinitieerd
    (transaction_id begint niet met ons eigen account-ID).

    Kijkt zowel naar native HBAR-overdrachten (transfers) als HTS-
    token-overdrachten (token_transfers, voor SAUCE).
    """
    mirror_node_url = NETWORK_SETTINGS[HEDERA_NETWORK]["mirror_node_url"]
    import requests

    # Eerst het EVM-adres omzetten naar het Hedera-eigen 0.0.X-formaat.
    resp = requests.get(f"{mirror_node_url}/api/v1/accounts/{account_evm_address}", timeout=15)
    resp.raise_for_status()
    hedera_account_id = resp.json().get("account")
    if not hedera_account_id:
        return 0.0

    totaal_tinybar = 0
    volgende_url = (
        f"{mirror_node_url}/api/v1/transactions"
        f"?account.id={hedera_account_id}&order=asc&limit=100"
    )
    pagina_teller = 0
    MAX_PAGINAS = 50  # defensief, voorkomt een oneindige lus bij een onverwacht API-antwoord

    # HERZIEN (1 sep 2026, na het daadwerkelijk oplijsten van elke
    # meegetelde transactie op verzoek): "initiator != ons account" bleek
    # NIET voldoende -- Hedera's JSON-RPC-relay-account (op testnet:
    # 0.0.7314364) dient ONZE EIGEN swap-/positie-transacties namens ons
    # in, en verschijnt daardoor als "initiator" voor geld dat gewoon
    # van ONSZELF terugkomt (bv. een refundETH()-teruggave na een swap)
    # -- geen nieuwe, externe storting. Empirisch bevestigd: dit
    # relay-account was verantwoordelijk voor het overgrote deel van een
    # eerder, veel te hoog berekend totaal (7420 i.p.v. de werkelijke
    # ~2128 HBAR). AANNAME: dit relay-account-ID is TESTNET-specifiek en
    # kan bij een mainnet-migratie anders zijn -- dan opnieuw verifieren.
    BEKENDE_RELAY_ACCOUNTS = {"0.0.7314364"}

    while volgende_url and pagina_teller < MAX_PAGINAS:
        resp = requests.get(volgende_url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for tx in data.get("transactions", []):
            transaction_id = tx.get("transaction_id", "")
            initiator = transaction_id.split("-")[0] if transaction_id else ""
            if initiator == hedera_account_id or initiator in BEKENDE_RELAY_ACCOUNTS:
                continue  # WIJZELF (rechtstreeks of via de relay) initieerden dit

            for overdracht in tx.get("transfers", []):
                if overdracht.get("account") == hedera_account_id and overdracht.get("amount", 0) > 0:
                    totaal_tinybar += overdracht["amount"]

        volgende_link = data.get("links", {}).get("next")
        volgende_url = f"{mirror_node_url}{volgende_link}" if volgende_link else None
        pagina_teller += 1

    return totaal_tinybar / (10 ** 8)
