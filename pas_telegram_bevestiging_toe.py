"""
pas_telegram_bevestiging_toe.py -- voegt zichtbare bevestiging toe na een tik
op Goedkeuren/Weigeren: een korte toast in Telegram EN het bericht zelf wordt
bijgewerkt (bv. "✅ Goedgekeurd"), knoppen verdwijnen.

Draai dit vanuit /root/hbar_bot, NA de eerdere pas_telegram_fix_toe.py (dit
script patcht de al-Postgres-backed versie van telegram_webhook.py, niet de
oorspronkelijke in-memory versie).

    python3 pas_telegram_bevestiging_toe.py
    docker compose up -d --build dashboard
"""
import shutil
import sys

PAD = "telegram_webhook.py"

OUDE_VERWERK_CALLBACK = '''async def verwerk_callback(db: PostgresClient, update: dict) -> dict:
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
    return {"ok": True, "status": nieuwe_status, "soort": p["soort"], "verzoek_id": vid}'''

NIEUWE_VERWERK_CALLBACK = '''def _antwoord_callback(antwoord_id: str, tekst: str) -> None:
    """Toont een korte, boven-in-beeld toast in Telegram (verdwijnt na een paar seconden)."""
    requests.post(f"{API}/bot{_token()}/answerCallbackQuery",
                  json={"callback_query_id": antwoord_id, "text": tekst, "show_alert": False}, timeout=10)


def _bewerk_bericht(chat_id, message_id, tekst: str) -> None:
    """Past het oorspronkelijke bericht aan (bv. '\\u2705 Goedgekeurd') en verwijdert de knoppen,
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
            _antwoord_callback(antwoord_id, "\\u26a0\\ufe0f Onbekend of verlopen")
        return {"ok": False, "reden": "verzoek onbekend/verlopen"}
    if time.time() - p["aangemaakt"].timestamp() > PENDING_TTL:
        await db.resolve_pending_verzoek(vid, "verlopen")
        if antwoord_id:
            _antwoord_callback(antwoord_id, "\\u231b Verlopen")
        if chat_id and message_id:
            _bewerk_bericht(chat_id, message_id, f"{oorspronkelijke_tekst}\\n\\n\\u231b Verlopen -- niet meer geldig.")
        return {"ok": False, "reden": "verlopen", "soort": p["soort"]}
    nieuwe_status = "goedgekeurd" if keuze == "ja" else "geweigerd"
    gelukt = await db.resolve_pending_verzoek(vid, nieuwe_status)
    if not gelukt:
        if antwoord_id:
            _antwoord_callback(antwoord_id, "Al verwerkt")
        return {"ok": False, "reden": "al verwerkt", "soort": p["soort"]}
    if antwoord_id:
        _antwoord_callback(antwoord_id, "\\u2705 Verwerkt" if nieuwe_status == "goedgekeurd" else "\\u274c Verwerkt")
    if chat_id and message_id:
        icoon = "\\u2705 Goedgekeurd" if nieuwe_status == "goedgekeurd" else "\\u274c Geweigerd"
        _bewerk_bericht(chat_id, message_id, f"{oorspronkelijke_tekst}\\n\\n{icoon}")
    return {"ok": True, "status": nieuwe_status, "soort": p["soort"], "verzoek_id": vid}'''


def main():
    with open(PAD) as f:
        inhoud = f.read()

    if NIEUWE_VERWERK_CALLBACK in inhoud:
        print(f"{PAD}: bevestiging staat er al in, niets te doen.")
        return

    if OUDE_VERWERK_CALLBACK not in inhoud:
        print(
            f"FOUT: ankerpunt niet gevonden in {PAD}. "
            "Draai je dit script tegen de Postgres-backed versie (na pas_telegram_fix_toe.py)? "
            "Er is niets gewijzigd.",
            file=sys.stderr,
        )
        sys.exit(1)

    shutil.copy(PAD, PAD + ".bak2")
    inhoud = inhoud.replace(OUDE_VERWERK_CALLBACK, NIEUWE_VERWERK_CALLBACK, 1)
    with open(PAD, "w") as f:
        f.write(inhoud)
    print(f"{PAD}: bevestiging toegevoegd (backup: {PAD}.bak2)")
    print("\nVervolgstap: docker compose up -d --build dashboard")


if __name__ == "__main__":
    main()
