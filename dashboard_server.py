# dashboard_server.py
#
# Live webdashboard (1 sep 2026, op verzoek) -- toont de actuele
# strategie, positie/range-gezondheid, opgebouwde fees, en
# waarde-historie (dag/week/maand/jaar) van de bot. Draait als eigen
# service naast de bot en de database (zie docker-compose.yml).
#
# BEWUST GEEN LOGIN (op uitdrukkelijk verzoek, "hoeft geen login te
# hebben nu nog") -- zie PLAN.md voor de kanttekening hierover als dit
# ooit publiek/internet-toegankelijk wordt in plaats van lokaal/via een
# SSH-tunnel.

import datetime
import time
import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader

from bot_data import fetch_dashboard_data, STRATEGIE_NAMEN, HEDERA_NETWORK, get_total_deposits_hbar
from lp_manager import compute_fees_apr
from postgres_client import PostgresClient

app = FastAPI()
jinja_env = Environment(loader=FileSystemLoader("templates"))

RANGE_STATUS_LABELS = {
    "buiten_bereik": "Buiten bereik -- verdient geen fees",
    "dicht_bij_rand": "Dicht bij de rand -- kwetsbaar",
    "gezond": "Gezond gecentreerd",
}

# Ruwe, indicatieve USD->EUR-omrekening (1 sep 2026) -- GeckoTerminal (onze
# enige huidige prijsbron) geeft alleen USD terug. Voor een ECHTE EUR-koers
# is later een aparte bron nodig (bv. een simpele wisselkoers-API) -- dit
# is bewust een vaste, benaderende factor, geen live koers.
USD_NAAR_EUR = 0.923


