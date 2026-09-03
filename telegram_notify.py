"""
telegram_notify.py

Notificatie- en rapportagelaag via Telegram. Wordt al aangeroepen door
execute_hbar_swap_standalone.py (from telegram_notify import
send_telegram_message) -- deze module maakt die import compleet en voegt
rijkere rapportage toe: dagelijkse samenvattingen, sentiment-alerts, en
circuit-breaker-meldingen (safety_override.py).

Setup:
1. Maak een bot via @BotFather op Telegram, krijg een TELEGRAM_BOT_TOKEN
2. Stuur je bot een bericht, haal je chat_id op via:
   https://api.telegram.org/bot<TOKEN>/getUpdates
3. Zet beide als environment variables (zie .env.example)
"""

import os
import requests
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


TELEGRAM_API_BASE = "https://api.telegram.org"


def send_telegram_message(message: str, parse_mode: str = None) -> bool:
    """
    Basis-verstuurfunctie. Faalt stil (retourneert False, logt geen
    exception) als env vars ontbreken -- dit wordt door de aanroepende
    losgekoppelde subprocessen al met een try/except omringd (zie
    execute_hbar_swap_standalone.py), dus hier geen harde crash.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("WAARSCHUWING: TELEGRAM_BOT_TOKEN of TELEGRAM_CHAT_ID niet gezet -- bericht niet verstuurd.")
        print(f"--- Inhoud van het niet-verstuurde bericht ---\n{message}\n---")
        return False

    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"FOUT bij versturen Telegram-bericht: {e}")
        return False


# ---------------------------------------------------------------------------
# Rapportage-functies -- formatteren + versturen van gestructureerde updates
# ---------------------------------------------------------------------------

def report_trade(direction: str, engine: str, network: str, amount_in: float,
                  estimated_out: float, status: str, tx_hash: Optional[str] = None) -> bool:
    emoji = "\u2705" if status == "success" else "\u274c"
    lines = [
        f"{emoji} *HBAR Bot -- Trade {status.upper()}*",
        f"Richting: `{direction}`",
        f"Engine: {engine.upper()} ({network})",
        f"Ingezet: {amount_in:.4f}",
        f"Verwacht ontvangen: {estimated_out:.4f}",
    ]
    if tx_hash:
        lines.append(f"Tx: `{tx_hash}`")
    return send_telegram_message("\n".join(lines))


def report_panic_override(reasoning: str, btc_score: float, hbar_score: float) -> bool:
    message = (
        f"\u26a0\ufe0f *PANIEK-OVERRIDE GETRIGGERD*\n"
        f"BTC-score: {btc_score:.2f} | HBAR-score: {hbar_score:.2f}\n"
        f"{reasoning}"
    )
    return send_telegram_message(message)


def report_lp_rebalance(action: str, price: float, tick_lower: int, tick_upper: int) -> bool:
    message = (
        f"\U0001f504 *HBAR Bot -- LP {action}*\n"
        f"Prijs: {price:.4f} USDC/HBAR\n"
        f"Range: tick {tick_lower} -- {tick_upper}"
    )
    return send_telegram_message(message)


def report_error(context: str, error: str) -> bool:
    message = f"\U0001f6a8 *HBAR Bot -- FOUT*\nContext: {context}\n```\n{error}\n```"
    return send_telegram_message(message)


@dataclass
class DailySummaryData:
    date: str
    total_trades: int
    successful_trades: int
    failed_trades: int
    avg_btc_sentiment: float
    avg_hbar_sentiment: float
    panic_overrides_triggered: int
    net_hbar_change: float
    net_usdc_change: float


def format_daily_summary(data: DailySummaryData) -> str:
    """
    Formatteert een DailySummaryData naar een leesbaar Telegram-bericht.
    De data zelf komt straks uit postgres_client.py (nog te bouwen) --
    deze functie is daar bewust onafhankelijk van, zodat ze ook los
    getest kan worden.
    """
    win_rate = (
        data.successful_trades / data.total_trades * 100
        if data.total_trades > 0 else 0.0
    )

    lines = [
        f"\U0001f4ca *HBAR Bot -- Dagrapport {data.date}*",
        "",
        f"Trades: {data.total_trades} ({data.successful_trades} succesvol, {data.failed_trades} mislukt)",
        f"Slagingspercentage: {win_rate:.0f}%",
        "",
        f"Gem. BTC-sentiment: {data.avg_btc_sentiment:+.2f}",
        f"Gem. HBAR-sentiment: {data.avg_hbar_sentiment:+.2f}",
        f"Paniek-overrides: {data.panic_overrides_triggered}",
        "",
        f"Netto HBAR: {data.net_hbar_change:+.2f}",
        f"Netto USDC: {data.net_usdc_change:+.2f}",
    ]
    return "\n".join(lines)


def send_daily_summary(data: DailySummaryData) -> bool:
    return send_telegram_message(format_daily_summary(data))


if __name__ == "__main__":
    # Formattering testen zonder live Telegram-call (env vars ontbreken
    # in deze sandbox, dus send_telegram_message geeft netjes False terug)
    example = DailySummaryData(
        date=datetime.now().strftime("%Y-%m-%d"),
        total_trades=5,
        successful_trades=4,
        failed_trades=1,
        avg_btc_sentiment=0.12,
        avg_hbar_sentiment=0.45,
        panic_overrides_triggered=0,
        net_hbar_change=120.5,
        net_usdc_change=-8.3,
    )

    print("--- Voorbeeld dagrapport ---")
    print(format_daily_summary(example))

    print("\n--- Test send (verwacht: False, geen env vars in sandbox) ---")
    result = send_telegram_message("Testbericht")
    print(f"Verstuurd: {result}")
