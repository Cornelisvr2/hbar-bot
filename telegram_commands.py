"""
telegram_commands.py

Interactieve Telegram-commando's voor de bot -- in tegenstelling tot
telegram_notify.py (puur eenrichtingsverkeer, alleen versturen), kan
deze module berichten ONTVANGEN via Telegram's getUpdates-polling en
erop reageren.

Ondersteunde commando's (26 aug 2026: teruggezet naar korte namen -- deze
bot heeft nu een EIGEN, apart Telegram-bot-token (@Hbar_lp_bot), losstaand
van het scalper-tradingbot-project, dus geen botsingsrisico meer):
  /status   -- huidig regime, laatste combined_score, of gepauzeerd
  /pause    -- stopt nieuwe regime-overgangen (bestaande positie blijft
               gewoon open, alleen geen NIEUWE acties meer)
  /resume   -- hervat normale werking
  /balance  -- huidige HBAR-balans

Ontworpen om NAAST de bestaande hoofdloop te draaien, zonder die te
verstoren: check_for_commands() wordt elke cyclus kort aangeroepen
(niet-blokkerend, korte timeout), en beinvloedt het gedrag alleen via
de gedeelde BotCommandState.
"""

import os
import requests


TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"


class BotCommandState:
    """Gedeelde staat tussen de commando-poller en de hoofdloop."""

    def __init__(self):
        self.paused = False
        self.last_update_id = 0


async def check_for_commands(state: BotCommandState, regime_orchestrator) -> None:
    """
    Vraagt eenmalig nieuwe Telegram-berichten op (korte timeout, niet-
    blokkerend voor de rest van de bot) en verwerkt eventuele commando's.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    url = f"{TELEGRAM_API_BASE.format(token=token)}/getUpdates"
    params = {"offset": state.last_update_id + 1, "timeout": 1}

    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        updates = response.json().get("result", [])
    except Exception:
        return  # netwerkfout ophalen van commando's mag de hoofdloop nooit breken

    for update in updates:
        state.last_update_id = update["update_id"]
        message = update.get("message", {})
        text = message.get("text", "").strip().lower()
        incoming_chat_id = str(message.get("chat", {}).get("id", ""))

        if incoming_chat_id != str(chat_id):
            continue  # alleen reageren op berichten uit de eigen, geconfigureerde chat

        if text == "/pause":
            state.paused = True
            _reply(token, chat_id, "Bot gepauzeerd. Bestaande posities blijven open, "
                                     "geen nieuwe regime-overgangen totdat je /resume stuurt.")
        elif text == "/resume":
            state.paused = False
            _reply(token, chat_id, "Bot hervat. Normale werking weer actief.")
        elif text == "/status":
            _reply(token, chat_id, _format_status(state, regime_orchestrator))
        elif text == "/balance":
            _reply(token, chat_id, _format_balance(regime_orchestrator))
        elif text.startswith("/"):
            _reply(token, chat_id, "Onbekend commando. Beschikbaar: /status, /pause, "
                                     "/resume, /balance")
        # Overige commando's (bv. voor een andere bot in dezelfde chat)
        # bewust NEGEREN -- geen "onbekend commando"-ruis voor iets dat
        # niet voor deze bot bedoeld was.


def _reply(token: str, chat_id: str, text: str) -> None:
    url = f"{TELEGRAM_API_BASE.format(token=token)}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=5)
    except Exception:
        pass  # een mislukte reply mag de hoofdloop nooit breken


def _format_status(state: BotCommandState, regime_orchestrator) -> str:
    paused_text = "GEPAUZEERD" if state.paused else "actief"
    regime = getattr(regime_orchestrator, "current_regime", None)
    regime_text = regime.value if regime else "onbekend"
    return f"Status: {paused_text}\nHuidig regime: {regime_text}"


def _format_balance(regime_orchestrator) -> str:
    rpc_client = getattr(regime_orchestrator, "rpc_client", None)
    if not rpc_client:
        return "Geen RPC-verbinding beschikbaar."
    try:
        hbar_balance = rpc_client.get_hbar_balance()
        return f"HBAR-balans: {hbar_balance:.4f}"
    except Exception as e:
        return f"Kon balans niet ophalen: {e}"
