# daily_status_report.py
#
# Dagelijks statusrapport naar Telegram (29 aug 2026, op verzoek) --
# bedoeld om via cron elke dag om 09:00 te draaien (zie
# daily_status_cron.sh voor de crontab-installatie-instructies).
#
# Bevat: wallet-saldo (native HBAR, eventuele losse SAUCE, en een
# waarschuwing bij vastzittende WHBAR) + de samenstelling en waarde van de
# actieve LP-positie (indien open), allemaal met actuele USD-waarden.
#
# BUGFIX (30 aug 2026, KRITIEK, empirisch gevonden): SAUCE is GEEN 1:1
# USD-proxy op testnet, zoals eerder werd aangenomen -- empirisch
# bevestigd (verhouding GeckoTerminal-USD-prijs vs. de pool's eigen,
# interne SAUCE-per-HBAR-koers): SAUCE is in werkelijkheid maar ~$0,0015
# waard, ~685x minder dan de eerdere $1-aanname. Zonder deze fix toonde
# het rapport bv. 6616 SAUCE als $6616, terwijl de daadwerkelijke waarde
# ~$10 is. SAUCE's echte USD-waarde wordt nu afgeleid via: hbar_price_usd
# / pool_sauce_per_hbar_koers (rechtstreeks via get_live_pool_price()).
# Zelfde reden waarom compute_position_amounts() nu de POOL-interne
# prijs krijgt i.p.v. de USD-prijs -- die functie werkt met tick_lower/
# tick_upper, die ALTIJD in de pool-eigen schaal zijn uitgedrukt.

import asyncio
import datetime
import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import (
    NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses,
    resolve_mainnet_addresses, resolve_mainnet_v2_addresses,
)
from swap_executor import ERC20_ABI
from hedera_address_utils import hedera_id_to_evm_address
from lp_manager import compute_position_amounts, get_live_pool_price, tick_to_price
from geckoterminal_client import GeckoTerminalClient
from postgres_client import PostgresClient
import telegram_notify

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
        # Voor het opvragen van opgebouwde, nog niet geclaimde fees (1 sep
        # 2026, op verzoek) -- via .call() (een gesimuleerde aanroep, GEEN
        # daadwerkelijke transactie) met de maximale bedragen, wat het
        # standaard-patroon is om te zien wat er NU geclaimd zou kunnen
        # worden, zonder het daadwerkelijk te doen.
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


