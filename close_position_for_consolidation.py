# close_position_for_consolidation.py
#
# Eenmalig script (30 aug 2026, op verzoek) om de bestaande LP-positie te
# sluiten, zodat de bot 'm na een HERSTART automatisch heropent via het
# bestaande vangnet-mechanisme -- met de nieuwe, zojuist verhoogde
# 50-HBAR-reserve (MIN_GAS_RESERVE_HBAR) al actief, en met alle
# beschikbare kapitaal (wallet + vrijgekomen positie) opnieuw verdeeld.
#
# BELANGRIJK, TWEEMAAL GECORRIGEERD BIJ HET BOUWEN:
# 1. Gebruikt een ECHTE PostgresClient (niet MagicMock) -- de opstart-
#    reconciliatie hieronder heeft daadwerkelijke database-toegang nodig
#    om lp_manager.state correct met de on-chain realiteit te
#    synchroniseren; zonder dit zou het script ONTERECHT denken dat er
#    geen positie open staat (LpManager.state.is_open is puur in-memory
#    en begint standaard op False).
# 2. Sluit de positie via een APARTE, tijdelijke orchestrator-instantie --
#    de AL-DRAAIENDE bot (ander proces, in de container) merkt dit NIET
#    automatisch, want die leest zijn eigen lp_manager.state alleen bij
#    het opstarten opnieuw in. Daarom is een HERSTART van de bot-container
#    vereist na dit script (niet slechts wachten), om het vangnet
#    daadwerkelijk te laten vuren.

import asyncio
from regime_orchestrator import RegimeOrchestrator
from postgres_client import PostgresClient


async def main():
    db = PostgresClient()
    await db.connect()

    orchestrator = RegimeOrchestrator(db)

    if not orchestrator.lp_manager:
        print("FOUT: lp_manager kon niet worden opgezet (ontbrekende private key?).")
        await db.close()
        return

    # Reconciliatie -- synchroniseert lp_manager.state met de
    # daadwerkelijke, on-chain situatie (zie bestandskop hierboven).
    await orchestrator._reconcile_lp_position_on_startup()

    if not orchestrator.lp_manager.state.is_open:
        print("Geen actieve, open positie gevonden -- niets te sluiten.")
        await db.close()
        return

    token_id = orchestrator.lp_manager.state.token_id
    print(f"Sluit positie {token_id}...")

    tx_hash = orchestrator.lp_manager.close_position(token_id)
    print(f"Positie {token_id} gesloten. Transactie: {tx_hash}")

    await db.clear_active_lp_position()
    print("Databaserij gewist.")

    print(
        "\nVOLGENDE STAP, HANDMATIG VEREIST: herstart de bot-container "
        "(docker compose up -d --build --force-recreate) -- pas dan "
        "detecteert de LIVE bot dat de positie weg is en heropent het "
        "vangnet automatisch, met de 50 HBAR-reserve al actief."
    )
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
