"""
cleanup_narrow_positions.py

Sluit positie 345 (de complexere wrap+approve-aanpak) en behoudt 346 (de
eenvoudigere, alleen-grotere-msg.value-buffer-aanpak) als de ene, smalle
testpositie die actief blijft in de pool.
"""

import asyncio
import os

from hedera_rpc_client import HederaRpcClient, NetworkConfig
from hedera_address_utils import hedera_id_to_evm_address
from config import NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses
from lp_manager import LpManager, LpPositionConfig, POSITION_MANAGER_ABI
from postgres_client import PostgresClient

SAUCE_TESTNET_ID = "0.0.1183558"


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
        fee_tier=3000,
    )
    manager = LpManager(client, config)

    # Eerst bevestigen welke posities daadwerkelijk nog open staan.
    position_manager = client.w3.eth.contract(address=v2.position_manager, abi=POSITION_MANAGER_ABI)
    for token_id in [345, 346]:
        position = position_manager.functions.positions(token_id).call()
        print(f"tokenSN={token_id}: liquidity={position[5]}, "
              f"tickLower={position[3]}, tickUpper={position[4]}")

    print("\n=== Positie 345 sluiten (behoud 346) ===")
    close_tx = manager.close_position(345)
    print(f"Sluit-status: {'GELUKT' if close_tx else 'MISLUKT'}, tx={close_tx}")

    # Database bijwerken: 346 is nu de bekende, actieve positie.
    db = PostgresClient()
    await db.connect()
    position_346 = position_manager.functions.positions(346).call()
    await db.clear_active_lp_position()
    await db.save_active_lp_position(346, position_346[3], position_346[4])
    await db.close()
    print("Database bijgewerkt -- 346 is nu de bekende, actieve positie.")

    hbar_balance = client.get_hbar_balance()
    print(f"\nHBAR-balans na opruimen: {hbar_balance}")


if __name__ == "__main__":
    asyncio.run(main())
