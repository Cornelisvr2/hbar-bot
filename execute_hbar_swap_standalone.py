"""
execute_hbar_swap_standalone.py -- HBAR Bot, Losgekoppelde Trade-uitvoering

Zelfde patroon als execute_vix_rider_trade_standalone.py: de swap-uitvoering
(wachten op tx-confirmatie, wat 5-15 seconden kan duren op Hedera) mag de
aanroepende monitoringlus (main_orchestrator.py) niet blokkeren terwijl die
ondertussen door moet gaan met het pollen van nieuwe sentiment-signalen.

Gebruik (aangeroepen door main_orchestrator.py, niet handmatig):
    python3 execute_hbar_swap_standalone.py --direction HBAR_TO_USDC \
        --amount 50.0 --network testnet --engine v1

    python3 execute_hbar_swap_standalone.py --direction USDC_TO_HBAR \
        --amount 25.0 --network mainnet --engine v2 --fee-tier 3000
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LOG_DIR = os.environ.get("HBAR_BOT_LOG_DIR", "/opt/hbar_bot/logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s|%(levelname)-.1s| %(message)s",
    filename=os.path.join(LOG_DIR, f"hbar_swap_{os.getpid()}.log"),
)
logger = logging.getLogger("execute_hbar_swap_standalone")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--direction", required=True, choices=["HBAR_TO_USDC", "USDC_TO_HBAR"])
    parser.add_argument("--amount", required=True, type=float)
    parser.add_argument("--network", required=True, choices=["testnet", "mainnet"])
    parser.add_argument("--engine", required=True, choices=["v1", "v2"])
    parser.add_argument("--fee-tier", type=int, default=3000, help="Alleen relevant voor engine=v2")
    parser.add_argument("--slippage", type=float, default=0.01)
    args = parser.parse_args()

    logger.info(
        f"Losgekoppeld HBAR-swap-proces gestart: {args.direction} {args.amount} "
        f"op {args.network} via engine={args.engine}, PID {os.getpid()}"
    )

    from hedera_rpc_client import HederaRpcClient, NetworkConfig
    from config import NETWORK_SETTINGS

    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    if not private_key:
        logger.error("HEDERA_BOT_PRIVATE_KEY niet gezet -- kan niet handelen.")
        sys.exit(1)

    settings = NETWORK_SETTINGS[args.network]
    network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
    client = HederaRpcClient(network, private_key)

    try:
        if args.engine == "v1":
            from swap_executor import SwapExecutor, build_swap_config
            config = build_swap_config(args.network, slippage_tolerance=args.slippage)
            executor = SwapExecutor(client, config)

            # On-chain verificatie voordat er geld beweegt
            if not executor.verify_whbar_address():
                raise RuntimeError("WHBAR-adres mismatch met Router -- swap afgebroken.")

            if args.direction == "HBAR_TO_USDC":
                result = executor.swap_hbar_to_usdc(args.amount)
            else:
                result = executor.swap_usdc_to_hbar(args.amount)

        else:  # v2
            from swap_executor_v2 import SwapExecutorV2, build_swap_config_v2
            config = build_swap_config_v2(
                args.network, fee_tier=args.fee_tier, slippage_tolerance=args.slippage
            )
            executor = SwapExecutorV2(client, config)

            if args.direction == "HBAR_TO_USDC":
                result = executor.swap_hbar_to_usdc(args.amount)
            else:
                result = executor.swap_usdc_to_hbar(args.amount)

        logger.info(f"Swap afgerond: {result}")
        _notify(f"[HBAR Bot] Swap {result.status.upper()}: {args.direction} "
                f"{args.amount} (engine={args.engine}) -- tx: {result.tx_hash}")

        # Gestructureerde output naar stdout (23 aug 2026): het aanroepende
        # proces (regime_orchestrator.py, via subprocess) kon tot nu toe
        # NIETS van dit resultaat opvangen -- tx_hash, estimated_amount_out
        # en actual_amount_out werden altijd als None gelogd naar de
        # trades-tabel, wat elke vorm van winst/verlies-analyse onmogelijk
        # maakte. Deze regel print als ALLERLAATSTE stdout-regel een JSON-
        # object dat de aanroeper kan parsen.
        print(json.dumps({
            "tx_hash": result.tx_hash,
            "status": result.status,
            "amount_in": result.amount_in,
            "estimated_amount_out": result.estimated_amount_out,
            "direction": result.direction,
            "fee_tier": result.fee_tier,
        }))

    except Exception as e:
        logger.error(f"Onverwachte fout in losgekoppeld HBAR-swap-proces: {e}")
        _notify(f"[HBAR Bot] \u26a0\ufe0f Fout bij swap ({args.direction}, {args.amount}): {e}")
        sys.exit(1)


def _notify(message: str):
    try:
        from telegram_notify import send_telegram_message
        send_telegram_message(message)
    except Exception:
        logger.warning("Kon geen Telegram-notificatie versturen (telegram_notify.py nog niet aanwezig).")


if __name__ == "__main__":
    main()
