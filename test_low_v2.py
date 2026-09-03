"""
test_open_only_low.py

Positie 340 is al bevestigd gesloten (liquidity=0). Dit script doet
ALLEEN het openen van de nieuwe positie in het LOW/Focused-regime.
"""

import asyncio
import os
import subprocess
import requests

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from hedera_address_utils import hedera_id_to_evm_address
from config import NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses
from lp_manager import (
    LpManager, LpPositionConfig, VolatilityRegime,
    compute_amount1_for_amount0, compute_amount0_for_amount1, get_live_pool_price,
)
from postgres_client import PostgresClient
from swap_executor import ERC20_ABI


SAUCE_TESTNET_ID = "0.0.1183558"
SAUCE_DECIMALS = 6
WHBAR_DECIMALS = 8
POOL_FEE = 3000


async def main():
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    settings = NETWORK_SETTINGS["testnet"]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, private_key)

    base = resolve_testnet_addresses()
    v2 = resolve_testnet_v2_addresses()
    sauce_address = hedera_id_to_evm_address(SAUCE_TESTNET_ID)

    config = LpPositionConfig(
        position_manager_address=v2.position_manager,
        token0=base.whbar_token, token1=sauce_address,
        whbar_address=base.whbar_token,
        whbar_helper_address=base.whbar_helper,
        factory_address=v2.factory,
        fee_tier=POOL_FEE,
        token0_decimals=WHBAR_DECIMALS, token1_decimals=SAUCE_DECIMALS,
    )
    manager = LpManager(client, config)

    GAS_RESERVE_HBAR = 25.0  # verhoogd voor deze diagnostische ronde (was 10.0)

    hbar_balance = float(client.get_hbar_balance())
    hbar_balance = max(0.0, hbar_balance - GAS_RESERVE_HBAR)
    sauce_contract = client.w3.eth.contract(address=sauce_address, abi=ERC20_ABI)
    sauce_balance = sauce_contract.functions.balanceOf(client.address).call() / (10 ** SAUCE_DECIMALS)
    print(f"Huidige balans: {hbar_balance:.4f} HBAR (na {GAS_RESERVE_HBAR:.0f} HBAR gas-reserve) + {sauce_balance:.2f} SAUCE")

    live_price = get_live_pool_price(
        client, v2.factory, base.whbar_token, sauce_address, POOL_FEE,
        WHBAR_DECIMALS, SAUCE_DECIMALS,
    )
    print(f"Live pool-prijs: {live_price}")

    tick_lower, tick_upper = manager.compute_range(
        live_price, VolatilityRegime.LOW, sentiment_direction=0.0
    )
    print(f"Range (LOW/Focused): [{tick_lower}, {tick_upper}]")

    # DIAGNOSTISCHE AANPASSING (26 aug 2026): handmatig verschoven
    # tick-grenzen testen, om te isoleren of het probleem specifiek aan
    # DEZE exacte grenzen ligt (mogelijke edge-case bij tick-initialisatie)
    # of aan smalle ranges in het algemeen.
    SHIFT_TICKS_FOR_TEST = 120  # een tick-spacing-veelvoud verschuiven
    tick_lower -= SHIFT_TICKS_FOR_TEST
    tick_upper -= SHIFT_TICKS_FOR_TEST
    print(f"Verschoven testrange: [{tick_lower}, {tick_upper}]")

    # Herbalanceren VOORDAT we de bedragen bepalen (26 aug 2026, terecht
    # gevonden aandachtspunt): zonder dit gebruikt de beperkende-kant-
    # logica hieronder simpelweg de kleinste van de twee kanten, en laat
    # de rest van de andere kant ONGEBRUIKT liggen -- geen fout, maar wel
    # inefficient. Eerst checken of de HUIDIGE verhouding al voldoende is
    # voor volledige HBAR-inzet; zo niet, de helft van het overschot
    # omzetten om dichter bij een bruikbare verhouding te komen.
    hbar_raw_check = int(hbar_balance * (10 ** WHBAR_DECIMALS))
    usdc_raw_check = int(sauce_balance * (10 ** SAUCE_DECIMALS))
    needed_usdc_check = compute_amount1_for_amount0(
        hbar_raw_check, live_price, tick_lower, tick_upper, WHBAR_DECIMALS, SAUCE_DECIMALS
    )

    if needed_usdc_check > usdc_raw_check:
        # SAUCE is de beperkende kant -- teveel HBAR t.o.v. wat nodig is.
        # Swap de helft van het HBAR-overschot naar SAUCE.
        excess_usdc_needed = (needed_usdc_check - usdc_raw_check) / (10 ** SAUCE_DECIMALS)
        hbar_to_swap = (excess_usdc_needed / live_price) / 2
        print(f"\nSAUCE is beperkend -- {hbar_to_swap:.4f} HBAR omzetten naar SAUCE om te herbalanceren...")
        subprocess.run(
            ["python3", "execute_hbar_swap_standalone.py",
             "--direction", "HBAR_TO_USDC", "--amount", str(hbar_to_swap),
             "--network", "testnet", "--engine", "v2"],
            check=True,
        )
        # Extra pauze (26 aug 2026) -- de swap hierboven liep via een
        # APART subprocess, met zijn EIGEN RPC-client-instantie. De
        # centrale nonce-timing-fix in hedera_rpc_client.wait_for_receipt()
        # (time.sleep(2) na elke bevestigde tx) geldt alleen BINNEN
        # dezelfde procesinstantie -- hier moet de RPC-relay zijn nonce-
        # teller ook nog bijwerken voor DIT (andere) proces, wat empirisch
        # gezien niet altijd binnen de eigen 2s van het subprocess gebeurt.
        import time
        time.sleep(4)
        hbar_balance = float(client.get_hbar_balance())
        hbar_balance = max(0.0, hbar_balance - GAS_RESERVE_HBAR)
        sauce_balance = sauce_contract.functions.balanceOf(client.address).call() / (10 ** SAUCE_DECIMALS)
        print(f"Balans na herbalanceren: {hbar_balance:.4f} HBAR (na reserve) + {sauce_balance:.2f} SAUCE")
    else:
        print("\nHuidige verhouding is al voldoende voor volledige HBAR-inzet, geen swap nodig.")

    # DIAGNOSTISCHE AANPASSING (26 aug 2026): tijdelijk een klein, vast
    # bedrag gebruiken i.p.v. de volledige balans, om te testen of de
    # GROOTTE van het bedrag de oorzaak is van de lege revert bij deze
    # smalle LOW/Focused-range (hypothese: een zeer smalle range vereist
    # een veel grotere liquiditeitswaarde (L) per token-eenheid, wat bij
    # een groot bedrag mogelijk tegen een interne grens aanloopt).
    DIAGNOSTIC_SMALL_TEST = True
    if DIAGNOSTIC_SMALL_TEST:
        hbar_raw_available = int(1.0 * (10 ** WHBAR_DECIMALS))  # 1 HBAR
        usdc_raw_available = int(sauce_balance * (10 ** SAUCE_DECIMALS))
        needed_usdc_for_full_hbar = compute_amount1_for_amount0(
            hbar_raw_available, live_price, tick_lower, tick_upper, WHBAR_DECIMALS, SAUCE_DECIMALS
        )
        hbar_raw, usdc_raw = hbar_raw_available, min(needed_usdc_for_full_hbar, usdc_raw_available)
    else:
        hbar_raw_available = int(hbar_balance * (10 ** WHBAR_DECIMALS))
        usdc_raw_available = int(sauce_balance * (10 ** SAUCE_DECIMALS))
        needed_usdc_for_full_hbar = compute_amount1_for_amount0(
            hbar_raw_available, live_price, tick_lower, tick_upper, WHBAR_DECIMALS, SAUCE_DECIMALS
        )
        if needed_usdc_for_full_hbar <= usdc_raw_available:
            hbar_raw, usdc_raw = hbar_raw_available, needed_usdc_for_full_hbar
        else:
            usdc_raw = usdc_raw_available
            hbar_raw = compute_amount0_for_amount1(
                usdc_raw_available, live_price, tick_lower, tick_upper, WHBAR_DECIMALS, SAUCE_DECIMALS
            )

    print(f"\n=== Positie openen: {hbar_raw/(10**WHBAR_DECIMALS):.4f} HBAR "
          f"+ {usdc_raw/(10**SAUCE_DECIMALS):.2f} SAUCE ===")

    # Diagnostiek (26 aug 2026): exacte, actuele balans en de berekende
    # payable_value vergelijken, om te zien waar "Insufficient funds"
    # precies vandaan komt in plaats van te blijven gokken.
    actual_hbar_balance_now = float(client.get_hbar_balance())
    gas_price = client.w3.eth.gas_price
    print(f"Daadwerkelijke, actuele HBAR-balans (ongereserveerd): {actual_hbar_balance_now:.8f}")
    print(f"Bedoelde inzet (hbar_raw als HBAR): {hbar_raw / (10**WHBAR_DECIMALS):.8f}")
    print(f"Huidige gas-prijs (wei): {gas_price}")
    print(f"Geschatte max. gaskosten (HBAR): {(1_200_000 * gas_price * 1.2) / 10**18:.8f}")

    try:
        token_id = manager.open_position(
            hbar_raw, usdc_raw, live_price,
            volatility_regime=VolatilityRegime.LOW, sentiment_direction=0.0,
            slippage_tolerance=0.15, gas_limit_override=1_200_000,
        )
        print(f"GELUKT -- nieuwe positie: token_id={token_id}")

        db = PostgresClient()
        await db.connect()
        await db.clear_active_lp_position()
        await db.save_active_lp_position(token_id, tick_lower, tick_upper)
        await db.close()
        print("Database bijgewerkt.")
    except requests.exceptions.HTTPError as e:
        print(f"HTTP-statuscode: {e.response.status_code}")
        print(f"Ruwe responstekst:\n{e.response.text}")
    except Exception as e:
        print(f"MISLUKT: {e}")


if __name__ == "__main__":
    asyncio.run(main())
