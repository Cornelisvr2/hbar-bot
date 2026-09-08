#!/usr/bin/env python3
"""
pool_scan.py -- (8 sep 2026) Vergelijking van SaucerSwap-V2-pools:
TVL en 24u-volume (GeckoTerminal), fee-tier (SaucerSwap-API), LARI-
allocatie epoch 74 (docs), -> Fees-APR (pool-breed), LARI-APR, totaal,
plus een risicoklasse. Puur informatief (verbeterplan punt 6, fase 1).

Gebruik: python3 pool_scan.py [--min-tvl 100000]
"""
import argparse
import requests

GT = "https://api.geckoterminal.com/api/v2"
SS = "https://api.saucerswap.finance"

# Epoch 74 (7-21 sep 2026), docs.saucerswap.finance/protocol/saucerswap-v2/lari-weights
LARI_SAUCE = {
    "USDC-HBAR": 186067.23, "SAUCE-HBAR": 152863.32, "SAUCE-XSAUCE": 21658.82, "HBAR-HBARX": 35799.55,
    "XSAUCE-HBAR": 11814.00, "USDC-SAUCE": 17541.89, "DOVU-HBAR": 82696.66, "KARATE-HBAR": 17183.90,
    "JAM-HBAR": 23717.28, "CARAT-USDC": 5370.12, "USDC-WETH": 21032.33, "HBAR-WETH": 70882.88,
    "HBAR-WBTC": 57189.64, "USDC-WBTC": 30966.64, "HBAR-HST": 5907.11, "HBAR-BONZO": 16825.91,
    "HBAR-PACK": 20853.33, "HBAR-GRELF": 11814.00, "HBAR-CLXY": 7965.58, "HBAR-HLQT": 6444.10,
    "USDC-HCHF": 6354.61, "USDC-USDC.AXL": 15751.93, "HBAR-USDT0": 12529.99, "USDC-USDT0": 11008.52,
    "HBAR-LINK.AXL": 13335.47, "HBAR-QNT.AXL": 16557.41, "HBAR-WAVAX.AXL": 7786.58, "HBAR-WBNB.AXL": 7064.20,
}
LARI_HBAR = {"USDC-HBAR": 9541.75, "SAUCE-HBAR": 9541.75}
EPOCHS_PER_YEAR = 26.07145
STABLES = {"USDC", "USDT0", "USDC.AXL", "USDT", "HCHF", "CARAT"}
MAJORS = {"WETH", "WBTC", "HBAR", "WHBAR"}


def norm(sym: str) -> str:
    return sym.upper().replace("WHBAR", "HBAR")


def pair_key(a: str, b: str):
    a, b = norm(a), norm(b)
    for k in LARI_SAUCE:
        x, y = k.split("-")
        if {x, y} == {a, b}:
            return k
    return None


def risk_class(a: str, b: str) -> str:
    a, b = norm(a), norm(b)
    if a in STABLES and b in STABLES:
        return "stable/stable (laag IL)"
    if {a, b} <= MAJORS | STABLES:
        return "major (middel IL)"
    if "HBAR" in (a, b) and (a in STABLES or b in STABLES):
        return "stable/HBAR (middel IL)"
    return "alt-token (hoog IL, dunne markt)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-tvl", type=float, default=100_000)
    args = ap.parse_args()

    sauce_px = float(requests.get(f"{GT}/simple/networks/hedera-hashgraph/token_price/0x00000000000000000000000000000000000b2ad5", timeout=15)
                     .json()["data"]["attributes"]["token_prices"].popitem()[1])
    hbar_px = float(requests.get(f"{GT}/simple/networks/hedera-hashgraph/token_price/0x0000000000000000000000000000000000163b5a", timeout=15)
                    .json()["data"]["attributes"]["token_prices"].popitem()[1])

    fee_by_contract = {}
    for p in requests.get(f"{SS}/v2/pools", timeout=20).json():
        fee_by_contract[p["contractId"]] = (p["fee"], p["tokenA"]["symbol"], p["tokenB"]["symbol"])

    pools = []
    for page in range(1, 6):
        r = requests.get(f"{GT}/networks/hedera-hashgraph/dexes/saucerswap-v2/pools", params={"page": page}, timeout=20)
        if r.status_code != 200:
            break
        data = r.json().get("data", [])
        if not data:
            break
        pools.extend(data)

    rows = []
    for p in pools:
        a = p["attributes"]
        tvl = float(a.get("reserve_in_usd") or 0)
        if tvl < args.min_tvl:
            continue
        vol = float((a.get("volume_usd") or {}).get("h24") or 0)
        name = a.get("name", "")
        syms = [s.strip().split(" ")[0] for s in name.replace("/", " / ").split(" / ")][:2]
        if len(syms) < 2:
            continue
        # fee-tier via SaucerSwap-lijst: match op symbolen
        fee = None
        for cid, (f, ta, tb) in fee_by_contract.items():
            if {norm(ta), norm(tb)} == {norm(syms[0]), norm(syms[1])}:
                # meerdere fee-tiers per paar mogelijk: neem de tier waarvan de naam matcht als GeckoTerminal die geeft
                if fee is None or (str(f / 10000) + "%" in name):
                    fee = f
        fee_frac = (fee or 3000) / 1_000_000
        fees_apr = vol * fee_frac * (5 / 6) / tvl * 365 if tvl else 0.0
        key = pair_key(syms[0], syms[1])
        lari_usd = (LARI_SAUCE.get(key, 0) * sauce_px + LARI_HBAR.get(key, 0) * hbar_px) if key else 0.0
        lari_apr = lari_usd * EPOCHS_PER_YEAR / tvl if tvl else 0.0
        rows.append({
            "pool": name, "fee": fee, "tvl": tvl, "vol": vol, "vol_tvl": vol / tvl if tvl else 0,
            "fees_apr": fees_apr, "lari_apr": lari_apr, "total": fees_apr + lari_apr,
            "risk": risk_class(syms[0], syms[1]), "lari_epoch_usd": lari_usd,
        })

    rows.sort(key=lambda r: -r["total"])
    print(f"SAUCE ${sauce_px:.4f}  HBAR ${hbar_px:.4f}  |  {len(rows)} pools met TVL >= ${args.min_tvl:,.0f}\n")
    print(f"{'pool':34s} {'fee':>6s} {'TVL':>10s} {'vol24u':>10s} {'vol/TVL':>7s} {'fees':>6s} {'LARI':>6s} {'totaal':>7s}  risico")
    for r in rows:
        fee_s = f"{r['fee']/10000:.2f}%" if r["fee"] else "?"
        print(f"{r['pool'][:34]:34s} {fee_s:>6s} {r['tvl']/1e3:>9.0f}k {r['vol']/1e3:>9.0f}k {r['vol_tvl']:>7.2f} "
              f"{r['fees_apr']*100:>5.1f}% {r['lari_apr']*100:>5.1f}% {r['total']*100:>6.1f}%  {r['risk']}")
    print("\nFees-APR = 24u-volume x fee x 5/6 / TVL x 365 (pool-breed; een smalle range verdient een veelvoud).")
    print("LARI-APR = epoch-allocatie (SAUCE+HBAR, epoch 74) x prijs x 26,07 / TVL. Alt-token-pools: hoog IL-risico en vaak eenzijdige kopers.")


if __name__ == "__main__":
    main()
