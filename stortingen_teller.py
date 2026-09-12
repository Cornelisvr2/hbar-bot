"""
stortingen_teller.py -- echt rendement: wat stopte ik erin vs wat is het waard.

Detecteert stortingen als inkomende HBAR van MoonPay (account 0.0.7302893)
via de Mirror Node -- waterdicht, want al het andere inkomende verkeer is
bot-activiteit (swaps, fees, rewards). Per storting wordt de HBAR-koers op
die dag opgezocht in candles_5m voor de USDC-waarde-bij-storting.

Rendement op twee manieren:
  - MUNTJES: huidige HBAR-stapel vs totaal ingelegde HBAR (het doel).
  - USDC: huidige walletwaarde vs som van (storting-HBAR x koers-toen).
    Dit toont het echte euro/dollar-resultaat inclusief koersbeweging.

    docker compose run --rm -T hbar-bot python3 stortingen_teller.py
    docker compose run --rm -T hbar-bot python3 stortingen_teller.py --json
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "hbar-bot-stortingen/1.0"}
MOONPAY = "0.0.7302893"


def account_id(mirror):
    from eth_account import Account
    pk = (os.environ.get("HEDERA_LP_PRIVATE_KEY") or os.environ.get("HEDERA_BOT_PRIVATE_KEY") or "").removeprefix("0x")
    evm = Account.from_key("0x" + pk).address
    return requests.get(f"{mirror}/api/v1/accounts/{evm}?limit=1", headers=UA, timeout=15).json().get("account")


async def main():
    json_uit = "--json" in sys.argv
    from config import NETWORK_SETTINGS
    from postgres_client import PostgresClient
    net = os.environ.get("HEDERA_NETWORK", "mainnet")
    mirror = NETWORK_SETTINGS[net]["mirror_node_url"]
    acc = account_id(mirror)

    # 1) stortingen van MoonPay ophalen
    stortingen = []
    gezien = set()
    url = f"{mirror}/api/v1/transactions?account.id={acc}&limit=100&order=asc&transactiontype=CRYPTOTRANSFER"
    pag = 0
    while url and pag < 50:
        d = requests.get(url, headers=UA, timeout=20).json()
        for t in d.get("transactions", []):
            tid = t.get("transaction_id")
            if tid in gezien or t.get("result") != "SUCCESS":
                continue
            gezien.add(tid)
            van_moonpay = any(tr.get("account") == MOONPAY and tr["amount"] < 0 for tr in t.get("transfers", []))
            if not van_moonpay:
                continue
            ontvangen = sum(tr["amount"] for tr in t.get("transfers", []) if tr.get("account") == acc and tr["amount"] > 0)
            if ontvangen > 0:
                ts = float(t["consensus_timestamp"])
                stortingen.append((datetime.fromtimestamp(ts, tz=timezone.utc), ontvangen / 1e8))
        nxt = (d.get("links") or {}).get("next")
        url = f"{mirror}{nxt}" if nxt else None
        pag += 1

    # 2) koers op elke stortingsdag uit candles_5m
    db = PostgresClient()
    await db.connect()
    totaal_hbar = 0.0
    totaal_usdc_toen = 0.0
    regels = []
    async with db._pool.acquire() as conn:
        for dt, hbar in stortingen:
            row = await conn.fetchrow(
                "SELECT close FROM candles_5m WHERE symbol='HBAR' AND ts <= $1 ORDER BY ts DESC LIMIT 1", dt)
            koers = row["close"] if row else None
            usdc = hbar * koers if koers else 0.0
            totaal_hbar += hbar
            totaal_usdc_toen += usdc
            regels.append((dt.date().isoformat(), round(hbar, 1), round(koers, 5) if koers else None, round(usdc, 0)))
        # huidige koers
        nu_row = await conn.fetchrow("SELECT close FROM candles_5m WHERE symbol='HBAR' ORDER BY ts DESC LIMIT 1")
    nu_koers = nu_row["close"] if nu_row else 0.0

    # huidige walletwaarde in USDC ophalen van de chain (HBAR-saldo + USDC-token + LP schat via bot? -> hier alleen wallet)
    acc_data = requests.get(f"{mirror}/api/v1/accounts/{acc}", headers=UA, timeout=15).json()
    hbar_saldo = acc_data.get("balance", {}).get("balance", 0) / 1e8
    # NB: LP-positie-waarde zit NIET in het wallet-saldo; die komt uit de bot.
    # Voor een compleet beeld toont het dashboard walletwaarde + LP-waarde.

    resultaat = {
        "aantal_stortingen": len(stortingen),
        "totaal_ingelegd_hbar": round(totaal_hbar, 1),
        "totaal_ingelegd_usdc_bij_storting": round(totaal_usdc_toen, 0),
        "huidige_hbar_koers": round(nu_koers, 5),
        "wallet_hbar_saldo": round(hbar_saldo, 1),
        "stortingen": regels,
    }
    if json_uit:
        print(json.dumps(resultaat)); return
    print(f"\nStortingen (van MoonPay) op account {acc}")
    for datum, hbar, koers, usdc in regels:
        print(f"  {datum}: {hbar:>8.1f} HBAR  @ ${koers}  = ${usdc:.0f}")
    print(f"\n  Totaal ingelegd: {totaal_hbar:.1f} HBAR  (= ${totaal_usdc_toen:.0f} op de stortingsmomenten)")
    print(f"  HBAR-koers nu:   ${nu_koers:.5f}")
    print(f"  Ingelegde HBAR nu waard: ${totaal_hbar*nu_koers:.0f}")
    verschil = (nu_koers * totaal_hbar) - totaal_usdc_toen
    print(f"  Koerseffect op inleg: {verschil:+.0f} USDC")
    print("\nNB: dit is de INLEG-kant. Het echte totaalrendement = huidige")
    print("walletwaarde + LP-positiewaarde - totaal ingelegd. De LP-waarde komt")
    print("uit de bot (report), het dashboard combineert beide.")


if __name__ == "__main__":
    asyncio.run(main())
