"""
pas_telegram_fix_toe.py -- past de Postgres-backed telegram_webhook-fix toe.

Draai dit EENMALIG vanuit /root/hbar_bot op de VPS:
    python3 pas_telegram_fix_toe.py

Doet, in volgorde:
1. Voegt drie nieuwe async methods toe aan de PostgresClient-klasse in
   postgres_client.py (create_pending_verzoek, get_pending_verzoek,
   resolve_pending_verzoek).
2. Vervangt telegram_webhook.py volledig door de Postgres-backed versie
   (i.p.v. de in-memory _pending-dict die het proces-isolatie-probleem gaf).
3. Vervangt de webhook-route in dashboard_server.py door de async,
   Postgres-gebruikende versie.

Maakt van elk bestand eerst een .bak-kopie. Stopt met een duidelijke
foutmelding (zonder iets te wijzigen) als een verwacht ankerpunt niet
gevonden wordt -- dus geen halve toepassing.
"""
import shutil
import sys

POSTGRES_CLIENT_PAD = "postgres_client.py"
TELEGRAM_WEBHOOK_PAD = "telegram_webhook.py"
DASHBOARD_SERVER_PAD = "dashboard_server.py"

NIEUWE_POSTGRES_METHODS = '''
    async def create_pending_verzoek(self, vid: str, soort: str, omschrijving: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO telegram_pending_verzoeken (id, soort, omschrijving, status)
                VALUES ($1, $2, $3, 'open')
                """,
                vid, soort, omschrijving,
            )

    async def get_pending_verzoek(self, vid: str):
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, soort, omschrijving, status, aangemaakt
                FROM telegram_pending_verzoeken WHERE id = $1
                """,
                vid,
            )
            return dict(row) if row else None

    async def resolve_pending_verzoek(self, vid: str, status: str) -> bool:
        """
        Zet een 'open' verzoek op de gegeven status. Retourneert False als het
        verzoek niet bestond of al niet meer 'open' was -- atomisch via
        WHERE status='open', zodat een dubbele tap niet twee keer "slaagt".
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE telegram_pending_verzoeken
                SET status = $2
                WHERE id = $1 AND status = 'open'
                RETURNING id
                """,
                vid, status,
            )
            return row is not None
'''

NIEUWE_TELEGRAM_WEBHOOK = '''"""
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


def stuur_met_knoppen(tekst: str, verzoek_id: str, ja_label="\\u2705 Goedkeuren", nee_label="\\u274c Weigeren") -> bool:
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
    stuur_met_knoppen(f"\\U0001f510 {omschrijving}\\n\\nWas jij dit? Bevestig binnen 2 minuten.", vid)
    return vid


async def verwerk_callback(db: PostgresClient, update: dict) -> dict:
    cq = update.get("callback_query")
    if not cq:
        return {"ok": False, "reden": "geen callback_query"}
    from_id = str(cq.get("from", {}).get("id", ""))
    if _chat_id() and from_id != str(_chat_id()):
        return {"ok": False, "reden": "onbekende afzender"}
    data = cq.get("data", "")
    antwoord_id = cq.get("id")
    try:
        keuze, vid = data.split(":", 1)
    except ValueError:
        return {"ok": False, "reden": "ongeldige data"}
    p = await db.get_pending_verzoek(vid)
    if antwoord_id:
        requests.post(f"{API}/bot{_token()}/answerCallbackQuery",
                      json={"callback_query_id": antwoord_id}, timeout=10)
    if not p:
        return {"ok": False, "reden": "verzoek onbekend/verlopen"}
    if time.time() - p["aangemaakt"].timestamp() > PENDING_TTL:
        await db.resolve_pending_verzoek(vid, "verlopen")
        return {"ok": False, "reden": "verlopen", "soort": p["soort"]}
    nieuwe_status = "goedgekeurd" if keuze == "ja" else "geweigerd"
    gelukt = await db.resolve_pending_verzoek(vid, nieuwe_status)
    if not gelukt:
        return {"ok": False, "reden": "al verwerkt", "soort": p["soort"]}
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
'''