async def main():
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    settings = NETWORK_SETTINGS[HEDERA_NETWORK]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, private_key)
    # BUGFIX (4 sep 2026, gevonden tijdens de mainnet-migratie, zelfde
    # patroon als eerder in bot_data.py gerepareerd): dit was volledig
    # hardgecodeerd naar testnet.
    if HEDERA_NETWORK == "mainnet":
        base = resolve_mainnet_addresses()
        v2 = resolve_mainnet_v2_addresses()
    else:
        base = resolve_testnet_addresses()
        v2 = resolve_testnet_v2_addresses()
    # 1. Wallet-saldo
    hbar_balance = float(client.get_hbar_balance())
    quote_address = base.usdc  # SAUCE op testnet, echte USDC op mainnet
    quote_contract = client.w3.eth.contract(address=quote_address, abi=ERC20_ABI)
    sauce_balance = quote_contract.functions.balanceOf(client.address).call() / (10 ** base.usdc_decimals)
    whbar_contract = client.w3.eth.contract(address=base.whbar_token, abi=ERC20_ABI)
    whbar_stuck = whbar_contract.functions.balanceOf(client.address).call() / (10 ** 8)
    # 2. Prijzen: de ECHTE USD-prijs van HBAR (GeckoTerminal), EN de
    # pool's eigen, interne SAUCE-per-HBAR-koers (rechtstreeks via
    # slot0()) -- zie bestandskop hierboven voor waarom dit TWEE
    # verschillende, beide benodigde grootheden zijn.
    gecko = GeckoTerminalClient()
    hbar_price_usd = gecko.get_pool_snapshot().price_usd
    fee_tier = int(os.environ.get("LP_FEE_TIER", "3000"))
    pool_price_sauce_per_hbar = get_live_pool_price(
        client, v2.factory, base.whbar_token, quote_address, fee_tier, 8, base.usdc_decimals,
    )
    # SAUCE's daadwerkelijke USD-waarde afgeleid (30 aug 2026): als 1 HBAR
    # zowel $hbar_price_usd ALS pool_price_sauce_per_hbar SAUCE waard is,
    # dan is 1 SAUCE = hbar_price_usd / pool_price_sauce_per_hbar dollar waard.
    sauce_price_usd = hbar_price_usd / pool_price_sauce_per_hbar if pool_price_sauce_per_hbar > 0 else 0.0

    # 3. Actieve LP-positie (indien open) EN de huidige regimestatus
    # (30 aug 2026, op verzoek: strategie + positie-in-range zichtbaar
    # maken in het rapport).
    db = PostgresClient()
    await db.connect()
    positie = await db.get_active_lp_position()
    regimestatus = await db.get_regime_state()
    # db.close() verplaatst naar het einde (1 sep 2026) -- later nog
    # nodig voor de historische-waarde-snapshot en -analytics.

    positie_hbar, positie_sauce, positie_waarde_usd = 0.0, 0.0, 0.0
    fee_hbar, fee_sauce, fee_waarde_usd = 0.0, 0.0, 0.0
    if positie:
        position_manager = client.w3.eth.contract(
            address=v2.position_manager, abi=V2_POSITION_MANAGER_ABI
        )
        on_chain = position_manager.functions.positions(positie["token_id"]).call()
        liquidity = on_chain[5]

        # BUGFIX (30 aug 2026): pool_price_sauce_per_hbar i.p.v.
        # hbar_price_usd -- deze functie werkt met tick_lower/tick_upper,
        # die in de pool-eigen schaal zijn uitgedrukt, niet in USD.
        positie_hbar, positie_sauce = compute_position_amounts(
            liquidity, positie["tick_lower"], positie["tick_upper"],
            pool_price_sauce_per_hbar, token0_decimals=8, token1_decimals=6,
        )
        positie_waarde_usd = positie_hbar * hbar_price_usd + positie_sauce * sauce_price_usd

        # Opgebouwde, nog niet geclaimde fees (1 sep 2026, op verzoek) --
        # via een GESIMULEERDE collect()-aanroep (.call(), geen
        # daadwerkelijke transactie) met maximale bedragen.
        #
        # BUGFIX (1 sep 2026): .call() zonder een expliciet "from"-adres
        # simuleert NIET automatisch als onze eigen wallet -- de
        # eigendomscontrole binnen collect() (die vereist dat msg.sender
        # de eigenaar/geautoriseerde operator van de positie is) faalde
        # daardoor met "not authorized". Met from=client.address
        # correct opgelost.
        UINT128_MAX = (2 ** 128) - 1
        try:
            fee_amount0_raw, fee_amount1_raw = position_manager.functions.collect(
                (positie["token_id"], client.address, UINT128_MAX, UINT128_MAX)
            ).call({"from": client.address})
            fee_hbar = fee_amount0_raw / (10 ** 8)
            fee_sauce = fee_amount1_raw / (10 ** 6)
        except Exception as e:
            # Defensief (1 sep 2026): dit is een informatief, niet-
            # kritiek onderdeel van het rapport -- een mislukking hier
            # mag de rest van het rapport niet laten crashen.
            print(f"[waarschuwing] Kon opgebouwde fees niet opvragen: {e}")
            fee_hbar, fee_sauce = 0.0, 0.0
        fee_waarde_usd = fee_hbar * hbar_price_usd + fee_sauce * sauce_price_usd

    # Range-analyse (30 aug 2026, op verzoek): waar staat de HUIDIGE
    # prijs precies binnen de actieve range, en hoe gezond is dat --
    # zelfde soort berekening als eerder vandaag gebruikt om de
    # bijstort-balanceringsklem te verklaren (prijs dicht bij de rand
    # van een smalle range = risicovol).
    range_regel = ""
    if positie:
        # Canonieke token0/token1-decimalen bepalen (5 sep 2026, systematische audit -- zelfde detectie als _setup_lp_manager()
        # in regime_orchestrator.py): ticks in de database zijn ALTIJD canoniek opgeslagen, ongeacht netwerk.
        if int(base.whbar_token, 16) < int(base.usdc, 16):
            _t0_dec, _t1_dec = 8, base.usdc_decimals
        else:
            _t0_dec, _t1_dec = base.usdc_decimals, 8
        # BUGFIX (11 sep 2026): de range-grenzen en de huidige prijs stonden
        # in ELKAARS INVERSE schaal -- tick_to_price() gaf SAUCE/HBAR
        # (bv. 10,9-13,3) terwijl pool_price_sauce_per_hbar in werkelijkheid
        # de HBAR/USDC-schaal heeft (~0,075, dezelfde die de bot in zijn
        # regime-drift-check gebruikt). Dat gaf onmogelijke waarden als
        # -438,9% "in de range" en valse "BUITEN BEREIK"-meldingen, terwijl
        # de bot zelf correct in-range handelde. Fix: beide in DEZELFDE
        # schaal brengen door de tick-grenzen te inverteren en te sorteren,
        # zodat de vergelijking klopt met de prijs die de bot gebruikt.
        _g1 = tick_to_price(positie["tick_lower"], _t0_dec, _t1_dec)
        _g2 = tick_to_price(positie["tick_upper"], _t0_dec, _t1_dec)
        huidige_prijs = pool_price_sauce_per_hbar
        # als de grenzen in de inverse schaal t.o.v. de prijs staan, inverteren
        if _g1 > 0 and _g2 > 0 and min(_g1, _g2) > huidige_prijs * 5:
            _g1, _g2 = 1.0 / _g1, 1.0 / _g2
        prijs_onder, prijs_boven = min(_g1, _g2), max(_g1, _g2)
        if prijs_boven > prijs_onder:
            positie_in_range_pct = (
                (huidige_prijs - prijs_onder) / (prijs_boven - prijs_onder) * 100
            )
        else:
            positie_in_range_pct = 50.0  # degenerate geval, zou niet moeten voorkomen

        if positie_in_range_pct < 0 or positie_in_range_pct > 100:
            range_status = "⚠️ BUITEN BEREIK -- verdient geen fees, wacht op herbalancering"
        elif positie_in_range_pct < 15 or positie_in_range_pct > 85:
            range_status = "⚠️ dicht bij de rand -- kwetsbaar voor uit-bereik-lopen"
        else:
            range_status = "✅ gezond gecentreerd"

        # Breedte van de positie als strategie-indicator (1 sep 2026, op
        # verzoek) -- uitgedrukt als percentage rond de huidige prijs,
        # zelfde soort getal als in de [regime-drift]-logs ("30.0%
        # breedte").
        # BUGFIX (1 sep 2026, na een gevonden inconsistentie): exact
        # dezelfde formule als _regime_drift_check() in regime_
        # orchestrator.py -- halve breedte, t.o.v. het MIDDEN van de
        # range (niet de huidige prijs). Was voorheen (prijs_boven -
        # prijs_onder)/huidige_prijs*100 (VOLLEDIGE breedte t.o.v. de
        # huidige prijs) -- gaf 61,6% waar de regime-drift-log
        # consistent 30,0% toonde voor DEZELFDE positie. Twee losse
        # conventies voor hetzelfde begrip is verwarrend; nu gelijkgetrokken.
        centrum = (prijs_boven + prijs_onder) / 2
        breedte_pct = (prijs_boven - prijs_onder) / (2 * centrum) * 100 if centrum > 0 else 0.0

        fee_regel = ""
        if fee_hbar > 0.0001 or fee_sauce > 0.01:
            fee_regel = f"\n  Opgebouwde fees: {fee_hbar:.4f} HBAR + {fee_sauce:.2f} SAUCE (${fee_waarde_usd:.2f})"

        range_regel = (
            f"\n  Breedte: {breedte_pct:.1f}%\n"
            f"  Range: {prijs_onder:.4f} -- {prijs_boven:.4f} SAUCE/HBAR\n"
            f"  Prijs staat op {positie_in_range_pct:.1f}% in de range -- {range_status}"
            f"{fee_regel}"
        )

    # 4. Berekeningen en bericht opbouwen
    wallet_waarde_usd = hbar_balance * hbar_price_usd + sauce_balance * sauce_price_usd
    totale_waarde_usd = wallet_waarde_usd + positie_waarde_usd

    # Historische analytics (1 sep 2026, op verzoek): eerst de HUIDIGE
    # waarde opslaan als nieuwe snapshot, DAARNA pas de vergelijkingen
    # ophalen (zodat de eerste keer dat dit draait, er meteen een
    # startpunt is voor toekomstige vergelijkingen).
    await db.save_portfolio_value_snapshot(totale_waarde_usd, wallet_waarde_usd, positie_waarde_usd)

    analytics_regels = []
    for dagen, label in [(1, "24u"), (7, "7d"), (30, "30d"), (365, "1j")]:
        vorige = await db.get_portfolio_value_at(dagen)
        if vorige is None:
            continue
        # Tolerantie (1 sep 2026): als de dichtstbijzijnde snapshot te
        # ver van het gevraagde moment af ligt (bv. slechts 2 dagen
        # historie beschikbaar voor een "30d"-vergelijking), is de
        # vergelijking misleidend -- dan liever weglaten dan een
        # verkeerd getal tonen. Marge: de helft van de gevraagde periode.
        nu = datetime.datetime.now(datetime.timezone.utc)
        afstand_dagen = abs((nu - vorige["recorded_at"]).total_seconds()) / 86400
        if abs(afstand_dagen - dagen) > dagen / 2:
            continue
        if vorige["total_value_usd"] > 0:
            verandering_pct = (totale_waarde_usd - vorige["total_value_usd"]) / vorige["total_value_usd"] * 100
            # BUGFIX (11 sep 2026): een verandering buiten [-90%, +1000%] op
            # een portefeuille die niet daadwerkelijk naar (bijna) nul ging,
            # komt vrijwel zeker van een CORRUPTE oude snapshot -- bv. een
            # positiewaarde die met de inmiddels gefixte range/prijs-bug
            # verkeerd is weggeschreven. Dat gaf de onmogelijke "7d: -97,9%".
            # Zulke waarden overslaan i.p.v. een misleidend getal tonen; ze
            # komen vanzelf terug zodra er schone snapshots zijn.
            if -90.0 <= verandering_pct <= 1000.0:
                teken = "+" if verandering_pct >= 0 else ""
                analytics_regels.append(f"{label}: {teken}{verandering_pct:.1f}%")
            else:
                print(f"[waarschuwing] {label}-verandering {verandering_pct:.0f}% onwaarschijnlijk "
                      f"(snapshot ${vorige['total_value_usd']:.2f} vs nu ${totale_waarde_usd:.2f}) -- overgeslagen.")

    analytics_regel = ""
    if analytics_regels:
        analytics_regel = f"\n\n📈 *Waardeverandering*: {' | '.join(analytics_regels)}"

    stuck_regel = ""
    if whbar_stuck > 0.001:
        stuck_regel = f"\n⚠️ Vastzittende WHBAR: {whbar_stuck:.4f} (nog niet omgezet naar native HBAR)"

    # BUGFIX (3 sep 2026, gevonden na een verwarrende Telegram-melding):
    # het label was voorheen een STATISCHE tekst per regime, ongeacht of
    # er daadwerkelijk een open positie was -- zelfde fix als in
    # bot_data.py's fetch_dashboard_data(), hier apart nodig omdat dit
    # bestand zijn eigen, losse strategie_namen-mapping heeft.
    strategie_namen = {
        "lp_mode": "LP_MODE (actief in de pool)",
        "bullish_reflex": "BULLISH_REFLEX (volledig uitgestapt, alles in HBAR)",
        "bearish_reflex": "BEARISH_REFLEX (volledig uitgestapt, alles in SAUCE)",
    }
    huidig_regime = regimestatus["current_regime"] if regimestatus else "lp_mode"
    if huidig_regime == "lp_mode" and positie is None:
        strategie_label = "LP_MODE (geen actieve positie -- wacht op herintrede)"
    else:
        strategie_label = strategie_namen.get(huidig_regime, huidig_regime)
    strategie_regel = (
        f"\n\n🎯 *Huidige strategie*: {strategie_label}"
        f"{range_regel}"
    )

    positie_regel = (
        f"\n\n📊 *LP-positie* (token {positie['token_id']}):\n"
        f"  {positie_hbar:.4f} HBAR + {positie_sauce:.2f} SAUCE\n"
        f"  Waarde: ${positie_waarde_usd:.2f}"
        if positie else "\n\n📊 *LP-positie*: geen actieve positie."
    )

    bericht = (
        f"📅 *Dagelijks statusrapport -- HBAR Bot*\n\n"
        f"💰 *Wallet-saldo*:\n"
        f"  {hbar_balance:.4f} HBAR + {sauce_balance:.2f} SAUCE\n"
        f"  Waarde: ${wallet_waarde_usd:.2f}"
        f"{stuck_regel}"
        f"{strategie_regel}"
        f"{positie_regel}\n\n"
        f"💵 *Totale waarde*: ${totale_waarde_usd:.2f}"
        f"{analytics_regel}\n"
        f"(HBAR-koers: ${hbar_price_usd:.5f}, SAUCE-koers: ${sauce_price_usd:.6f})"
    )

    await db.close()
    telegram_notify.send_telegram_message(bericht)
    print(bericht)


if __name__ == "__main__":
    asyncio.run(main())
