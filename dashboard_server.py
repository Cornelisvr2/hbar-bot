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

import asyncio
from collections import deque

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
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


async def _build_dashboard_context_live() -> dict:
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
        pool_apr_breed = compute_fees_apr(snapshot.volume_24h_usd, fee_tier, snapshot.liquidity_usd)
        # (7 sep 2026) Nauwkeurige Fees-APR met SaucerSwap's "balanced
        # range"-noemer (uit bot_data's pool_metrics); de pool-brede
        # variant blijft als fallback en ter vergelijking.
        pm = data.get("pool_metrics")
        pool_apr = pm["fees_apr_balanced"] if pm else pool_apr_breed
        lari = pm["lari"] if pm else None
        lari_realized = data.get("lari_realized")

        # Projecties (1 sep 2026, op verzoek) -- dagelijks samengestelde
        # rente op basis van de HUIDIGE pool-APR, zoals besproken: NIET
        # een enkele, volatiele dag extrapoleren (zou een onrealistisch
        # getal geven), maar de stabielere, jaarlijkse APR-maatstaf.
        totaal = data["total_value_usd"]
        # (8 sep 2026) Projectie op de STABIELSTE maatstaf: 7-daags
        # gemiddelde Fees-APR + LARI-schatting voor onze positie; niet op
        # het 24u-getal (te volatiel) en niet op de hele-pool-APR (die
        # onderschat structureel t.o.v. de gerealiseerde fees).
        fees_apr_7d = pm["fees_apr_7d"] if pm and pm.get("fees_apr_7d") is not None else pool_apr_breed
        projectie_apr = fees_apr_7d + (lari.our_reward_apr if lari else 0.0)
        projectie_30d = totaal * (1 + projectie_apr / 365) ** 30
        projectie_90d = totaal * (1 + projectie_apr / 365) ** 90
        projectie_180d = totaal * (1 + projectie_apr / 365) ** 180
        _pos = data.get("position") or {}

        # Waardeverandering 24u (hergebruikt dezelfde aanpak als het
        # Telegram-rapport).
        vorige_24u = await db.get_portfolio_value_at(1)
        change_24h_pct = None
        if vorige_24u and vorige_24u["total_value_usd"] > 0:
            nu = datetime.datetime.now(datetime.timezone.utc)
            afstand_dagen = abs((nu - vorige_24u["recorded_at"]).total_seconds()) / 86400
            if afstand_dagen <= 1.5:  # zelfde tolerantie-principe als het Telegram-rapport
                change_24h_pct = (totaal - vorige_24u["total_value_usd"]) / vorige_24u["total_value_usd"] * 100

        # BUGFIX (6 sep 2026): omvattende gaskosten-berekening via de
        # mirror node -- de oude berekening (verderop, uit de trades-
        # tabel) telde alleen swap-gas, miste mint/wrap/unwrap/bijstort.
        async def _bereken_omvattende_gaskosten_30d():
            import requests
            from config import NETWORK_SETTINGS
            mirror_node_url = NETWORK_SETTINGS[HEDERA_NETWORK]["mirror_node_url"]
            resp = requests.get(
                f"{mirror_node_url}/api/v1/accounts/{data['wallet_address']}", timeout=15
            )
            resp.raise_for_status()
            hedera_account_id = resp.json().get("account")
            if not hedera_account_id:
                return 0.0
            dertig_dagen_geleden_ts = time.time() - 30 * 86400
            bekende_relay_accounts = {"0.0.7314364", "0.0.995584"}
            totaal_tinybar = 0
            volgende_url = (
                f"{mirror_node_url}/api/v1/transactions"
                f"?account.id={hedera_account_id}&order=desc&limit=100"
                f"&timestamp=gte:{dertig_dagen_geleden_ts:.0f}"
            )
            pagina_teller = 0
            while volgende_url and pagina_teller < 20:  # veiligheidsgrens
                resp = requests.get(f"{mirror_node_url}{volgende_url}" if volgende_url.startswith("/") else volgende_url, timeout=15)
                resp.raise_for_status()
                pagina = resp.json()
                for tx in pagina.get("transactions", []):
                    tx_id = tx.get("transaction_id", "")
                    initiator = tx_id.split("-")[0] if tx_id else ""
                    if initiator == hedera_account_id or initiator in bekende_relay_accounts:
                        totaal_tinybar += tx.get("charged_tx_fee", 0) or 0
                volgende_link = pagina.get("links", {}).get("next")
                volgende_url = volgende_link
                pagina_teller += 1
            return totaal_tinybar / (10 ** 8)

        try:
            totale_kosten_30d_omvattend = await _bereken_omvattende_gaskosten_30d()
        except Exception as e:
            print(f"[waarschuwing] Kon omvattende gaskosten niet berekenen: {e}")
            totale_kosten_30d_omvattend = None

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
            "quote_symbol": "USDC" if HEDERA_NETWORK == "mainnet" else "SAUCE",
            "macro": _macro_for_dashboard(_bot_state().get("macro_regime")),
            "bot_state": _bot_state(),
            "pool_apr_pct": pool_apr * 100,
            "pool_apr_breed_pct": pool_apr_breed * 100,
            "fees_apr_now_pct": pm["fees_apr_now"] * 100 if pm and pm.get("fees_apr_now") is not None else None,
            "fees_apr_7d_pct": pm["fees_apr_7d"] * 100 if pm and pm.get("fees_apr_7d") is not None else None,
            "volume_1h_usd": pm["volume_1h_usd"] if pm else None,
            "volume_24h_usd": pm["volume_24h_usd"] if pm else None,
            "volume_7d_avg_usd": pm["volume_7d_avg_usd"] if pm else None,
            "tvl_in_range_usd": pm["tvl_in_range_usd"] if pm else None,
            "lari_pool_apr_pct": lari.pool_reward_apr * 100 if lari else None,
            "lari_our_apr_pct": lari.our_reward_apr * 100 if lari else None,
            "lari_our_share_pct": lari.our_liquidity_share * 100 if lari else None,
            "lari_our_epoch_usd": lari.our_reward_per_epoch_usd if lari else None,
            "lari_realized_sauce": lari_realized.sauce_received if lari_realized else None,
            "lari_realized_hbar": lari_realized.hbar_received if lari_realized else None,
            "lari_realized_count": lari_realized.airdrop_count if lari_realized else None,
            "total_apr_pct": (pool_apr + (lari.our_reward_apr if lari else 0.0)) * 100,
            "projection_apr_pct": projectie_apr * 100,
            "realized_fees_apr_pct": (_pos["realized_fees_apr"] * 100) if _pos.get("realized_fees_apr") is not None else None,
            "position_days_open": _pos.get("days_open"),
            "projection_30d": projectie_30d,
            "projection_90d": projectie_90d,
            "projection_180d": projectie_180d,
            "change_24h_pct": change_24h_pct,
            "transactions": transacties,
            "total_costs_30d": totale_kosten_30d_omvattend if totale_kosten_30d_omvattend is not None else totale_kosten_30d,
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