async def _build_dashboard_context() -> dict:
    """Verzamelt alle data die het dashboard-sjabloon nodig heeft."""
    db = PostgresClient()
    await db.connect()
    try:
        data = await fetch_dashboard_data(db)

        # Live pool-APR (hergebruikt dezelfde, al-bestaande formule als
        # regime_orchestrator.py's periodieke logregel).
        from geckoterminal_client import GeckoTerminalClient
        gecko = GeckoTerminalClient()
        snapshot = gecko.get_pool_snapshot()
        fee_tier = int(os.environ.get("LP_FEE_TIER", "3000"))  # BUGFIX (5 sep 2026, systematische audit): was hardgecodeerd op 3000, ongeacht de daadwerkelijke pool-fee-tier (1500 op mainnet)
        pool_apr = compute_fees_apr(snapshot.volume_24h_usd, fee_tier, snapshot.liquidity_usd)

        # Projecties (1 sep 2026, op verzoek) -- dagelijks samengestelde
        # rente op basis van de HUIDIGE pool-APR, zoals besproken: NIET
        # een enkele, volatiele dag extrapoleren (zou een onrealistisch
        # getal geven), maar de stabielere, jaarlijkse APR-maatstaf.
        totaal = data["total_value_usd"]
        projectie_30d = totaal * (1 + pool_apr / 365) ** 30
        projectie_90d = totaal * (1 + pool_apr / 365) ** 90
        projectie_180d = totaal * (1 + pool_apr / 365) ** 180

        # Waardeverandering 24u (hergebruikt dezelfde aanpak als het
        # Telegram-rapport).
        vorige_24u = await db.get_portfolio_value_at(1)
        change_24h_pct = None
        if vorige_24u and vorige_24u["total_value_usd"] > 0:
            nu = datetime.datetime.now(datetime.timezone.utc)
            afstand_dagen = abs((nu - vorige_24u["recorded_at"]).total_seconds()) / 86400
            if afstand_dagen <= 1.5:  # zelfde tolerantie-principe als het Telegram-rapport
                change_24h_pct = (totaal - vorige_24u["total_value_usd"]) / vorige_24u["total_value_usd"] * 100

        # Transactiegeschiedenis (laatste 30, uit de trades-tabel).
        trades = await db.get_recent_trades(limit=30)
        transacties = []
        totale_kosten_30d = 0.0
        totale_inkomsten_30d = 0.0
        dertig_dagen_geleden = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)

        # RPC-client EENMALIG aanmaken, buiten de lus hieronder (1 sep
        # 2026) -- werd voorheen per transactie opnieuw aangemaakt,
        # onnodig traag bij 30 transacties.
        from config import NETWORK_SETTINGS
        from hedera_rpc_client import HederaRpcClient, NetworkConfig
        _settings = NETWORK_SETTINGS[HEDERA_NETWORK]
        _network = NetworkConfig(rpc_url=_settings["rpc_url"], chain_id=_settings["chain_id"])
        _rpc = HederaRpcClient(_network, os.environ.get("HEDERA_BOT_PRIVATE_KEY"))

        for t in trades:
            is_binnen_30d = t["created_at"] >= dertig_dagen_geleden
            # BUGFIX (4 sep 2026, gevonden tijdens de mainnet-migratie):
            # dit toonde altijd "SAUCE", ongeacht het netwerk -- op
            # mainnet is dit USDC.
            _tokennaam = "SAUCE" if os.environ.get("HEDERA_NETWORK", "testnet") == "testnet" else "USDC"
            richting_label = f"Swap HBAR → {_tokennaam}" if t["direction"] == "HBAR_TO_USDC" else f"Swap {_tokennaam} → HBAR"
            eenheid = "HBAR" if t["direction"] == "HBAR_TO_USDC" else _tokennaam
            bedrag = t["amount_in"]

            # BUGFIX (1 sep 2026, gevonden na visuele controle): het
            # VOLLEDIGE, ingezette swap-bedrag (bv. 45.477 SAUCE) werd
            # voorheen ten onrechte als "kosten" getoond (rood, met een
            # minteken) -- een swap is GEEN verlies, alleen een
            # omzetting van het ene token naar het andere (de waarde
            # blijft, alleen in een andere vorm). De ECHTE kosten van
            # een swap zijn uitsluitend de gasfee -- die vragen we hier
            # daarom apart op (via de daadwerkelijke transactie-
            # ontvangstbevestiging), en TONEN we als de kostenpost,
            # i.p.v. het volledige, misleidende swap-bedrag.
            gas_kosten_hbar = 0.0
            if t["tx_hash"]:
                try:
                    receipt = _rpc.w3.eth.get_transaction_receipt(t["tx_hash"])
                    # Gebruikt effectiveGasPrice UIT de ontvangstbevestiging
                    # zelf (standaard EVM-veld sinds EIP-1559) i.p.v. een
                    # aparte get_transaction()-aanroep -- halveert het
                    # aantal RPC-aanroepen (30 transacties x 1 i.p.v. x 2).
                    gas_kosten_wei = receipt["gasUsed"] * receipt["effectiveGasPrice"]
                    gas_kosten_hbar = gas_kosten_wei / (10 ** 18)
                except Exception:
                    pass  # defensief -- een mislukte opzoeking mag de rest van de lijst niet blokkeren

            transacties.append({
                "date_label": t["created_at"].strftime("%-d %b"),
                "description": f"{richting_label} ({bedrag:,.2f} {eenheid})",
                "tag": t["engine"],
                "amount": gas_kosten_hbar,
                "is_cost": True,  # de gasfee zelf is wel degelijk een echte kostenpost
            })
            if is_binnen_30d:
                totale_kosten_30d += gas_kosten_hbar

        db_positie = data["position"]
        if db_positie and (db_positie["fee_hbar"] > 0.0001):
            totale_inkomsten_30d += db_positie["fee_hbar"]  # huidige, nog niet geclaimde fees als indicatie

        # Totaaloverzicht sinds start (1 sep 2026, op verzoek) -- totale
        # stortingen via de mirror node (zie get_total_deposits_hbar()
        # voor de volledige toelichting/aannames), en het netto-resultaat
        # (huidige totale waarde min de dollarwaarde van alle stortingen
        # -- gekozen als eenvoudigste, meest betrouwbare maatstaf, i.p.v.
        # te proberen fees en principaal met terugwerkende kracht per
        # gesloten positie uit elkaar te trekken, wat onbetrouwbaar bleek).
        try:
            totale_stortingen_hbar = get_total_deposits_hbar(data["wallet_address"])
        except Exception as e:
            print(f"[waarschuwing] Kon totale stortingen niet ophalen: {e}")
            totale_stortingen_hbar = None

        netto_resultaat_usd = None
        if totale_stortingen_hbar is not None:
            totale_stortingen_usd = totale_stortingen_hbar * data["hbar_price_usd"]
            netto_resultaat_usd = data["total_value_usd"] - totale_stortingen_usd

        return {
            **data,
            "current_regime_label": STRATEGIE_NAMEN.get(data["current_regime"], data["current_regime"]),
            "range_status_label": RANGE_STATUS_LABELS.get(
                data["position"]["range_status"], ""
            ) if data["position"] else "",
            "hbar_price_eur": data["hbar_price_usd"] * USD_NAAR_EUR,
            "pool_apr_pct": pool_apr * 100,
            "projection_30d": projectie_30d,
            "projection_90d": projectie_90d,
            "projection_180d": projectie_180d,
            "change_24h_pct": change_24h_pct,
            "transactions": transacties,
            "total_costs_30d": totale_kosten_30d,
            "total_income_30d": totale_inkomsten_30d,
            "total_deposits_hbar": totale_stortingen_hbar,
            "net_result_usd": netto_resultaat_usd,
            "chart_data_24h": await _build_chart_data(db, days=1),
            "price_chart_data_24h": _build_price_chart_data(days=1),
            "network": os.environ.get("HEDERA_NETWORK", "testnet"),
            "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%-d %b %Y, %H:%M UTC"),
        }
    finally:
        await db.close()


