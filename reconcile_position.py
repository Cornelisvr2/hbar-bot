from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)
    lp = orchestrator.lp_manager
    client = orchestrator.rpc_client

    print("=== In het geheugen van de bot (lp_manager.state) ===")
    print(f"is_open: {lp.state.is_open}")
    if lp.state.is_open:
        print(f"token_id: {lp.state.token_id}")
        print(f"tick_lower: {lp.state.tick_lower}, tick_upper: {lp.state.tick_upper}")

    print()
    print("=== In de database (active_lp_position) ===")
    db_positie = await db.get_active_lp_position()
    print(f"DB-record: {db_positie}")

    print()
    print("=== Meest recente NFT's van dit account (mirror node) ===")
    import requests
    resp = requests.get(f"https://testnet.mirrornode.hedera.com/api/v1/accounts/{client.address}", timeout=15)
    hedera_account_id = resp.json().get("account")
    nft_resp = requests.get(
        f"https://testnet.mirrornode.hedera.com/api/v1/accounts/{hedera_account_id}/nfts?limit=10&order=desc",
        timeout=15,
    )
    for nft in nft_resp.json().get("nfts", []):
        print(f"token_id={nft['token_id']} serial={nft['serial_number']} "
              f"created={nft.get('created_timestamp')}")

    await db.close()

asyncio.run(main())
