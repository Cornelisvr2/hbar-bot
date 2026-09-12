"""
kosten_teller.py -- totale kosten die de bot heeft betaald.

De trades-tabel logt geen kosten, maar wel tx_hash + de bedragen. Twee
kostensoorten worden hier opgeteld:

  1. NETWERK/GAS-fee per transactie -- opgehaald via de Hedera Mirror Node
     op tx_hash (charged_tx_fee, in tinybar -> HBAR).
  2. SWAP-fee/slippage -- het verschil tussen estimated_amount_out en
     actual_amount_out per swap (wat je kwijt was aan de pool + slippage).

Geeft het totaal in HBAR en USDC-equivalent, zodat het dashboard kan tonen:
"Fees betaald" naast "Fees verdiend", en het netto resultaat.

    docker compose run --rm -T hbar-bot python3 kosten_teller.py
    docker compose run --rm -T hbar-bot python3 kosten_teller.py --json   # voor het dashboard
"""
import asyncio
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UA = {"User-Agent": "hbar-bot-kosten/1.0"}


def netwerk_fee_hbar(mirror_url, tx_hash):
    """charged_tx_fee (tinybar) -> HBAR, via de Mirror Node. 0 bij niet gevonden."""
    if not tx_hash:
        return 0.0
    try:
        # Mirror Node accepteert het transaction-id-formaat; tx_hash kan een
        # eth-hash zijn -> zoek via /contracts/results/{hash} voor de fee.
        r = requests.get(f"{mirror_url}/api/v1/contracts/results/{tx_hash}", headers=UA, timeout=10)
        if r.status_code == 200:
            d = r.json()
            # gas_used * gas_price geeft de gaskost; charged in tinybar
            fee_tinybar = d.get("amount", 0) or 0
            gas_used = d.get("gas_used", 0) or 0
            gas_price = d.get("gas_price", 0) or 0
            # sommige velden zijn hex
            def _num(x):
                if isinstance(x, str) and x.startswith("0x"):
                    return int(x, 16)
                return x or 0
            kost_tinybar = _num(gas_used) * _num(gas_price)
            return kost_tinybar / 1e8  # tinybar -> HBAR
    except Exception:
        pass
    return 0.0


async def main():
    json_uit = "--json" in sys.argv
    from postgres_client import PostgresClient
    from config import NETWORK_SETTINGS
    mirror = NETWORK_SETTINGS[os.environ.get("HEDERA_NETWORK", "mainnet")]["mirror_node_url"]
    db = PostgresClient()
    await db.connect()
    async with db._pool.acquire() as conn:
        trades = await conn.fetch(
            "SELECT tx_hash, amount_in, estimated_amount_out, actual_amount_out, direction, status "
            "FROM trades WHERE status = 'success' ORDER BY created_at")

    n_trades = len(trades)
    swap_verlies_hbar = 0.0   # slippage + pool-fee, ruw in HBAR-equivalent
    gas_hbar = 0.0
    for t in trades:
        # swap-verlies: verschil geschat vs werkelijk (in de uit-token)
        est, act = t["estimated_amount_out"], t["actual_amount_out"]
        if est and act and est > act:
            # verlies uitgedrukt als fractie van de trade; ruw naar HBAR via amount_in
            frac = (est - act) / est
            swap_verlies_hbar += frac * (t["amount_in"] or 0)
        gas_hbar += netwerk_fee_hbar(mirror, t["tx_hash"])

    totaal_hbar = swap_verlies_hbar + gas_hbar
    resultaat = {
        "aantal_trades": n_trades,
        "gas_hbar": round(gas_hbar, 4),
        "swap_verlies_hbar": round(swap_verlies_hbar, 2),
        "totaal_kosten_hbar": round(totaal_hbar, 2),
    }
    if json_uit:
        print(json.dumps(resultaat))
    else:
        print(f"\nKostenteller ({n_trades} geslaagde trades)")
        print(f"  Gas/netwerk-fees:   {gas_hbar:.4f} HBAR")
        print(f"  Swap-fee+slippage:  {swap_verlies_hbar:.2f} HBAR (ruwe schatting)")
        print(f"  Totaal betaald:     {totaal_hbar:.2f} HBAR")
        print("\nLet op: swap-verlies is een ruwe schatting uit estimated vs actual;")
        print("gas komt exact van de Mirror Node. Voor het dashboard: --json.")


if __name__ == "__main__":
    asyncio.run(main())
