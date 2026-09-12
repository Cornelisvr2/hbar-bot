"""
kosten_teller.py -- totale kosten van de bot, rechtstreeks van de chain.

Leest alle transacties van het bot-account uit de Hedera Mirror Node
(zelfde bron als HashScan) en telt de betaalde netwerk-fee (charged_tx_fee)
op. Ontdubbelt op transaction_id, want de paginering kan overlappen.

    docker compose run --rm -T hbar-bot python3 kosten_teller.py
    docker compose run --rm -T hbar-bot python3 kosten_teller.py --account 0.0.10819646 --json
"""
import json
import os
import sys

import requests

UA = {"User-Agent": "hbar-bot-kosten/1.0"}


def account_id(mirror):
    if "--account" in sys.argv:
        return sys.argv[sys.argv.index("--account") + 1]
    from eth_account import Account
    pk = (os.environ.get("HEDERA_LP_PRIVATE_KEY") or os.environ.get("HEDERA_BOT_PRIVATE_KEY") or "").removeprefix("0x")
    evm = Account.from_key("0x" + pk).address
    r = requests.get(f"{mirror}/api/v1/accounts/{evm}?limit=1", headers=UA, timeout=15)
    return r.json().get("account")


def main():
    json_uit = "--json" in sys.argv
    from config import NETWORK_SETTINGS
    mirror = NETWORK_SETTINGS[os.environ.get("HEDERA_NETWORK", "mainnet")]["mirror_node_url"]
    acc = account_id(mirror)
    if not acc:
        print("Kon account-ID niet bepalen."); return

    totaal = 0
    per_type = {}
    n = 0
    gezien = set()
    url = f"{mirror}/api/v1/transactions?account.id={acc}&limit=100&order=asc"
    pagina = 0
    while url and pagina < 100:
        r = requests.get(url, headers=UA, timeout=20)
        if r.status_code != 200:
            break
        d = r.json()
        for tx in d.get("transactions", []):
            tid = tx.get("transaction_id")
            if tx.get("result") != "SUCCESS" or tid in gezien:
                continue
            gezien.add(tid)
            fee = tx.get("charged_tx_fee") or 0
            if fee <= 0:
                continue
            totaal += fee
            t = tx.get("name", "onbekend")
            per_type[t] = per_type.get(t, 0) + fee
            n += 1
        nxt = (d.get("links") or {}).get("next")
        url = f"{mirror}{nxt}" if nxt else None
        pagina += 1

    hbar = totaal / 1e8
    resultaat = {
        "account": acc,
        "aantal_tx": n,
        "gas_hbar": round(hbar, 2),
        "per_type_hbar": {k: round(v / 1e8, 2) for k, v in sorted(per_type.items(), key=lambda x: -x[1])},
    }
    if json_uit:
        print(json.dumps(resultaat))
    else:
        print(f"\nKosten van account {acc} (rechtstreeks van de chain)")
        print(f"  Transacties:        {n}")
        print(f"  Totaal gas betaald: {hbar:.2f} HBAR")
        for k, v in resultaat["per_type_hbar"].items():
            print(f"    {k:24s} {v:.2f} HBAR")
        print("\nNB: dit is de netwerk-fee (gas). De pool-swap-fee (0,3% per swap) zit")
        print("verrekend in de swap-bedragen zelf en wordt apart geschat.")


if __name__ == "__main__":
    main()
