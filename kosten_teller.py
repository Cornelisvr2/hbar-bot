"""
kosten_teller.py -- totale kosten van de bot, RECHTSTREEKS van de chain.

Leest ALLE transacties van het bot-account uit de Hedera Mirror Node
(dezelfde bron als HashScan) en telt de werkelijk betaalde fees op. Geen
afhankelijkheid van de trades-tabel (die logt actual_amount_out niet).

  - charged_tx_fee per transactie (tinybar -> HBAR): het EXACTE netwerk/gas-
    bedrag dat het account heeft betaald, voor elke tx die het account als
    payer had.
Telt ook hoeveel transacties er waren en splitst naar type (crypto/contract).

Het account-ID wordt afgeleid uit de sleutel (publiek adres -> Mirror Node),
of via --account 0.0.xxxxx.

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

    totaal_fee_tinybar = 0
    per_type = {}
    n = 0
    url = f"{mirror}/api/v1/transactions?account.id={acc}&limit=100&order=asc"
    pagina = 0
    while url and pagina < 200:   # ruime bovengrens
        r = requests.get(url, headers=UA, timeout=20)
        if r.status_code != 200:
            break
        d = r.json()
        for tx in d.get("transactions", []):
            # alleen tx's waar DIT account de fee betaalde (payer)
            if tx.get("charged_tx_fee") and tx.get("transaction_id", "").startswith(acc):
                fee = tx["charged_tx_fee"]
                totaal_fee_tinybar += fee
                t = tx.get("name", "onbekend")
                per_type[t] = per_type.get(t, 0) + fee
                n += 1
        nxt = (d.get("links") or {}).get("next")
        url = f"{mirror}{nxt}" if nxt else None
        pagina += 1

    totaal_hbar = totaal_fee_tinybar / 1e8
    resultaat = {
        "account": acc,
        "aantal_betaalde_tx": n,
        "totaal_gas_hbar": round(totaal_hbar, 4),
        "per_type_hbar": {k: round(v / 1e8, 4) for k, v in sorted(per_type.items(), key=lambda x: -x[1])},
    }
    if json_uit:
        print(json.dumps(resultaat))
    else:
        print(f"\nKosten van account {acc} (rechtstreeks van de chain)")
        print(f"  Transacties met fee: {n}")
        print(f"  Totaal gas/netwerk:  {totaal_hbar:.4f} HBAR")
        print(f"  Per type:")
        for k, v in resultaat["per_type_hbar"].items():
            print(f"    {k:28s} {v:.4f} HBAR")
        print("\nNB: dit is de NETWERK-fee (gas), exact van de chain. De pool-swap-fee")
        print("(0,3% per swap) zit verrekend in de swap-bedragen zelf, niet als aparte")
        print("chain-fee -- die schatten we apart uit het aantal swaps x 0,3%.")


if __name__ == "__main__":
    main()