from fastapi import Request

@app.post("/telegram/webhook")
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
    return JSONResponse({"ok": True})


# FASE 1 lees-architectuur (12 sep 2026): het dashboard leest de laatste
# snapshot uit dashboard_snapshots (door snapshot_writer.py weggeschreven) i.p.v.
# zelf live GeckoTerminal/Mirror Node te bevragen -> instant laden. Valt terug
# op de live-berekening als er geen (verse) snapshot is, zodat het altijd werkt.
SNAPSHOT_MAX_AGE_SECONDS = 15 * 60

async def _build_dashboard_context() -> dict:
    import json as _json
    from postgres_client import PostgresClient
    db = PostgresClient()
    try:
        await db.connect()
        async with db._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload, extract(epoch from (now() - ts)) AS leeftijd "
                "FROM dashboard_snapshots ORDER BY ts DESC LIMIT 1")
        if row and row["leeftijd"] is not None and row["leeftijd"] <= SNAPSHOT_MAX_AGE_SECONDS:
            ctx = row["payload"] if isinstance(row["payload"], dict) else _json.loads(row["payload"])
            ctx["_snapshot_leeftijd_s"] = int(row["leeftijd"])
            return ctx
    except Exception as e:
        print(f"[dashboard] snapshot lezen mislukt ({e}) -- val terug op live")
    finally:
        try:
            await db.close()
        except Exception:
            pass
    # terugval: live berekenen (traag, maar altijd correct)
    return await _build_dashboard_context_live()


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


