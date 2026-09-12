"""
telegram_webhook.py -- tweerichtings-Telegram (fase 1b / fundament fase 4).

Pending-verzoeken leven in Postgres (telegram_pending_verzoeken, zie
migratie_telegram_pending.sql), niet meer in een in-memory dict -- dat brak
zodra een verzoek werd aangemaakt door een ander proces dan de draaiende
dashboard-server (bv. `docker compose exec ... --test`).

    docker compose exec -T dashboard python3 telegram_webhook.py --register
    docker compose exec -T dashboard python3 telegram_webhook.py --info
    docker compose exec -T dashboard python3 telegram_webhook.py --delete
    docker compose exec -T dashboard python3 telegram_webhook.py --test
"""
import asyncio
import os
import sys
import time
import uuid

import requests

from postgres_client import PostgresClient

API = "https://api.telegram.org"
DOMEIN = os.environ.get("DASHBOARD_DOMEIN", "187-124-8-211.sslip.io")
PENDING_TTL = 120


def _token():
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def _chat_id():
    return os.environ.get("TELEGRAM_CHAT_ID")


def _secret():
    return os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")


def stuur_met_knoppen(tekst: str, verzoek_id: str, ja_label="\u2705 Goedkeuren", nee_label="\u274c Weigeren") -> bool:
    url = f"{API}/bot{_token()}/sendMessage"
    payload = {
        "chat_id": _chat_id(),
        "text": tekst,
        "reply_markup": {
            "inline_keyboard": [[
                {"text": ja_label, "callback_data": f"ja:{verzoek_id}"},
                {"text": nee_label, "callback_data": f"nee:{verzoek_id}"},
            ]]
        },
    }
    r = requests.post(url, json=payload, timeout=15)
    return r.status_code == 200


async def nieuw_verzoek(db: PostgresClient, soort: str, omschrijving: str) -> str:
    vid = uuid.uuid4().hex[:12]
    await db.create_pending_verzoek(vid, soort, omschrijving)
    stuur_met_knoppen(f"\U0001f510 {omschrijving}\n\nWas jij dit? Bevestig binnen 2 minuten.", vid)
    return vid


def _antwoord_callback(antwoord_id: str, tekst: str) -> None:
    """Toont een korte, boven-in-beeld toast in Telegram (verdwijnt na een paar seconden)."""
    requests.post(f"{API}/bot{_token()}/answerCallbackQuery",
                  json={"callback_query_id": antwoord_id, "text": tekst, "show_alert": False}, timeout=10)


def _bewerk_bericht(chat_id, message_id, tekst: str) -> None:
    """Past het oorspronkelijke bericht aan (bv. '\u2705 Goedgekeurd') en verwijdert de knoppen,
    zodat er een blijvend, zichtbaar bewijs in de chat staat -- niet alleen een toast."""
    requests.post(f"{API}/bot{_token()}/editMessageText", json={
        "chat_id": chat_id,
        "message_id": message_id,
        "text": tekst,
        "reply_markup": {"inline_keyboard": []},
    }, timeout=10)


async def verwerk_callback(db: PostgresClient, update: dict) -> dict:
    cq = update.get("callback_query")
    if not cq:
        return {"ok": False, "reden": "geen callback_query"}
    from_id = str(cq.get("from", {}).get("id", ""))
    if _chat_id() and from_id != str(_chat_id()):
        return {"ok": False, "reden": "onbekende afzender"}
    data = cq.get("data", "")
    antwoord_id = cq.get("id")
    msg = cq.get("message", {}) or {}
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    oorspronkelijke_tekst = msg.get("text", "")
    try:
        keuze, vid = data.split(":", 1)
    except ValueError:
        if antwoord_id:
            _antwoord_callback(antwoord_id, "Ongeldig verzoek")
        return {"ok": False, "reden": "ongeldige data"}
    p = await db.get_pending_verzoek(vid)
    if not p:
        if antwoord_id:
            _antwoord_callback(antwoord_id, "\u26a0\ufe0f Onbekend of verlopen")
        return {"ok": False, "reden": "verzoek onbekend/verlopen"}
    if time.time() - p["aangemaakt"].timestamp() > PENDING_TTL:
        await db.resolve_pending_verzoek(vid, "verlopen")
        if antwoord_id:
            _antwoord_callback(antwoord_id, "\u231b Verlopen")
        if chat_id and message_id:
            _bewerk_bericht(chat_id, message_id, f"{oorspronkelijke_tekst}\n\n\u231b Verlopen -- niet meer geldig.")
        return {"ok": False, "reden": "verlopen", "soort": p["soort"]}
    nieuwe_status = "goedgekeurd" if keuze == "ja" else "geweigerd"
    gelukt = await db.resolve_pending_verzoek(vid, nieuwe_status)
    if not gelukt:
        if antwoord_id:
            _antwoord_callback(antwoord_id, "Al verwerkt")
        return {"ok": False, "reden": "al verwerkt", "soort": p["soort"]}
    if antwoord_id:
        _antwoord_callback(antwoord_id, "\u2705 Verwerkt" if nieuwe_status == "goedgekeurd" else "\u274c Verwerkt")
    if chat_id and message_id:
        icoon = "\u2705 Goedgekeurd" if nieuwe_status == "goedgekeurd" else "\u274c Geweigerd"
        _bewerk_bericht(chat_id, message_id, f"{oorspronkelijke_tekst}\n\n{icoon}")
    return {"ok": True, "status": nieuwe_status, "soort": p["soort"], "verzoek_id": vid}


async def verzoek_status(db: PostgresClient, vid: str) -> str:
    p = await db.get_pending_verzoek(vid)
    if not p:
        return "onbekend"
    if p["status"] == "open" and time.time() - p["aangemaakt"].timestamp() > PENDING_TTL:
        return "verlopen"
    return p["status"]


def _register():
    url = f"{API}/bot{_token()}/setWebhook"
    payload = {"url": f"https://{DOMEIN}/telegram/webhook", "secret_token": _secret(),
               "allowed_updates": ["callback_query"]}
    r = requests.post(url, json=payload, timeout=15)
    print(r.status_code, r.text)


def _info():
    r = requests.get(f"{API}/bot{_token()}/getWebhookInfo", timeout=15)
    print(r.text)


def _delete():
    r = requests.post(f"{API}/bot{_token()}/deleteWebhook", timeout=15)
    print(r.text)


async def _test():
    db = PostgresClient()
    await db.connect()
    try:
        vid = await nieuw_verzoek(db, "test", "Testverzoek vanuit telegram_webhook.py")
        print(f"testbericht gestuurd, verzoek_id={vid} -- tik Goedkeuren of Weigeren in Telegram")
    finally:
        await db.close()


if __name__ == "__main__":
    a = sys.argv
    if "--register" in a: _register()
    elif "--info" in a: _info()
    elif "--delete" in a: _delete()
    elif "--test" in a: asyncio.run(_test())
    else:
        print("gebruik: --register | --info | --delete | --test")
