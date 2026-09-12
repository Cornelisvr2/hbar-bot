"""
telegram_webhook.py -- tweerichtings-Telegram (fase 1b / fundament fase 4).

De bestaande telegram_notify.py kan alleen berichten STUREN. Deze module voegt
toe: berichten met knoppen (inline keyboard) sturen, en de knop-taps ONTVANGEN
via een Telegram-webhook. Fundament voor: login-goedkeuring (nu) en de
bedieningsknoppen met 2-factor (later).

Beveiliging:
- Webhook-URL: https://<domein>/telegram/webhook
- Telegram stuurt een geheime header (X-Telegram-Bot-Api-Secret-Token) mee die
  we vergelijken met TELEGRAM_WEBHOOK_SECRET -> niemand anders kan nep-callbacks
  sturen.
- Alleen callbacks van de bekende TELEGRAM_CHAT_ID worden geaccepteerd.

Pending-verzoeken (login of actie) leven in het geheugen met een verloop van
PENDING_TTL seconden.

Eenmalig de webhook registreren bij Telegram:
    docker compose exec -T dashboard python3 telegram_webhook.py --register
Status bekijken / verwijderen:
    docker compose exec -T dashboard python3 telegram_webhook.py --info
    docker compose exec -T dashboard python3 telegram_webhook.py --delete
Testbericht met Ja/Nee-knop sturen:
    docker compose exec -T dashboard python3 telegram_webhook.py --test
"""
import os
import sys
import time
import uuid

import requests

API = "https://api.telegram.org"
DOMEIN = os.environ.get("DASHBOARD_DOMEIN", "187-124-8-211.sslip.io")
PENDING_TTL = 120  # seconden dat een verzoek geldig is

# in-memory pending-verzoeken: id -> {soort, aangemaakt, status}
_pending: dict[str, dict] = {}


def _token():
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def _chat_id():
    return os.environ.get("TELEGRAM_CHAT_ID")


def _secret():
    return os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")


def stuur_met_knoppen(tekst: str, verzoek_id: str, ja_label="✅ Goedkeuren", nee_label="❌ Weigeren") -> bool:
    """Stuur een bericht met twee inline-knoppen; callback_data = <ja|nee>:<verzoek_id>."""
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


def nieuw_verzoek(soort: str, omschrijving: str) -> str:
    """Maak een pending-verzoek en stuur de Telegram-vraag. Retourneert het id."""
    vid = uuid.uuid4().hex[:12]
    _pending[vid] = {"soort": soort, "omschrijving": omschrijving, "aangemaakt": time.time(), "status": "open"}
    stuur_met_knoppen(f"🔐 {omschrijving}\n\nWas jij dit? Bevestig binnen 2 minuten.", vid)
    return vid


def verwerk_callback(update: dict) -> dict:
    """Verwerk een binnenkomende callback_query. Retourneert {ok, status, soort}."""
    cq = update.get("callback_query")
    if not cq:
        return {"ok": False, "reden": "geen callback_query"}
    # alleen van ons eigen account
    from_id = str(cq.get("from", {}).get("id", ""))
    if _chat_id() and from_id != str(_chat_id()):
        return {"ok": False, "reden": "onbekende afzender"}
    data = cq.get("data", "")
    antwoord_id = cq.get("id")
    try:
        keuze, vid = data.split(":", 1)
    except ValueError:
        return {"ok": False, "reden": "ongeldige data"}
    p = _pending.get(vid)
    # bevestig de tap naar Telegram (haalt het "laden"-cirkeltje weg)
    if antwoord_id:
        requests.post(f"{API}/bot{_token()}/answerCallbackQuery",
                      json={"callback_query_id": antwoord_id}, timeout=10)
    if not p:
        return {"ok": False, "reden": "verzoek onbekend/verlopen"}
    if time.time() - p["aangemaakt"] > PENDING_TTL:
        p["status"] = "verlopen"
        return {"ok": False, "reden": "verlopen", "soort": p["soort"]}
    p["status"] = "goedgekeurd" if keuze == "ja" else "geweigerd"
    return {"ok": True, "status": p["status"], "soort": p["soort"], "verzoek_id": vid}


def verzoek_status(vid: str) -> str:
    p = _pending.get(vid)
    if not p:
        return "onbekend"
    if p["status"] == "open" and time.time() - p["aangemaakt"] > PENDING_TTL:
        return "verlopen"
    return p["status"]


# ---- beheer (CLI) ----
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


def _test():
    vid = nieuw_verzoek("test", "Testverzoek vanuit telegram_webhook.py")
    print(f"testbericht gestuurd, verzoek_id={vid} -- tik Goedkeuren of Weigeren in Telegram")


if __name__ == "__main__":
    a = sys.argv
    if "--register" in a: _register()
    elif "--info" in a: _info()
    elif "--delete" in a: _delete()
    elif "--test" in a: _test()
    else:
        print("gebruik: --register | --info | --delete | --test")