# ---------------------------------------------------------------------------
# Live-logpaneel (7 sep 2026): de bot tee't zijn stdout naar ./logs/bot.log
# (zie main_orchestrator.py); het dashboard heeft die map read-only.
# ---------------------------------------------------------------------------
BOT_LOG_FILE = os.environ.get("BOT_LOG_FILE", "/app/logs/bot.log")


def _tail_lines(path: str, n: int) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return list(deque(f, maxlen=n))
    except FileNotFoundError:
        return []


@app.get("/api/logs")
async def api_logs(tail: int = 200):
    tail = max(1, min(tail, 2000))
    return JSONResponse({"lines": [l.rstrip("\n") for l in _tail_lines(BOT_LOG_FILE, tail)]})


@app.get("/api/logs/stream")
async def api_logs_stream():
    async def gen():
        # Begin aan het EINDE van het bestand: de eerste vulling komt via
        # /api/logs; deze stream levert alleen nieuwe regels.
        try:
            f = open(BOT_LOG_FILE, "r", encoding="utf-8", errors="replace")
            f.seek(0, 2)
        except FileNotFoundError:
            f = None
        inode = os.stat(BOT_LOG_FILE).st_ino if f else None
        idle = 0
        while True:
            line = f.readline() if f else ""
            if line:
                idle = 0
                yield f"data: {line.rstrip()}\n\n"
                continue
            await asyncio.sleep(0.5)
            idle += 1
            # Rotatie of nog-niet-bestaand bestand afhandelen
            try:
                st = os.stat(BOT_LOG_FILE)
                if f is None or st.st_ino != inode:
                    if f:
                        f.close()
                    f = open(BOT_LOG_FILE, "r", encoding="utf-8", errors="replace")
                    inode = st.st_ino
            except FileNotFoundError:
                pass
            if idle % 30 == 0:
                yield ": keepalive\n\n"  # houdt de verbinding door Caddy heen open
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Meerlaagse macro-analyse (8 sep 2026) -- schaduwmodus, alleen tonen
# ---------------------------------------------------------------------------
def _macro_for_dashboard(current_bot_regime):
    try:
        from binance_klines_client import BinanceKlinesClient
        from macro_analysis import compute_macro_analysis
        m = compute_macro_analysis(BinanceKlinesClient(), current_bot_regime=current_bot_regime)
        d = m.to_dict()
        d["computed_at_str"] = datetime.datetime.fromtimestamp(m.computed_at).strftime("%d %b %H:%M")
        return d
    except Exception as e:
        print(f"[waarschuwing] macro-analyse niet beschikbaar: {e}")
        return None


# ---------------------------------------------------------------------------
# Scenario-model tot ~2030 (8 sep 2026): HODL vs bot per prijspad
# ---------------------------------------------------------------------------
@app.get("/api/scenarios")
async def api_scenarios():
    from scenario_model import run_all
    ctx = await _build_dashboard_context()
    p0 = ctx.get("hbar_price_usd") or 0.0
    start_value = ctx.get("total_value_usd") or 0.0
    fees_apr = ctx.get("fees_apr_7d_pct")
    if fees_apr is None:
        fees_apr = ctx.get("pool_apr_pct") or 0.0
    lari_apr = ctx.get("lari_our_apr_pct") or 0.0
    total_apr = (fees_apr + lari_apr) / 100.0
    if p0 <= 0 or start_value <= 0:
        return JSONResponse({"error": "geen prijs/waarde beschikbaar"}, status_code=503)
    out = run_all(p0, start_value, total_apr)
    out["inputs"]["fees_apr_pct"] = fees_apr
    out["inputs"]["lari_apr_pct"] = lari_apr
    return JSONResponse(out)


def _bot_state() -> dict:
    """Statusbestand dat de bot elke cyclus schrijft (zie _write_bot_state)."""
    try:
        import json
        with open(os.environ.get("BOT_STATE_FILE", "/app/logs/bot_state.json")) as f:
            d = json.load(f)
        d["age_seconds"] = time.time() - d.get("updated_at", 0)
        return d
    except Exception:
        return {}