async def _build_chart_data(db: PostgresClient, days: int) -> dict:
    """Haalt de waarde-historie op voor de grafiek, over de gevraagde periode."""
    rijen = await db.get_portfolio_value_history_since(days)
    if not rijen:
        return {"labels": [], "values": []}
    formaat = "%H:%M" if days <= 1 else ("%-d %b" if days <= 30 else "%-d %b %y")
    return {
        "labels": [r["recorded_at"].strftime(formaat) for r in rijen],
        "values": [r["total_value_usd"] for r in rijen],
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    context = await _build_dashboard_context()
    template = jinja_env.get_template("dashboard.html")
    return template.render(d=context)


@app.get("/api/history")
async def api_history(days: int = 1):
    db = PostgresClient()
    await db.connect()
    try:
        return JSONResponse(await _build_chart_data(db, days))
    finally:
        await db.close()


# Korte cache voor de prijs-historie per periode (1 sep 2026, na een
# gevonden 429-snelheidslimiet-fout bij GeckoTerminal) -- deze functie
# kan meerdere keren per minuut aangeroepen worden (elke pagina-
# herlading, elke toggle-klik van elke bezoeker), en GeckoTerminal's
# publieke API staat maar een beperkt aantal aanvragen per minuut toe.
# 60 seconden geldigheid per periode is ruim voldoende -- de koers
# verandert niet zo snel dat een minuut oud een probleem is.
_prijs_cache: dict = {}
_PRIJS_CACHE_TTL_SECONDEN = 60


def _build_price_chart_data(days: int) -> dict:
    """
    Haalt de HBAR-prijs-historie op voor de gevraagde periode (1 sep
    2026, op verzoek) -- via GeckoTerminal's EIGEN, al-bestaande
    OHLCV-geschiedenis (get_historical_ohlcv()), NIET via onze eigen
    opslag. Dit geeft echte, langere historie (ook van vóór we zelf
    begonnen met snapshots opslaan), zonder dat we het zelf hoeven bij
    te houden.

    Kiest een passend tijdsinterval per candle, afhankelijk van de
    gevraagde periode -- anders zou een jaar aan uur-candles (8760
    stuks) de grafiek onleesbaar maken.
    """
    nu = time.time()
    gecached = _prijs_cache.get(days)
    if gecached and (nu - gecached[0]) < _PRIJS_CACHE_TTL_SECONDEN:
        return gecached[1]

    from geckoterminal_client import GeckoTerminalClient
    gecko = GeckoTerminalClient()

    if days <= 1:
        timeframe, aggregate, formaat = "minute", 15, "%H:%M"
    elif days <= 7:
        timeframe, aggregate, formaat = "hour", 1, "%-d %b %H:%M"
    elif days <= 30:
        timeframe, aggregate, formaat = "hour", 4, "%-d %b"
    else:
        timeframe, aggregate, formaat = "day", 1, "%-d %b %y"

    try:
        candles = gecko.get_historical_ohlcv(timeframe=timeframe, aggregate=aggregate, limit=200)
    except Exception as e:
        print(f"[waarschuwing] Kon HBAR-prijs-historie niet ophalen: {e}")
        # Bij een storing: de LAATST BEKENDE, gecachete data teruggeven
        # (ook al is die net verlopen) i.p.v. een lege grafiek -- beter
        # een licht-verouderd resultaat tonen dan niets.
        if gecached:
            return gecached[1]
        return {"labels": [], "values": []}

    # GeckoTerminal geeft de nieuwste candle EERST -- omkeren voor een
    # chronologische grafiek (oud -> nieuw, zelfde volgorde als de
    # waarde-grafiek).
    candles = sorted(candles, key=lambda c: c.timestamp)

    grens = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    candles = [c for c in candles if datetime.datetime.fromtimestamp(c.timestamp, tz=datetime.timezone.utc) >= grens]

    resultaat = {
        "labels": [
            datetime.datetime.fromtimestamp(c.timestamp, tz=datetime.timezone.utc).strftime(formaat)
            for c in candles
        ],
        "values": [c.close for c in candles],
    }
    _prijs_cache[days] = (nu, resultaat)
    return resultaat


@app.get("/api/price-history")
async def api_price_history(days: int = 1):
    return JSONResponse(_build_price_chart_data(days))
