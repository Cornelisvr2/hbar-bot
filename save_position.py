from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient
import asyncio

async def main():
    db = PostgresClient()
    await db.connect()
    orchestrator = RegimeOrchestrator(db)

    await orchestrator._reconcile_lp_position_on_startup()

    lp = orchestrator.lp_manager
    print(f'lp.state.is_open: {lp.state.is_open}')
    print(f'lp.state.token_id: {lp.state.token_id}')
    print(f'lp.state.tick_lower: {lp.state.tick_lower}, tick_upper: {lp.state.tick_upper}')

    bestaande = await db.get_active_lp_position()
    print(f'Database heeft al een record: {bestaande}')

    if lp.state.is_open and not bestaande:
        print('Database mist de positie -- nu alsnog opslaan...')
        await db.save_active_lp_position(
            lp.state.token_id, lp.state.tick_lower, lp.state.tick_upper,
        )
        print('Opgeslagen.')
    elif not lp.state.is_open:
        print('LET OP: geen open positie gevonden on-chain bij de reconciliatie.')

    await db.close()

asyncio.run(main())