OUDE_WEBHOOK_ROUTE = '''@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Ontvangt Telegram callback_query's (knop-taps). Checkt de secret-header
    zodat alleen Telegram zelf hier binnenkomt. Fundament voor login-goedkeuring
    en de bedieningsknoppen met 2-factor."""
    import os as _os
    from telegram_webhook import verwerk_callback
    verwacht = _os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    gekregen = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if verwacht and gekregen != verwacht:
        return JSONResponse({"ok": False, "reden": "ongeldige secret"}, status_code=403)
    update = await request.json()
    resultaat = verwerk_callback(update)
    print(f"[telegram-webhook] {resultaat}")
    return JSONResponse({"ok": True})'''

NIEUWE_WEBHOOK_ROUTE = '''@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Ontvangt Telegram callback_query's (knop-taps). Checkt de secret-header
    zodat alleen Telegram zelf hier binnenkomt. Fundament voor login-goedkeuring
    en de bedieningsknoppen met 2-factor."""
    import os as _os
    from telegram_webhook import verwerk_callback
    verwacht = _os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    gekregen = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if verwacht and gekregen != verwacht:
        return JSONResponse({"ok": False, "reden": "ongeldige secret"}, status_code=403)
    update = await request.json()
    db = PostgresClient()
    await db.connect()
    try:
        resultaat = await verwerk_callback(db, update)
    finally:
        await db.close()
    print(f"[telegram-webhook] {resultaat}")
    return JSONResponse({"ok": True})'''


def _fail(msg):
    print(f"FOUT: {msg} -- er is niets gewijzigd.", file=sys.stderr)
    sys.exit(1)


def main():
    # --- 1. postgres_client.py ---
    with open(POSTGRES_CLIENT_PAD) as f:
        pc = f.read()
    anker_pc = "    async def close(self):\n        if self._pool:\n            await self._pool.close()\n"
    if anker_pc not in pc:
        _fail(f"ankerpunt niet gevonden in {POSTGRES_CLIENT_PAD} (mogelijk al gewijzigd?)")
    if "create_pending_verzoek" in pc:
        print(f"{POSTGRES_CLIENT_PAD}: methods staan er al, overslaan.")
    else:
        shutil.copy(POSTGRES_CLIENT_PAD, POSTGRES_CLIENT_PAD + ".bak")
        pc = pc.replace(anker_pc, anker_pc + NIEUWE_POSTGRES_METHODS, 1)
        with open(POSTGRES_CLIENT_PAD, "w") as f:
            f.write(pc)
        print(f"{POSTGRES_CLIENT_PAD}: methods toegevoegd (backup: {POSTGRES_CLIENT_PAD}.bak)")

    # --- 2. telegram_webhook.py ---
    shutil.copy(TELEGRAM_WEBHOOK_PAD, TELEGRAM_WEBHOOK_PAD + ".bak")
    with open(TELEGRAM_WEBHOOK_PAD, "w") as f:
        f.write(NIEUWE_TELEGRAM_WEBHOOK)
    print(f"{TELEGRAM_WEBHOOK_PAD}: volledig vervangen (backup: {TELEGRAM_WEBHOOK_PAD}.bak)")

    # --- 3. dashboard_server.py ---
    with open(DASHBOARD_SERVER_PAD) as f:
        ds = f.read()
    if OUDE_WEBHOOK_ROUTE not in ds:
        if NIEUWE_WEBHOOK_ROUTE in ds:
            print(f"{DASHBOARD_SERVER_PAD}: route staat er al in de nieuwe vorm, overslaan.")
        else:
            _fail(f"ankerpunt (oude webhook-route) niet gevonden in {DASHBOARD_SERVER_PAD}")
    else:
        shutil.copy(DASHBOARD_SERVER_PAD, DASHBOARD_SERVER_PAD + ".bak")
        ds = ds.replace(OUDE_WEBHOOK_ROUTE, NIEUWE_WEBHOOK_ROUTE, 1)
        with open(DASHBOARD_SERVER_PAD, "w") as f:
            f.write(ds)
        print(f"{DASHBOARD_SERVER_PAD}: webhook-route bijgewerkt (backup: {DASHBOARD_SERVER_PAD}.bak)")

    print("\nKlaar. Vervolgstappen:")
    print("1. Migratie draaien (nog niet gedaan door dit script):")
    print("   docker compose exec -T database psql -U hbar_bot -d hbar_bot < migratie_telegram_pending.sql")
    print("2. Container herstarten: docker compose restart dashboard")
    print("3. Opnieuw testen: docker compose exec -T dashboard python3 telegram_webhook.py --test")


if __name__ == "__main__":
    main()
