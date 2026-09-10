"""
regime_orchestrator V2.py

Vervangt TradingOrchestrator + LpOrchestrator voor het SAMENGEVOEGDE
kapitaal (EUR 2.000) met een alles-of-niets regime-schakelaar:

- LP_MODE (rustig nieuws): volledige kapitaal in de HBAR/USDC V2-pool
- BULLISH_REFLEX (groot positief nieuws): pool leeghalen, alles naar HBAR
- BEARISH_REFLEX (groot negatief nieuws): pool leeghalen, alles naar USDC

Trigger: dezelfde vaste 40/60-weging als safety_override.py
(compute_fixed_combined_score), nu SYMMETRISCH toegepast -- niet alleen
als paniek-vangnet (alleen SELL forceren), maar ook als bullish-reflex
(BUY forceren). Dat is een bewuste afwijking van het eerdere principe
"een vangnet forceert nooit een koop" -- hier is het geen vangnet, maar
de kernstrategie zelf, expliciet zo gewenst.

Winst nemen uit de bullish-reflex: TrailingStopTracker bepaalt wanneer
de candle voorbij zijn piek is -- zelfde mechanisme als bij reguliere
directionele trades.

BELANGRIJK: dit maakt TradingOrchestrator's graduele BUY/SELL-logica
overbodig voor DIT kapitaal -- die modules blijven bestaan, maar worden
hier niet gebruikt. Zie PLAN.md.
"""

import asyncio
import json
import os
import time
import subprocess
from enum import Enum
from typing import Optional

from rss_news_client import RssNewsClient
from rss_news_client import normalize_headline

MACRO_MIN_MAGNITUDE = int(os.environ.get("MACRO_MIN_MAGNITUDE", "3"))   # alleen marktrelevant algemeen nieuws bewaren
MACRO_MAX_PER_REFRESH = int(os.environ.get("MACRO_MAX_PER_REFRESH", "25"))  # kostenrem op LLM-calls per verversing

SENTIMENT_BIAS_BY_ASSET = {
    "BTC": float(os.environ.get("SENTIMENT_BIAS_BTC", "0.17")),
    "HBAR": float(os.environ.get("SENTIMENT_BIAS_HBAR", "0.27")),
}
from messari_news_client import MessariNewsClient
from llm_sentiment_engine import LlmSentimentEngine
from geckoterminal_client import GeckoTerminalClient
from binance_klines_client import BinanceKlinesClient
from safety_override import compute_fixed_combined_score, compute_combined_volatility_sigma
from flash_event_model import detect_flash_event
from gbm_range_model import apply_regime_bias, evaluate_reflex_transition_economics
from position_planner import TrailingStopTracker
from lp_manager import LpManager, LpPositionConfig, VolatilityRegime, select_optimal_volatility_regime
from hedera_rpc_client import HederaRpcClient, NetworkConfig
import telegram_notify
from config import (
    HEDERA_NETWORK, NETWORK_SETTINGS,
    resolve_testnet_addresses, resolve_mainnet_addresses,
    resolve_testnet_v2_addresses, resolve_mainnet_v2_addresses,
)


POLL_INTERVAL_SECONDS = 60

# Fractie van de beschikbare balans die het vangnet (zie _cycle()) inzet
# bij het openen van een LP-positie -- op verzoek (26 aug 2026) tijdelijk
# op 90% gezet i.p.v. 100%, zodat er bewust wat HBAR achterblijft om
# verder te kunnen testen. Zet terug naar 1.0 zodra dat niet meer nodig is.
LP_SAFETYNET_DEPLOY_FRACTION = float(os.environ.get("LP_SAFETYNET_DEPLOY_FRACTION", "0.9"))

# Absolute ondergrens (in HBAR) die ALTIJD in de wallet moet achterblijven,
# ongeacht de deploy-fractie hierboven -- op verzoek (26 aug 2026): de
# gebruiker hield historisch zelf altijd 50 HBAR achter de hand bij
# handmatig beheer. Bij een grote positie kan het percentage al genoeg
# reserve geven; bij een kleine positie is een percentage alleen niet
# genoeg (gaskosten zijn ongeveer constant in absolute termen, niet
# schalend met de positiegrootte). De daadwerkelijke reserve is het
# GROOTSTE van beide -- zelfde patroon als GAS_RESERVE_USD/
# MIN_GAS_RESERVE_HBAR elders in dit bestand.
LP_SAFETYNET_MIN_RESERVE_HBAR = float(os.environ.get("LP_SAFETYNET_MIN_RESERVE_HBAR", "50"))
SENTIMENT_REFRESH_SECONDS = 5 * 60

# Gedifferentieerde sentiment-halfwaardetijd per asset (28 aug 2026, op
# verzoek): BTC (large-cap, snelle/liquide prijsvorming) veroudert
# sneller dan HBAR (kleinere cap, tragere informatieverwerking).
# AANNAME, geen empirisch geijkte waarde -- hier instelbaar.
SENTIMENT_HALF_LIFE_HOURS_BY_ASSET = {
    "BTC": 1.5,
    "HBAR": 6.0,
}

# Volatiliteitsregime niet elke cyclus herberekenen (bedoeld voor
# uur-schaal-veranderingen, niet minuut-schaal) -- elke 4 uur is genoeg
# (26 aug 2026, aansluitend op compute_volatility_regime()'s eigen
# docstring: "periodiek (elke paar uur), niet bij elke prijs-poll").
VOLATILITY_REGIME_REFRESH_SECONDS = 4 * 60 * 60
REGIME_THRESHOLD = 0.55
# Uitstap-drempel voor hysterese op REGIME_THRESHOLD (30 aug 2026, op
# verzoek) -- zelfde principe als de gematigde-zone-hysterese elders:
# instappen in een reflex-regime gebeurt bij REGIME_THRESHOLD, maar de
# TARGET-regime-bepaling stapt pas weer terug naar lp_mode als het
# signaal duidelijk ONDER deze lagere drempel zakt. Voorkomt dat
# target_regime bij een schommelend signaal rond 0.55 elke cyclus
# heen-en-weer wisselt (ook al beschermen de economische poort en de
# cooldown al tegen DAADWERKELIJKE, ongewenste overgangen -- dit
# voorkomt ook onnodige, verwarrende status-wisselingen zelf).
# AANNAME, geen empirisch geijkte waarde.
REGIME_THRESHOLD_EXIT = 0.40
# Verhoogd van 0.4 naar 0.55 (27 aug 2026), op basis van empirische
# analyse van de 6 eerdere BULLISH_REFLEX-triggers sinds 24 augustus: bij
# een drempel van 0.4 leidden slechts 2 van de 6 (33%) tot een
# betekenisvolle koersbeweging (>3%), de overige 4 (waaronder beide
# triggers van vandaag) tot vrijwel niets (0.04%-1.17%). Alleen de
# trigger met de hoogste confidence (0.55, 24 aug) leverde een sterke
# beweging op (+6.39%). Kleine steekproef (n=6), dus geen absolute
# garantie, maar sterk genoeg patroon om de drempel te verhogen.

# Gematigde-signaal-zone (28 aug 2026, op verzoek) -- introduceert een
# DERDE optie tussen "normaal LP'en" en "volledig uitstappen"
# (BULLISH_REFLEX/BEARISH_REFLEX): bij een signaal dat duidelijk richting
# heeft maar nog niet sterk genoeg is voor een volledige overstap, blijft
# de bot IN de pool, maar met een BREDERE range (via een hoger GBM-
# betrouwbaarheidsniveau) -- verdedigt tegen een grotere beweging, terwijl
# de (empirisch bevestigd, momentum-gekoppelde) hogere fee-APR nog wordt
# meegenomen. Vervangt het eerdere, binaire alles-of-niets-gedrag voor
# dit tussengebied. AANNAME, geen empirisch geijkte waarde.
MODERATE_SENTIMENT_THRESHOLD = 0.30  # boven dit niveau: bredere range i.p.v. de standaard 80%-band
MODERATE_ZONE_CONFIDENCE_LEVEL = 0.95  # verhoogd betrouwbaarheidsniveau -> bredere GBM-range
# Hysterese/dode-zone (30 aug 2026, op verzoek) -- voorkomt "stuiteren"
# tussen normale en gematigde-zone-breedte als het signaal rond
# MODERATE_SENTIMENT_THRESHOLD schommelt (wat elke cyclus onnodige
# gas-kosten zou opleveren). De bot stapt pas terug naar de normale
# breedte als het signaal duidelijk ONDER deze lagere drempel zakt --
# tussen de twee drempels in blijft de bot gewoon in zijn HUIDIGE modus.
MODERATE_ZONE_EXIT_THRESHOLD = 0.20

# Snelle, prijs-gebaseerde flash-detectie (30 aug 2026, op aangeleverde
# feedback) -- reageert DIRECT op een te grote koersbeweging binnen één
# 60s-cyclus, zonder te wachten op de tragere, sentiment-gebaseerde
# detectie (die tot 5 minuten kan duren). AANNAME, geen empirisch
# geijkte waarde -- 3% binnen 60s is uitzonderlijk voor HBAR onder
# normale omstandigheden (vandaag empirisch gemeten: ~0.6% PER UUR).
PRICE_DELTA_FLASH_THRESHOLD = 0.03

# Prijs-orakel-manipulatie-drempel (30 aug 2026, op aangeleverde
# feedback) -- maximale afwijking (in ticks) tussen de huidige tick en
# de 5-minuten-TWAP-tick, vóórdat een mint wordt uitgesteld. 50 ticks,
# exact zoals voorgesteld (~0,5%, aangezien 1 tick ≈ 0,01% prijsverschil).
PRICE_ORACLE_MAX_TICK_DEVIATION = 50


def determine_gbm_confidence_level_stateless(combined_score: float) -> float:
    """
    LET OP (30 aug 2026): deze stateloze versie blijft bestaan voor
    losstaand gebruik/tests, maar de LIVE bot gebruikt voortaan
    RegimeOrchestrator._determine_gbm_confidence_level() hieronder, die
    WEL hysterese toepast (dode zone tussen MODERATE_ZONE_EXIT_THRESHOLD
    en MODERATE_SENTIMENT_THRESHOLD) om te voorkomen dat de bot bij een
    schommelend signaal elke cyclus heen-en-weer wisselt tussen normale
    en gematigde-zone-breedte.
    """
    if abs(combined_score) >= MODERATE_SENTIMENT_THRESHOLD:
        return MODERATE_ZONE_CONFIDENCE_LEVEL
    return 0.80  # standaardwaarde, zelfde als compute_gbm_confidence_interval()'s default

DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"


class Regime(Enum):
    LP_MODE = "lp_mode"
    BULLISH_REFLEX = "bullish_reflex"
    BEARISH_REFLEX = "bearish_reflex"
    DEPEG_HALT = "depeg_halt"  # (8 sep 2026) USDC-depeg-noodstop: 100% HBAR, wacht op /resume


# (8 sep 2026) Trailing-stop-parameters, instelbaar. Bullish: 5% onder de
# hoogste prijs sinds instap, harde stop op instap -5%. Bearish (spiegel):
# 5% boven de laagste prijs, harde stop op instap +5%.
TRAILING_STOP_PCT = float(os.environ.get("TRAILING_STOP_PCT", "0.05"))


class BearishTrailingStopTracker:
    """Spiegel van TrailingStopTracker: volgt de LAAGSTE prijs sinds instap in
    BEARISH_REFLEX (100% USDC); stop = laagste * (1 + pct), nooit boven de
    harde stop op instapprijs * (1 + pct)."""

    def __init__(self, entry_price: float, trailing_distance_pct: float):
        self.entry_price = entry_price
        self.trailing_distance_pct = trailing_distance_pct
        self.lowest_price = entry_price
        self.hard_stop = entry_price * (1 + trailing_distance_pct)

    def update(self, current_price: float) -> float:
        if current_price < self.lowest_price:
            self.lowest_price = current_price
        return min(self.lowest_price * (1 + self.trailing_distance_pct), self.hard_stop)


class RegimeOrchestrator:
    def __init__(self, db):
        self.db = db
        try:
            from event_guard import EventGuard
            self.event_guard = EventGuard(db) if db is not None else None
        except Exception as e:
            print(f"[event-guard] niet geladen: {e}")
            self.event_guard = None
        self.rss_news = RssNewsClient()
        self.messari_news = MessariNewsClient()
        self.llm = LlmSentimentEngine()
        self.geckoterminal = GeckoTerminalClient()
        self.binance_klines = BinanceKlinesClient()

        self.total_capital_usdc = float(os.environ.get("REGIME_TOTAL_CAPITAL_USDC", "2000"))
        self.current_regime = Regime.LP_MODE
        self.trailing_tracker: Optional[TrailingStopTracker] = None
        self.bearish_tracker: Optional[BearishTrailingStopTracker] = None  # (8 sep 2026)
        from depeg_guard import DepegGuard
        self.depeg_guard = DepegGuard(self.binance_klines)  # (8 sep 2026)

        # NIEUW (3 sep 2026, op verzoek): markt-bevestigde terugkeer naar
        # LP_MODE tijdens een reflex-uitstap -- ANDERS dan de bestaande
        # trailing-stop hierboven (die is specifiek voor winst-name bij
        # BULLISH_REFLEX, 5% afstand) is dit een NIEUWE, aparte trigger die
        # voor BEIDE reflex-richtingen werkt: keer terug naar de pool
        # zodra de koers 1% is teruggevallen vanaf de piek/dal sinds de
        # uitstap, OF 1 uur lang binnen een 1%-band is gebleven (beide
        # AANNAMES, samen met de gebruiker bepaald, geen empirisch
        # geijkte waarden). Reset bij elke nieuwe reflex-episode.
        self._reflex_extreme_price: Optional[float] = None
        self._reflex_price_history: list = []  # lijst van (timestamp, prijs)-tuples
        self._reflex_entered_at: Optional[float] = None
        self.reflex_pullback_threshold_pct = float(
            os.environ.get("REFLEX_PULLBACK_THRESHOLD_PCT", "0.01")
        )
        self.reflex_sideways_band_pct = float(
            os.environ.get("REFLEX_SIDEWAYS_BAND_PCT", "0.01")
        )
        # HERZIEN (3 sep 2026, op verzoek): 30 minuten i.p.v. 1 uur.
        self.reflex_sideways_duration_seconds = float(
            os.environ.get("REFLEX_SIDEWAYS_DURATION_SECONDS", str(30 * 60))
        )
        # NIEUW (3 sep 2026, op verzoek): bevestigingsperiode -- zodra EEN
        # van beide ruwe condities (terugval of zijwaarts) actief wordt,
        # moet die nog dit lang ONONDERBROKEN blijven gelden vóórdat
        # daadwerkelijk teruggekeerd wordt naar LP_MODE.
        self._reflex_exit_pending_since: Optional[float] = None
        self._reflex_exit_pending_reason: str = ""
        self.reflex_exit_confirmation_seconds = float(
            os.environ.get("REFLEX_EXIT_CONFIRMATION_SECONDS", str(30 * 60))
        )
        # Actieve reflex-episode-id (27 aug 2026) -- None zolang we in
        # LP_MODE zitten, anders de id van de rij in reflex_episodes die
        # bij het uitstappen wordt afgesloten met de uitstapprijs.
        self._active_reflex_episode_id: Optional[int] = None
        # HERZIEN (3 sep 2026, op verzoek na een geconstateerd gat: een
        # positie die om WELKE reden dan ook sluit -- regime-drift, fee-
        # onderprestatie, of iets anders -- en waarvan de heropening
        # mislukt, bleef daarna VOOR ONBEPAALDE TIJD leeg staan, omdat dit
        # vangnet voorheen een simpele, eenmalige vlag was die alleen bij
        # SPECIFIEK de flash-verdediging expliciet gereset werd). Nu een
        # TIJD-GEBASEERDE cooldown i.p.v. een eenmalige vlag -- lost dit
        # voor ELKE sluitings-oorzaak in één keer op, zonder dat elke
        # nieuwe sluitings-plek zijn eigen, aparte reset nodig heeft.
        # Cooldown bewust RUIM boven de oorspronkelijke zorg (26 aug 2026:
        # zonder enige beperking deed het vangnet ELKE cyclus opnieuw een
        # herbalancerings-SWAP zolang open_position() bleef falen, wat
        # binnen enkele cycli honderden HBAR onnodig omzette) -- 30
        # minuten, AANNAME, geen empirisch geijkte waarde.
        self._last_safetynet_attempt_at = 0.0
        self.safetynet_retry_cooldown_seconds = float(
            os.environ.get("SAFETYNET_RETRY_COOLDOWN_SECONDS", str(30 * 60))
        )
        # Dynamisch volatiliteitsregime (26 aug 2026) -- was voorheen altijd
        # de default NORMAL, nooit daadwerkelijk aan live prijsdata gekoppeld.
        self._cached_volatility_regime = VolatilityRegime.NORMAL
        self._last_volatility_refresh = 0.0

        self._cached_btc_score = 0.0
        self._cached_hbar_score = 0.0
        # Volatility_sigma-caches (28 aug 2026, voor het GBM-range-model) --
        # 0.5 als neutrale startwaarde, zelfde als de fallback bij een
        # mislukte LLM-analyse.
        self._cached_btc_volatility_sigma = 0.5
        self._cached_hbar_volatility_sigma = 0.5
        # Echte, gemeten uurvolatiliteit (28 aug 2026, voor het GBM-model) --
        # 0.006072 (0.6072%) als redelijke startwaarde, gebaseerd op de
        # eerder vandaag empirisch gemeten HBAR-uurvolatiliteit, totdat de
        # eerste verversing draait.
        self._cached_hourly_volatility = 0.006072
        # (7 sep 2026) Start op None i.p.v. "sideways": de eerste meting na
        # een herstart is geen "wijziging", en gaf tot nu toe bij ELKE
        # herstart een valse "sideways -> bull"-melding op Telegram.
        self._cached_macro_regime = None
        self._last_economic_gate_notification_at = 0.0

        # Volatiliteit-kalibratiefactor (28 aug 2026) -- ingeladen bij het
        # opstarten uit het bestand dat recalibrate_from_live_history.py
        # periodiek bijwerkt (zelfde patroon als calibration_examples.json:
        # vereist een herstart om een nieuwe waarde te laten meewegen, geen
        # live-herlaad-mechanisme).
        self._volatility_calibration_factor = self._load_volatility_calibration_factor()

        # Flash-event-detectie en -verdediging (28 aug 2026, op verzoek) --
        # bewust LOS van het Regime-systeem (LP_MODE/BULLISH_REFLEX/
        # BEARISH_REFLEX), want dit is richtingsonafhankelijk
        # (volatiliteits-gedreven kapitaalbehoud), niet sentiment-
        # gedreven. Onthoudt de VORIGE sentiment-score per asset (om
        # d(mu)/dt te kunnen berekenen bij de volgende verversing), en
        # of de bot momenteel in "verdedigingsmodus" zit (LP-positie
        # bewust leeg, wacht tot de volatiliteit is gaan liggen).
        self._previous_btc_score = 0.0
        self._previous_hbar_score = 0.0
        self._flash_defense_until = 0.0  # 0.0 = niet actief
        self.flash_defense_duration_seconds = float(
            os.environ.get("FLASH_DEFENSE_DURATION_SECONDS", str(30 * 60))
        )
        self._last_sentiment_refresh = 0.0
        self._processed_news_ids: set = set()

        # Cooldown tegen flapping: als combined_score rond de drempel
        # schommelt, mag de bot niet elke minuut heen-en-weer schakelen
        # (elke overgang kost swap-fees/slippage). Winst-name via de
        # trailing-stop tijdens BULLISH_REFLEX is hiervan uitgezonderd --
        # dat moet altijd direct kunnen, ongeacht de cooldown.
        self.regime_cooldown_seconds = float(os.environ.get("REGIME_COOLDOWN_SECONDS", str(30 * 60)))
        self._last_transition_at = 0.0

        # Cooldown specifiek voor LP-herbalancering (28 aug 2026, op
        # verzoek) -- voorkomt onnodige gas-kosten bij een prijs die
        # precies op de rand van de range heen-en-weer beweegt. 15 minuten
        # als redelijke, instelbare standaardwaarde (korter dan de
        # regime-cooldown, want out-of-range betekent 0% fee-inkomsten
        # zolang niet herbalanceerd wordt -- te lang wachten heeft ook een
        # kostprijs).
        self.lp_rebalance_cooldown_seconds = float(
            os.environ.get("LP_REBALANCE_COOLDOWN_SECONDS", str(15 * 60))
        )
        self._last_lp_rebalance_at = 0.0

        # NIEUW (3 sep 2026, op verzoek): een positie die buiten zijn range
        # loopt, wordt niet meer METEEN herbalanceerd -- eerst een
        # genade-periode (default 30 minuten, AANNAME) om te zien of de
        # prijs vanzelf terugkeert, wat een onnodige, kostbare
        # herbalancering bespaart bij een kortstondige uitschieter.
        self._out_of_range_detected_at: Optional[float] = None
        self.out_of_range_grace_period_seconds = float(
            os.environ.get("OUT_OF_RANGE_GRACE_PERIOD_SECONDS", str(30 * 60))
        )

        # Fee-onderprestatie-tracking (2 sep 2026, op verzoek) --
        # onthoudt het laatst waargenomen fee-niveau en sinds wanneer
        # dat niet meer gegroeid is, zodat een positie die dicht bij de
        # rand staat EN structureel geen fees verdient (waarschijnlijk
        # omdat het actuele handelsvolume elders in de pool plaatsvindt,
        # buiten onze smalle band) proactief hercentreerd kan worden --
        # los van de bestaande regime-drift-check, die alleen let op
        # sentiment/volatiliteit-gebaseerde breedte-afwijkingen, niet op
        # daadwerkelijke fee-prestatie.
        self._last_significant_fee_hbar = 0.0
        self._fee_stagnant_since = None
        self.fee_stagnation_uren_drempel = float(
            os.environ.get("FEE_STAGNATION_UREN_DREMPEL", "4.0")
        )  # AANNAME, geen empirisch geijkte waarde

        # Automatisch bijstorten van overtollig wallet-kapitaal (30 aug
        # 2026, op verzoek) -- zodra er kapitaal bijgestort wordt (of
        # anderszins los in de wallet komt te staan) terwijl de bot in
        # LP_MODE met een open positie zit, wordt dat automatisch de
        # pool in gestort i.p.v. te blijven wachten tot de eerstvolgende
        # volledige herbalancering.
        self.min_deployable_capital_hbar = float(
            os.environ.get("MIN_DEPLOYABLE_CAPITAL_HBAR", "10.0")
        )  # ondergrens -- voorkomt onnodige gas-kosten voor triviale bedragen
        self.deploy_capital_cooldown_seconds = float(
            os.environ.get("DEPLOY_CAPITAL_COOLDOWN_SECONDS", str(10 * 60))
        )
        self._last_capital_deploy_at = 0.0
        # (7 sep 2026) Naam van de quote-token voor logs/meldingen: op
        # testnet is dat SAUCE, op mainnet USDC.
        self._quote_label = "USDC" if HEDERA_NETWORK == "mainnet" else "SAUCE"

        # Hysterese-status voor de gematigde-zone-breedte (30 aug 2026,
        # op verzoek) -- onthoudt of de bot MOMENTEEL in de bredere,
        # gematigde-zone-modus zit, zodat MODERATE_ZONE_EXIT_THRESHOLD
        # (lager dan de instap-drempel) kan worden toegepast.
        self._in_moderate_zone = False

        # Vorige-cyclus-prijs (30 aug 2026, voor de snelle, prijs-
        # gebaseerde flash-detectie hierboven) -- None bij het opstarten,
        # zodat de allereerste cyclus nooit onterecht een flash-event
        # detecteert (er is dan nog niets om mee te vergelijken).
        self._previous_cycle_price = None

        # Mean-reversion-tracking (30 aug 2026, op verzoek) -- onthoudt
        # per asset het sentiment-niveau VLAK VOOR en TIJDENS de laatst
        # gedetecteerde flash-event, zodat een latere sentiment-
        # verversing kan controleren of dit een overreactie bleek
        # (mean-reversion). None totdat er ooit een flash-event was.
        self._mean_reversion_pre_event_score = {}
        self._mean_reversion_event_score = {}

        # Live pool-APR (30 aug 2026, puur informatief voor nu)
        self._cached_pool_fees_apr = 0.0

        # Foutvlag voor balans-ophaal-storingen binnen de huidige cyclus
        # (30 aug 2026, na een gevonden vervolgprobleem: een mislukte
        # balans-ophaal gaf voorheen stilzwijgend 0.0 terug, wat een
        # kapitaal-bewegende actie (zoals bijstorten) op het verkeerde
        # been kon zetten -- deze vlag laat zulke acties expliciet
        # afzien als er deze cyclus al een storing was, i.p.v. door te
        # gaan met mogelijk onjuiste (aangenomen-nul) data).
        self._balance_fetch_failed_this_cycle = False

        # Korte TTL-caches voor de balans-functies (30 aug 2026, op
        # verzoek: onderzoek naar mogelijk zelf-veroorzaakte, overbodige
        # RPC-belasting -- zie _get_swappable_hbar_balance()/
        # _get_swappable_usdc_balance() voor de volledige toelichting).
        self._hbar_balance_cache = None
        self._hbar_balance_cache_at = 0.0
        self._usdc_balance_cache = None
        self._usdc_balance_cache_at = 0.0

        private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY", "")
        settings = NETWORK_SETTINGS[HEDERA_NETWORK]
        network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
        self.rpc_client = HederaRpcClient(network, private_key) if private_key else None
        self.lp_manager: Optional[LpManager] = None
        self._usdc_decimals = 6  # default, wordt overschreven in _setup_lp_manager indien beschikbaar
        self._hbar_decimals = 8
        if self.rpc_client:
            self._setup_lp_manager()

    @staticmethod
    def _load_volatility_calibration_factor() -> float:
        import json
        import os
        path = os.path.join(os.path.dirname(__file__), "volatility_calibration.json")
        if not os.path.exists(path):
            return 1.0
        try:
            with open(path) as f:
                factor = json.load(f).get("calibration_factor", 1.0)
            print(f"[regime] Volatiliteit-kalibratiefactor ingeladen: {factor:.4f}")
            return factor
        except (json.JSONDecodeError, OSError):
            return 1.0

    def _setup_lp_manager(self):
        self._usdc_decimals = 6  # veilige default, wordt hieronder overschreven
        self._hbar_decimals = 8

        try:
            if HEDERA_NETWORK == "testnet":
                base = resolve_testnet_addresses()
                v2 = resolve_testnet_v2_addresses()
            else:
                base = resolve_mainnet_addresses()
                v2 = resolve_mainnet_v2_addresses()

            self._usdc_decimals = base.usdc_decimals  # 18 op testnet-testtoken, 6 op mainnet

            whbar_addr, usdc_addr = base.whbar_token, base.usdc
            if int(whbar_addr, 16) < int(usdc_addr, 16):
                token0, token1 = whbar_addr, usdc_addr
                t0_dec, t1_dec = self._hbar_decimals, self._usdc_decimals
            else:
                token0, token1 = usdc_addr, whbar_addr
                t0_dec, t1_dec = self._usdc_decimals, self._hbar_decimals

            lp_config = LpPositionConfig(
                position_manager_address=v2.position_manager,
                token0=token0, token1=token1,
                whbar_address=whbar_addr,
                whbar_helper_address=base.whbar_helper,
                factory_address=v2.factory,
                mirror_node_url=NETWORK_SETTINGS[HEDERA_NETWORK]["mirror_node_url"],
                fee_tier=int(os.environ.get("LP_FEE_TIER", "3000")),
                token0_decimals=t0_dec, token1_decimals=t1_dec,
            )
            self.lp_manager = LpManager(self.rpc_client, lp_config)
        except ValueError as e:
            print(f"[regime] lp_manager NIET gekoppeld -- {e}")

    async def run_forever(self):
        import telegram_commands
        command_state = telegram_commands.BotCommandState()
        # (7 sep 2026) LARI-SAUCE herinvesteren -- standaard uit, zie sauce_reinvest.py
        try:
            from sauce_reinvest import SauceReinvestor
            self.sauce_reinvestor = SauceReinvestor(self.rpc_client, self.geckoterminal)
            print(f"[sauce] herinvesteren {'AAN' if self.sauce_reinvestor.cfg.enabled else 'UIT'} "
                  f"(min ${self.sauce_reinvestor.cfg.min_usd:.0f}, MA {self.sauce_reinvestor.cfg.ma_days}d, "
                  f"max {self.sauce_reinvestor.cfg.max_hold_days}d)")
        except Exception as e:
            self.sauce_reinvestor = None
            print(f"[sauce] herinvesteer-module niet geladen: {e}")

        await self._reconcile_regime_state_on_startup()
        await self._reconcile_lp_position_on_startup()

        # Vastzittende, niet-unwrapped WHBAR opsporen en herstellen (28
        # aug 2026) -- kan ontstaan zijn door een eerdere close_position()
        # die halverwege faalde (decrease+collect gelukt, unwrap niet,
        # bv. door een RPC-storing). Draait EENMALIG bij opstarten, dus
        # ook na elke herstart.
        if self.lp_manager:
            try:
                recovered = self.lp_manager.check_and_recover_stuck_whbar()
                if recovered > 0:
                    telegram_notify.send_telegram_message(
                        f"Bij opstarten: {recovered:.4f} vastzittende, niet-"
                        f"unwrapped WHBAR gevonden en automatisch hersteld "
                        f"naar native HBAR."
                    )
            except Exception as e:
                telegram_notify.report_error(
                    "regime_loop: stuck-WHBAR-controle bij opstarten", str(e)
                )

        while True:
            try:
                await telegram_commands.check_for_commands(command_state, self)
                if self.sauce_reinvestor and not command_state.paused:
                    try:
                        await self.sauce_reinvestor.maybe_run(self.current_regime == Regime.LP_MODE)
                    except Exception as e:
                        print(f"[sauce] fout: {e}")
                if command_state.paused:
                    print("[regime] Gepauzeerd via Telegram -- cyclus overgeslagen.")
                else:
                    await self._cycle()
                self._write_bot_state(paused=command_state.paused)
            except Exception as e:
                import traceback
                print(f"FOUT in regime_loop: {e}")
                traceback.print_exc()
                telegram_notify.report_error("regime_loop", str(e))
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    def _check_price_oracle_divergence(self, current_tick: int) -> bool:
        """
        Prijs-orakel-manipulatie-check (30 aug 2026, HERZIEN na
        aangeleverde feedback op de eerste versie) -- vergelijkt de
        HUIDIGE tick met de TWAP-tick (5 minuten, via de pool's eigen,
        ingebouwde observe()-orakelfunctie).

        EERDERE VERSIE (cross-source: pool vs. GeckoTerminal) bleek
        kwetsbaar voor valse alarmen bij normale, legitieme block-to-
        block koersbewegingen, vanwege GeckoTerminal's eigen
        indexerings-vertraging (tot enkele minuten) t.o.v. de pool's
        eigen, onmiddellijke tick-updates. Deze TWAP-versie vergelijkt
        UITSLUITEND on-chain, dezelfde-bron-data (geen cross-source-
        vertraging meer mogelijk als foutbron) -- empirisch bevestigd
        haalbaar: onze pool heeft observationCardinality=1000, ruim
        voldoende voor een 5-minuten-TWAP.

        Drempel: 50 ticks (~0,5%, exact zoals voorgesteld) -- een
        afwijking van de huidige tick t.o.v. het 5-minuten-gemiddelde
        die groter is, wijst op een mogelijke, kortstondige manipulatie
        (bv. een sandwich-aanval) i.p.v. een organische, aanhoudende
        koersbeweging.

        Geeft True terug als veilig (of als de TWAP-aanroep zelf
        faalt -- dan liever doorgaan met de bestaande, andere
        beschermingslagen dan de hele cyclus blokkeren op een
        orakel-storing), False bij een gedetecteerde afwijking.
        """
        from lp_manager import get_twap_tick
        try:
            twap_tick = get_twap_tick(
                self.rpc_client, self.lp_manager.config.factory_address,
                self.lp_manager.config.token0, self.lp_manager.config.token1,
                self.lp_manager.config.fee_tier, seconds_ago=300,
            )
        except Exception as e:
            telegram_notify.report_error(
                "regime_loop: TWAP opvragen mislukt",
                f"{e} -- ga door zonder deze check (andere beschermingslagen blijven actief).",
            )
            return True

        tick_afwijking = abs(current_tick - twap_tick)
        if tick_afwijking > PRICE_ORACLE_MAX_TICK_DEVIATION:
            telegram_notify.report_error(
                "regime_loop: prijs-orakel-afwijking gedetecteerd (TWAP)",
                f"Huidige tick ({current_tick}) wijkt {tick_afwijking} ticks af van de "
                f"5-minuten-TWAP ({twap_tick}) -- mogelijke manipulatie (bv. sandwich-"
                f"aanval). Actie uitgesteld tot de volgende cyclus.",
            )
            return False
        return True

    async def _get_total_capital_hbar(self, current_price: float) -> float:
        """
        NIEUW (1 sep 2026, op verzoek): het TOTALE kapitaal in HBAR-
        termen -- los wallet-saldo PLUS de waarde van een eventuele
        actieve LP-positie. Voorheen gebruikten kapitaal-afhankelijke
        beslissingen (bv. de oude, nu verwijderde select_optimal_
        volatility_regime()-aanroep) alleen self.rpc_client.
        get_hbar_balance(), wat UITSLUITEND het losse walletsaldo is --
        niet het kapitaal dat al in een LP-positie vastzit. Bij een
        goed-functionerende bot (weinig los, veel in de positie) gaf
        dat een sterk onderschat beeld van het werkelijke, totale
        kapitaal.

        Gebruikt compute_position_amounts() om de daadwerkelijke
        HBAR/SAUCE-samenstelling van de actieve positie te bepalen, en
        rekent de SAUCE-kant om naar HBAR-equivalent via de huidige,
        on-chain pool-prijs (SAUCE per HBAR).
        """
        loose_hbar = float(self.rpc_client.get_hbar_balance()) if self.rpc_client else 0.0

        if not self.lp_manager or not self.lp_manager.state.is_open:
            return loose_hbar

        try:
            position_data = self.lp_manager.position_manager.functions.positions(
                self.lp_manager.state.token_id
            ).call()
            liquidity = position_data[5]
        except Exception as e:
            telegram_notify.report_error(
                "regime_loop: totaal-kapitaal berekenen",
                f"Kon liquiditeit van actieve positie niet ophalen: {e} -- "
                f"val terug op alleen het losse walletsaldo voor deze berekening.",
            )
            return loose_hbar

        from lp_manager import compute_position_amounts
        try:
            hbar_in_positie, usdc_in_positie = compute_position_amounts(
                liquidity, self.lp_manager.state.tick_lower, self.lp_manager.state.tick_upper,
                current_price, self._hbar_decimals, self._usdc_decimals,
            )
        except Exception as e:
            telegram_notify.report_error(
                "regime_loop: totaal-kapitaal berekenen",
                f"Kon positie-samenstelling niet berekenen: {e} -- "
                f"val terug op alleen het losse walletsaldo voor deze berekening.",
            )
            return loose_hbar

        usdc_als_hbar = (usdc_in_positie / current_price) if current_price > 0 else 0.0
        return loose_hbar + hbar_in_positie + usdc_als_hbar

    async def _regime_drift_check(self, current_price: float):
        """
        HERONTWORPEN (1 sep 2026, op uitdrukkelijk verzoek na een
        eerdere versie die vannacht werd gebouwd) -- gebruikt niet
        langer de simpele, discrete LOW/NORMAL/HIGH-indeling om te
        bepalen of de bestaande positie herzien moet worden. Die
        indeling en de geavanceerde, doorlopende GBM-methode (gebruikt
        bij ELKE normale positie-opening elders in dit bestand) konden
        onderling tegenstrijdige antwoorden geven -- twee "rekenmachines"
        die elkaar konden tegenspreken. Nu is er nog maar ÉÉN bron van
        waarheid: de GBM-methode zelf.

        Nieuwe logica: bereken wat de GBM-methode NU als ideale breedte
        zou voorstellen, vergelijk dat met de breedte van de HUIDIGE,
        actieve positie (afgeleid uit de al-opgeslagen tick_lower/
        tick_upper, geen aparte "regime_at_creation"-vergelijking meer
        nodig). Bij een substantieel verschil: een kosten-batenanalyse
        (zelfde soort backtest-gebaseerde aanpak als select_optimal_
        volatility_regime() gebruikte, nu toegepast op "blijven" vs.
        "overstappen", inclusief de kosten van sluiten+heropenen) bepaalt
        of de overstap daadwerkelijk de moeite waard is -- niet alleen
        OF er een betere breedte is, maar OF die betere breedte de
        transactiekosten overtreft.

        Kapitaal voor deze berekening: het TOTALE kapitaal (los +
        in de positie), via _get_total_capital_hbar() -- niet alleen
        het losse walletsaldo.
        """
        if not self.lp_manager or not self.lp_manager.state.is_open:
            return

        seconds_since_last_lp_rebalance = time.time() - self._last_lp_rebalance_at
        if seconds_since_last_lp_rebalance < self.lp_rebalance_cooldown_seconds:
            return

        from lp_manager import tick_to_price, get_live_pool_price

        try:
            fresh_price = get_live_pool_price(
                self.rpc_client, self.lp_manager.config.factory_address,
                self.lp_manager.config.token0, self.lp_manager.config.token1,
                self.lp_manager.config.fee_tier,
                self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,
            )
        except Exception as e:
            telegram_notify.report_error(
                "regime_drift_check: pool-prijs opvragen",
                f"{e} -- geen actie ondernomen.",
            )
            return

        # Huidige, actieve breedte afleiden uit de al-opgeslagen ticks
        # -- geen "regime_at_creation"-vergelijking meer nodig.
        huidige_tick_lower = self.lp_manager.state.tick_lower
        huidige_tick_upper = self.lp_manager.state.tick_upper
        prijs_lower = tick_to_price(huidige_tick_lower, self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals)
        prijs_upper = tick_to_price(huidige_tick_upper, self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals)
        centrum_huidig = (prijs_lower + prijs_upper) / 2
        huidige_breedte = (prijs_upper - prijs_lower) / (2 * centrum_huidig) if centrum_huidig > 0 else 0.0

        # Wat zou de GBM-methode NU voorstellen? Zelfde parameters/
        # aanroep-patroon als elders in dit bestand (vangnet,
        # herbalancering, regime-overgang) -- consistent, ÉÉN systeem.
        combined_score_now = compute_fixed_combined_score(self._cached_btc_score, self._cached_hbar_score)
        combined_volatility_sigma_now = compute_combined_volatility_sigma(
            self._cached_btc_volatility_sigma, self._cached_hbar_volatility_sigma
        )
        combined_volatility_sigma_now = min(
            1.0, combined_volatility_sigma_now * self._volatility_calibration_factor
        )
        combined_score_now = apply_regime_bias(combined_score_now, self._cached_macro_regime)
        nieuwe_tick_lower, nieuwe_tick_upper = self.lp_manager.compute_range_via_gbm(
            fresh_price, combined_score_now, combined_volatility_sigma_now,
            self._cached_hourly_volatility,
            macro_regime=self._cached_macro_regime,
            confidence_level=self._determine_gbm_confidence_level(combined_score_now),
        )
        nieuwe_prijs_lower = tick_to_price(nieuwe_tick_lower, self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals)
        nieuwe_prijs_upper = tick_to_price(nieuwe_tick_upper, self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals)
        centrum_nieuw = (nieuwe_prijs_lower + nieuwe_prijs_upper) / 2
        nieuwe_breedte = (nieuwe_prijs_upper - nieuwe_prijs_lower) / (2 * centrum_nieuw) if centrum_nieuw > 0 else 0.0

        if huidige_breedte <= 0 or nieuwe_breedte <= 0:
            return  # defensief, voorkomt een deling-door-nul verderop

        relatieve_afwijking = abs(nieuwe_breedte - huidige_breedte) / huidige_breedte
        DRIFT_DREMPEL = 0.30  # 30% -- voorkomt ruis-gevoelig herbalanceren bij elke kleine schommeling

        if relatieve_afwijking < DRIFT_DREMPEL:
            print(f"[regime-drift] GBM-voorstel wijkt {relatieve_afwijking*100:.0f}% af van de huidige "
                  f"breedte -- onder de drempel ({DRIFT_DREMPEL*100:.0f}%), geen actie.")
            return

        print(f"[regime-drift] Substantiële afwijking: huidige breedte {huidige_breedte*100:.1f}%, "
              f"GBM stelt nu {nieuwe_breedte*100:.1f}% voor ({relatieve_afwijking*100:.0f}% verschil) "
              f"-- kosten-batenanalyse wordt uitgevoerd.")

        # Kosten-batenanalyse: is de overstap daadwerkelijk de moeite
        # waard, gegeven de sluiten+heropenen-kosten? Gebruikt hetzelfde
        # soort backtest-gebaseerde aanpak als select_optimal_volatility_
        # regime() (fee-opbrengst + impermanent loss over de historische
        # prijsreeks), nu toegepast op "huidige breedte behouden" vs.
        # "overstappen naar de GBM-voorgestelde breedte".
        try:
            klines = self.binance_klines.get_klines("HBAR", interval="1h", limit=1000)
            hourly_prices = [k.close for k in klines]
        except Exception as e:
            telegram_notify.report_error(
                "regime_drift_check: historische data ophalen",
                f"{e} -- kosten-batenanalyse overgeslagen, geen actie ondernomen.",
            )
            return

        totaal_kapitaal = await self._get_total_capital_hbar(current_price)

        from lp_manager import evaluate_regime_switch_economics
        economie = evaluate_regime_switch_economics(
            hourly_prices, totaal_kapitaal, huidige_breedte, nieuwe_breedte,
            fee_apr_basislijn=self._cached_pool_fees_apr, fee_apr_basislijn_breedte=1.0,
        )

        if not economie["should_switch"]:
            print(f"[regime-drift] Overstap NIET economisch de moeite waard: netto "
                  f"{economie['net_benefit_hbar']:.2f} HBAR (kosten van sluiten+heropenen wegen niet op "
                  f"tegen de geschatte meerwaarde). Blijft op de huidige breedte.")
            return

        print(f"[regime-drift] Overstap IS economisch de moeite waard: netto "
              f"+{economie['net_benefit_hbar']:.2f} HBAR verwacht voordeel -- positie wordt herzien.")
        telegram_notify.send_telegram_message(
            f"Positie-breedte wijkt substantieel af van het GBM-optimum "
            f"({huidige_breedte*100:.1f}% -> {nieuwe_breedte*100:.1f}%), en de overstap is economisch "
            f"de moeite waard (netto verwacht voordeel: +{economie['net_benefit_hbar']:.2f} HBAR). "
            f"Positie wordt geherbalanceerd."
        )

        await self._sluit_en_heropen_positie(
            fresh_price, current_price, nieuwe_tick_lower, nieuwe_tick_upper,
            reden_label="regime_drift_check",
        )

    async def _sluit_en_heropen_positie(self, fresh_price: float, current_price: float,
                                           nieuwe_tick_lower: int, nieuwe_tick_upper: int,
                                           reden_label: str) -> bool:
        """
        Gedeelde sluit+balanceer+heropen-logica (2 sep 2026, geextraheerd
        uit _regime_drift_check() bij het bouwen van de fee-
        onderprestatie-check hieronder) -- voorkomt dat deze logica op
        meerdere plekken los bestaat en apart onderhouden moet worden
        (we hebben vandaag al meerdere keren gezien dat een bugfix op
        de ene plek niet automatisch ook op een andere, vergelijkbare
        plek terechtkwam).

        reden_label wordt gebruikt in foutmeldingen, zodat duidelijk
        blijft WELKE aanroeper (regime-drift, fee-onderprestatie, etc.)
        de actie initieerde.

        Geeft True terug bij een volledig geslaagde heropening, False
        bij een (gedeeltelijke) mislukking -- de aanroeper hoeft zelf
        geen verdere afhandeling te doen, deze functie stuurt zelf al
        de juiste Telegram-meldingen.
        """
        try:
            self.lp_manager.close_position(self.lp_manager.state.token_id)
        except Exception as e:
            telegram_notify.report_error(f"{reden_label}: positie sluiten", str(e))
            return False

        await self.db.clear_active_lp_position()

        balanceren_gelukt = await self._ensure_balanced_liquidity_ratio(
            fresh_price, nieuwe_tick_lower, nieuwe_tick_upper
        )
        if not balanceren_gelukt:
            return False

        hbar_balance = self._get_swappable_hbar_balance(current_price)
        usdc_balance = self._get_swappable_usdc_balance()
        hbar_raw = int(hbar_balance * (10 ** self._hbar_decimals))
        usdc_raw = int(usdc_balance * (10 ** self._usdc_decimals))

        try:
            self.lp_manager.open_position(
                hbar_raw, usdc_raw, fresh_price,
                slippage_tolerance=0.15, gas_limit_override=1_200_000,
                precomputed_tick_range=(nieuwe_tick_lower, nieuwe_tick_upper),
            )
            await self.db.save_active_lp_position(
                self.lp_manager.state.token_id,
                self.lp_manager.state.tick_lower,
                self.lp_manager.state.tick_upper,
            )
            self._last_lp_rebalance_at = time.time()
            telegram_notify.send_telegram_message(
                f"{reden_label}: herbalancering voltooid, nieuwe positie {self.lp_manager.state.token_id}."
            )
            try:
                import decision_log
                decision_log.log("rebalance_done", reason=reden_label, new_token_id=self.lp_manager.state.token_id,
                                 tick_lower=nieuwe_tick_lower, tick_upper=nieuwe_tick_upper, price=current_price,
                                 hbar_in=hbar_balance, usdc_in=usdc_balance)
            except Exception:
                pass
            return True
        except Exception as e:
            telegram_notify.report_error(f"{reden_label}: nieuwe positie openen", str(e))
            return False

    REBALANCE_PAYBACK_DAYS = float(os.environ.get("REBALANCE_PAYBACK_DAYS", "3.0"))

    def _estimate_position_value_hbar(self, current_price: float) -> float:
        """(10 sep 2026) Positiewaarde in HBAR-equivalent, on-chain; 0 bij storing."""
        try:
            from lp_manager import compute_position_amounts, get_live_pool_price
            st = self.lp_manager.state
            if not st.is_open or st.token_id is None:
                return 0.0
            cfg = self.lp_manager.config
            liquidity = int(self.lp_manager.position_manager.functions.positions(st.token_id).call()[5])
            live = get_live_pool_price(self.rpc_client, cfg.factory_address, cfg.token0, cfg.token1,
                                       cfg.fee_tier, cfg.token0_decimals, cfg.token1_decimals)
            hbar_is_token0 = cfg.token0.lower() == cfg.whbar_address.lower()
            # get_live_pool_price geeft quote-per-HBAR; compute_position_amounts
            # verwacht de CANONIEKE prijs (token1 per token0) -- zelfde
            # omrekening als bot_data.py.
            live_canoniek = live if hbar_is_token0 else (1.0 / live if live > 0 else 0.0)
            a0, a1 = compute_position_amounts(liquidity, st.tick_lower, st.tick_upper, live_canoniek,
                                              cfg.token0_decimals, cfg.token1_decimals)
            hbar_amt, quote_amt = (a0, a1) if hbar_is_token0 else (a1, a0)
            quote_in_hbar = quote_amt / current_price if (HEDERA_NETWORK == "mainnet" and current_price > 0) else 0.0
            return float(hbar_amt + quote_in_hbar)
        except Exception:
            return 0.0

    async def _fee_underperformance_check(self, current_price: float):
        """
        NIEUW (2 sep 2026, op verzoek na een observatie tijdens live-
        testen): een positie kan dicht bij de rand van zijn range staan
        EN structureel geen fees verdienen -- waarschijnlijk omdat het
        actuele handelsvolume elders in de pool plaatsvindt, buiten
        onze smalle band, ook al is de POOL als geheel wel actief (zie
        de live pool-APR). De bestaande _regime_drift_check() vangt dit
        NIET op, want die let uitsluitend op sentiment/volatiliteit-
        gebaseerde breedte-afwijkingen -- een positie die toevallig
        naast het echte volume zit maar waarvan de GBM-voorgestelde
        breedte niet noemenswaardig verschilt van de huidige, blijft zo
        voor onbepaalde tijd vruchteloos staan.

        Logica: als de positie dicht bij de rand staat (zelfde drempel
        als de "dicht bij de rand"-statuslabel elders, <15% of >85%) EN
        de opgebouwde fees al self.fee_stagnation_uren_drempel uur niet
        meetbaar gegroeid zijn, wordt de positie proactief hercentreerd
        op de HUIDIGE prijs (een verse GBM-berekening, dezelfde aanpak
        als _regime_drift_check() -- geen aparte kosten-batenanalyse
        hier: bij structureel nul fee-inkomsten is er per definitie
        niets te verliezen aan fee-opbrengst door over te stappen, enkel
        de kosten van de overstap zelf af te wegen tegen het feit dat de
        positie anders voor onbepaalde tijd vruchteloos blijft staan).

        Reset de stagnatie-tracking zodra de positie NIET meer dicht bij
        de rand staat (dan is dit sowieso niet van toepassing) of zodra
        de fees wél weer meetbaar groeien.
        """
        if not self.lp_manager or not self.lp_manager.state.is_open:
            self._fee_stagnant_since = None
            return

        seconds_since_last_lp_rebalance = time.time() - self._last_lp_rebalance_at
        if seconds_since_last_lp_rebalance < self.lp_rebalance_cooldown_seconds:
            return

        # BUGFIX (3 sep 2026, gevonden na een verdachte -427.2%-melding
        # in productie): deze functie gebruikte current_price (GeckoTerminal-
        # USD, bv. 0.077) i.p.v. de POOL-EIGEN, interne SAUCE-per-HBAR-
        # schaal (bv. ~49) voor de in_range_pct-berekening -- EXACT
        # hetzelfde patroon als de kritieke bug die eerder al in
        # _regime_drift_check() werd gevonden en opgelost, hier per
        # ongeluk herhaald in deze nieuwere functie. fresh_price wordt
        # nu VROEG opgehaald en voortaan overal in deze functie gebruikt
        # (was voorheen pas laat, alleen vlak vóór de GBM-berekening,
        # opgehaald).
        try:
            from lp_manager import get_live_pool_price
            fresh_price = get_live_pool_price(
                self.rpc_client, self.lp_manager.config.factory_address,
                self.lp_manager.config.token0, self.lp_manager.config.token1,
                self.lp_manager.config.fee_tier,
                self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,
            )
        except Exception as e:
            telegram_notify.report_error("fee_underperformance_check: pool-prijs opvragen", str(e))
            return

        from lp_manager import tick_to_price
        tick_lower = self.lp_manager.state.tick_lower
        tick_upper = self.lp_manager.state.tick_upper
        prijs_lower = tick_to_price(tick_lower, self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals)
        prijs_upper = tick_to_price(tick_upper, self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals)
        if prijs_upper <= prijs_lower:
            return  # defensief, voorkomt een deling-door-nul verderop
        in_range_pct = (fresh_price - prijs_lower) / (prijs_upper - prijs_lower) * 100
        # (10 sep 2026) Canoniek -> mensvriendelijk: op mainnet (USDC=token0)
        # is de canonieke schaal omgekeerd; 0% = onderrand in USD/HBAR.
        hbar_is_token0 = self.lp_manager.config.token0.lower() == self.lp_manager.config.whbar_address.lower()
        if not hbar_is_token0:
            in_range_pct = 100.0 - in_range_pct

        if 15 <= in_range_pct <= 85:
            self._fee_stagnant_since = None  # niet dicht bij de rand -- niet van toepassing
            return

        # Actuele, opgebouwde fees opvragen (zelfde patroon als bot_data.py/
        # dashboard, hier lokaal herhaald om geen kruis-afhankelijkheid
        # tussen de bot en het dashboard te creeren).
        try:
            from bot_data import V2_POSITION_MANAGER_ABI
            position_manager = self.rpc_client.w3.eth.contract(
                address=self.lp_manager.config.position_manager_address,
                abi=V2_POSITION_MANAGER_ABI,
            )
            UINT128_MAX = (2 ** 128) - 1
            fee0_raw, fee1_raw = position_manager.functions.collect(
                (self.lp_manager.state.token_id, self.rpc_client.address, UINT128_MAX, UINT128_MAX)
            ).call({"from": self.rpc_client.address})
            # BUGFIX (10 sep 2026): fee0 werd als HBAR gelezen -- op mainnet is
            # token0 USDC, dus de HBAR-fees werden GENEGEERD en de USDC-fees
            # met 8 i.p.v. 6 decimalen gedeeld: "geen meetbare fee-groei"
            # terwijl de positie gewoon verdiende -> twee onnodige
            # herbalanceringen op 8-9 sep. Nu: beide kanten, in HBAR-
            # equivalent (USDC omgerekend via de USD-prijs).
            if hbar_is_token0:
                fee_hbar_raw, fee_quote_raw = fee0_raw, fee1_raw
            else:
                fee_hbar_raw, fee_quote_raw = fee1_raw, fee0_raw
            fee_hbar = fee_hbar_raw / (10 ** self._hbar_decimals)
            fee_quote = fee_quote_raw / (10 ** self._usdc_decimals)
            quote_in_hbar = (fee_quote / current_price) if (HEDERA_NETWORK == "mainnet" and current_price > 0) else 0.0
            fee_hbar_nu = fee_hbar + quote_in_hbar
        except Exception as e:
            telegram_notify.report_error(
                "fee_underperformance_check: fees opvragen",
                f"{e} -- overgeslagen, geen actie ondernomen.",
            )
            return

        # (10 sep 2026) Relatieve drempel i.p.v. 0,001 HBAR absoluut: "geen
        # groei" = minder dan 10% van wat de positie bij de pool-APR sinds
        # de vorige meting had moeten verdienen.
        positie_hbar_equiv = self._estimate_position_value_hbar(current_price)
        uren_sinds_meting = ((time.time() - self._fee_stagnant_since) / 3600) if self._fee_stagnant_since else 1.0
        verwacht_per_uur = positie_hbar_equiv * (self._cached_pool_fees_apr or 0.0) / 8760
        FEE_GROEI_DREMPEL_HBAR = max(0.001, 0.10 * verwacht_per_uur * max(1.0, uren_sinds_meting))
        if fee_hbar_nu > self._last_significant_fee_hbar + FEE_GROEI_DREMPEL_HBAR:
            self._last_significant_fee_hbar = fee_hbar_nu
            self._fee_stagnant_since = None  # fees groeien wel degelijk -- geen actie nodig
            return

        if self._fee_stagnant_since is None:
            self._fee_stagnant_since = time.time()
            return  # net pas beginnen te tellen, nog geen actie

        uren_stagnant = (time.time() - self._fee_stagnant_since) / 3600
        if uren_stagnant < self.fee_stagnation_uren_drempel:
            return

        # (10 sep 2026) Kosten-batenafweging: hercentreren kost ~ROUND_GAS_
        # BUFFER_HBAR + swap-fees. Alleen doen als de verwachte extra fee-
        # opbrengst dat binnen REBALANCE_PAYBACK_DAYS terugverdient.
        import decision_log
        verwacht_per_dag = positie_hbar_equiv * (self._cached_pool_fees_apr or 0.0) / 365
        kosten_hbar = self.ROUND_GAS_BUFFER_HBAR + 0.003 * positie_hbar_equiv  # gas + ~0,3% swap/slippage
        if verwacht_per_dag * self.REBALANCE_PAYBACK_DAYS < kosten_hbar:
            if time.time() - getattr(self, "_fee_underperf_econ_skip_at", 0.0) > 6 * 3600:
                self._fee_underperf_econ_skip_at = time.time()
                print(f"[fee-onderprestatie] {uren_stagnant:.1f}u stagnatie op {in_range_pct:.1f}% van de range, maar "
                      f"hercentreren (~{kosten_hbar:.1f} HBAR) verdient zich niet terug binnen "
                      f"{self.REBALANCE_PAYBACK_DAYS:.0f} dagen (verwacht {verwacht_per_dag:.2f} HBAR/dag) -- overgeslagen.")
                decision_log.log("rebalance_skipped", reason="fee_underperformance_uneconomic",
                                 in_range_pct=in_range_pct, hours_stagnant=uren_stagnant,
                                 cost_hbar=kosten_hbar, expected_hbar_per_day=verwacht_per_dag,
                                 position_hbar=positie_hbar_equiv, price=current_price)
            return

        print(f"[fee-onderprestatie] Positie staat {in_range_pct:.1f}% in de range (dicht bij de rand) "
              f"en heeft {uren_stagnant:.1f} uur geen meetbare fee-groei laten zien -- "
              f"positie wordt proactief hercentreerd.")
        decision_log.log("rebalance", reason="fee_underperformance", in_range_pct=in_range_pct,
                         hours_stagnant=uren_stagnant, fees_hbar_equiv=fee_hbar_nu, cost_hbar=kosten_hbar,
                         expected_hbar_per_day=verwacht_per_dag, price=current_price)

        from safety_override import compute_fixed_combined_score, compute_combined_volatility_sigma
        from gbm_range_model import apply_regime_bias
        combined_score_now = compute_fixed_combined_score(self._cached_btc_score, self._cached_hbar_score)
        combined_volatility_sigma_now = compute_combined_volatility_sigma(
            self._cached_btc_volatility_sigma, self._cached_hbar_volatility_sigma
        )
        combined_volatility_sigma_now = min(
            1.0, combined_volatility_sigma_now * self._volatility_calibration_factor
        )
        combined_score_now = apply_regime_bias(combined_score_now, self._cached_macro_regime)

        nieuwe_tick_lower, nieuwe_tick_upper = self.lp_manager.compute_range_via_gbm(
            fresh_price, combined_score_now, combined_volatility_sigma_now,
            self._cached_hourly_volatility,
            macro_regime=self._cached_macro_regime,
            confidence_level=self._determine_gbm_confidence_level(combined_score_now),
        )

        telegram_notify.send_telegram_message(
            f"Positie staat {uren_stagnant:.1f} uur zonder meetbare fee-groei dicht bij de rand "
            f"({in_range_pct:.1f}% in de range) -- wordt proactief hercentreerd op de huidige prijs."
        )

        gelukt = await self._sluit_en_heropen_positie(
            fresh_price, current_price, nieuwe_tick_lower, nieuwe_tick_upper,
            reden_label="fee_underperformance_check",
        )
        if gelukt:
            self._fee_stagnant_since = None
            self._last_significant_fee_hbar = 0.0

    async def _deploy_excess_capital_if_available(self, current_price: float, bypass_cooldown: bool = False):
        """
        Stort automatisch overtollig wallet-kapitaal bij in de bestaande
        LP-positie (30 aug 2026, op verzoek) -- zodra er kapitaal
        bijgestort wordt (of anderszins los komt te staan, bv. na een
        eerdere gedeeltelijke actie) terwijl de bot in LP_MODE met een
        open positie zit, hoeft dat niet te wachten tot de eerstvolgende
        volledige out-of-range-herbalancering.

        Respecteert de bestaande reserve (via _get_swappable_hbar_
        balance()'s ingebouwde MIN_GAS_RESERVE_HBAR-logica) en een eigen
        cooldown, en doet niets bij een te klein bedrag (voorkomt
        onnodige gas-kosten voor triviale stortingen).
        """
        if self.current_regime != Regime.LP_MODE:
            return
        if not self.lp_manager or not self.lp_manager.state.is_open:
            return
        if (not bypass_cooldown and (time.time() - self._last_capital_deploy_at) < self.deploy_capital_cooldown_seconds):
            return

        excess_hbar = self._get_swappable_hbar_balance(current_price)
        if excess_hbar < self.min_deployable_capital_hbar:
            return

        tick_lower = self.lp_manager.state.tick_lower
        tick_upper = self.lp_manager.state.tick_upper

        from lp_manager import get_live_pool_price
        try:
            fresh_price = get_live_pool_price(
                self.rpc_client, self.lp_manager.config.factory_address,
                self.lp_manager.config.token0, self.lp_manager.config.token1,
                self.lp_manager.config.fee_tier,
                self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,
            )
        except Exception:
            fresh_price = current_price

        # BUGFIX (7 sep 2026): cooldown ZETTEN VOORDAT de voorbereidende
        # swap start. De fix van 6 sep zette hem pas vlak voor
        # increaseLiquidity(); mislukte de swap hierboven, dan werd de
        # functie via 'return' verlaten ZONDER cooldown -- en probeerde de
        # bot elke cyclus (~60s) opnieuw te swappen.
        self._last_capital_deploy_at = time.time()

        balanceren_gelukt = await self._ensure_balanced_liquidity_ratio(
            fresh_price, tick_lower, tick_upper, max_hbar_to_use=excess_hbar
        )
        if not balanceren_gelukt:
            return  # veiligheidsklem geactiveerd -- niet doorgaan met een onbalanceerde storting

        hbar_balance = self._get_swappable_hbar_balance(current_price)
        usdc_balance = self._get_swappable_usdc_balance()
        if hbar_balance < self.min_deployable_capital_hbar:
            return  # na balanceren toch te weinig over om de moeite waard te zijn

        # Veiligheidscheck (30 aug 2026, na een gevonden vervolgprobleem):
        # als er deze cyclus al een balans-ophaal-storing was (bv. een
        # 502 van de RPC-relay), kunnen hbar_balance/usdc_balance
        # hierboven onbetrouwbaar zijn (mogelijk stilzwijgend 0.0
        # i.p.v. de daadwerkelijke waarde) -- dan NIET doorgaan met een
        # storting op basis van mogelijk onjuiste data.
        if self._balance_fetch_failed_this_cycle:
            print("[balans-diagnose] Bijstorten overgeslagen -- balans-ophaal-storing "
                  "deze cyclus, data mogelijk onbetrouwbaar.")
            return

        # DEFENSIEVE MARGE (1 sep 2026, na een niet-volledig-verklaarde
        # INSUFFICIENT_TOKEN_BALANCE-crash) -- 2% marge op het net
        # gelezen saldo, als extra buffer bovenop de bestaande gas-
        # reserve en swap-marge, voor het geval de balans-lezing hier
        # (ondanks de cache-invalidatie + 4s-pauze na een voorgaande
        # swap) toch nog een fractie afwijkt van de daadwerkelijke,
        # on-chain staat op het moment van de increaseLiquidity()-call.
        # EERLIJKE KANTTEKENING: de exacte oorzaak van die crash is NIET
        # met zekerheid vastgesteld -- er bleken al twee beschermingslagen
        # te bestaan (gas-reserve + 5%-swap-marge). Dit is een
        # voorzichtige, extra laag, geen garantie.
        BIJSTORT_VEILIGHEIDSMARGE = 0.98
        hbar_raw = int(hbar_balance * BIJSTORT_VEILIGHEIDSMARGE * (10 ** self._hbar_decimals))
        usdc_raw = int(usdc_balance * BIJSTORT_VEILIGHEIDSMARGE * (10 ** self._usdc_decimals))

        # (6 sep 2026, aangevuld 7 sep) cooldown is hierboven al gezet,
        # VOOR de swap; hier nogmaals zodat de 10 min vanaf de echte
        # storting tellen.
        self._last_capital_deploy_at = time.time()
        try:
            tx_hash = self.lp_manager.deploy_additional_capital(
                self.lp_manager.state.token_id, hbar_raw, usdc_raw,
            )
            if tx_hash:
                telegram_notify.send_telegram_message(
                    f"Overtollig kapitaal automatisch bijgestort in positie "
                    f"{self.lp_manager.state.token_id}: "
                    f"{hbar_balance:.4f} HBAR + {usdc_balance:.2f} {self._quote_label}."
                )
                # (7 sep 2026) increaseLiquidity() gebruikt nooit exact het
                # gewrapte bedrag (0,5% approve-marge + afronding); het
                # restje bleef als WHBAR staan tot de volgende HERSTART.
                # Nu direct terughalen naar native HBAR.
                try:
                    time.sleep(2)
                    recovered = self.lp_manager.check_and_recover_stuck_whbar()
                    if recovered:
                        print(f"[bijstorten] WHBAR-restje van {recovered:.4f} na bijstorten teruggehaald")
                except Exception as e:
                    print(f"[bijstorten] WHBAR-restje terughalen mislukt: {e}")
            else:
                telegram_notify.report_error(
                    "regime_loop: kapitaal bijstorten",
                    "increaseLiquidity() gaf geen succesvolle receipt terug.",
                )
        except Exception as e:
            telegram_notify.report_error("regime_loop: kapitaal bijstorten", str(e))

    async def _rebalance_if_out_of_range(self, current_price: float):
        """
        Checkt of de actieve LP-positie buiten zijn tick-range is gelopen
        (bv. na een prijsbeweging tijdens de bot niet actief was), en
        herbalanceert indien nodig -- met het BEWEZEN, vandaag opgebouwde
        patroon (get_live_pool_price, proportionele amount-afleiding,
        ruimere marge, gas-omzeiling, database-persistentie), niet de
        oudere, ongefixte LpManager.rebalance_if_needed() (26 aug 2026).

        Dit is een LOS probleem van de opstart-reconciliatie hierboven:
        die voorkomt duplicaten ("heb ik al iets lopen?"), dit checkt of
        wat er lopen is nog wel goed gepositioneerd is ("is het nog
        optimaal?"). Wordt zowel na de opstart-reconciliatie aangeroepen
        als elke reguliere cyclus, want de prijs kan op elk moment
        buiten de range lopen, niet alleen rond een herstart.
        """
        if not self.lp_manager or not self.lp_manager.state.is_open:
            return

        # Cooldown tegen te snel herhaald herbalanceren (28 aug 2026, op
        # verzoek: voorkomt onnodige gas-kosten als de prijs precies op de
        # rand van de range heen-en-weer beweegt) -- zelfde principe als
        # regime_cooldown_seconds, maar voor LP-herbalancering specifiek.
        seconds_since_last_lp_rebalance = time.time() - self._last_lp_rebalance_at
        if seconds_since_last_lp_rebalance < self.lp_rebalance_cooldown_seconds:
            return

        # Live, pool-eigen prijs gebruiken voor de beslissing zelf, niet
        # alleen voor de uitvoering erna -- zelfde reden als eerder vandaag:
        # GeckoTerminal kan verouderd zijn t.o.v. de daadwerkelijke on-chain
        # staat, en deze beslissing (wel/niet herbalanceren) moet daarop
        # gebaseerd zijn, niet op een mogelijk achterhaalde externe waarde.
        from lp_manager import get_live_pool_price
        try:
            live_price = get_live_pool_price(
                self.rpc_client, self.lp_manager.config.factory_address,
                self.lp_manager.config.token0, self.lp_manager.config.token1,
                self.lp_manager.config.fee_tier,
                self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,
            )
        except Exception:
            live_price = current_price  # val terug op de meegegeven prijs als ophalen faalt

        if not self.lp_manager.is_price_out_of_range(live_price):
            self._out_of_range_detected_at = None  # prijs is (weer) binnen bereik -- reset
            return

        # Genade-periode (3 sep 2026, op verzoek): pas herbalanceren nadat
        # de positie al minstens out_of_range_grace_period_seconds
        # ONONDERBROKEN buiten bereik is geweest -- een kortstondige
        # uitschieter die vanzelf terugkeert, kost dan geen onnodige
        # herbalancerings-transactie.
        nu = time.time()
        if self._out_of_range_detected_at is None:
            self._out_of_range_detected_at = nu
            print(f"[regime] LP-positie buiten range gelopen (prijs={live_price:.5f}) -- "
                  f"genade-periode van {self.out_of_range_grace_period_seconds/60:.0f} min gestart, "
                  f"nog geen actie.")
            return
        if (nu - self._out_of_range_detected_at) < self.out_of_range_grace_period_seconds:
            return  # nog binnen de genade-periode, stil wachten

        current_price = live_price  # de rest van deze functie gebruikt nu consistent de live prijs

        telegram_notify.send_telegram_message(
            f"LP-positie buiten range gelopen (prijs={current_price:.5f}) -- "
            f"herbalanceren..."
        )

        try:
            self.lp_manager.close_position(self.lp_manager.state.token_id)
            await self.db.clear_active_lp_position()
        except Exception as e:
            # Automatische, veilige verificatie (28 aug 2026): in plaats van
            # meteen een alarmerende "HANDMATIGE CONTROLE nodig"-melding te
            # sturen, checken we EERST on-chain of de close-transactie
            # daadwerkelijk mislukte, of dat alleen het ANTWOORD verloren
            # ging (bv. door een 502 van de RPC-relay) terwijl de
            # transactie zelf wel degelijk doorging. Empirisch aanleiding:
            # herhaalde 502's van testnet.hashio.io tijdens het sluiten
            # (28 aug 2026).
            token_id = self.lp_manager.state.token_id
            try:
                position = self.lp_manager.position_manager.functions.positions(token_id).call()
                still_open = position[5] > 0  # liquidity
            except Exception:
                still_open = None  # verificatie zelf mislukte ook

            if still_open is False:
                # De close IS gelukt -- alleen het antwoord ging verloren.
                self.lp_manager.state.is_open = False
                await self.db.clear_active_lp_position()

                # De exception kan precies bij de unwrap-stap zijn
                # opgetreden (28 aug 2026, empirisch bevestigd: dit
                # exacte scenario liet eerder 109.52 WHBAR onopgemerkt
                # vastzitten) -- meteen controleren en herstellen.
                recovered_msg = ""
                try:
                    recovered = self.lp_manager.check_and_recover_stuck_whbar()
                    if recovered > 0:
                        recovered_msg = (
                            f" Tevens {recovered:.4f} vastzittende WHBAR "
                            f"gevonden en hersteld naar native HBAR."
                        )
                except Exception:
                    pass  # niet kritiek -- de eerstvolgende opstart-check dekt dit ook af

                telegram_notify.send_telegram_message(
                    f"Herbalanceren (sluiten): transactie leek te falen ({e}), maar "
                    f"on-chain verificatie bevestigt dat positie {token_id} "
                    f"daadwerkelijk gesloten is. Kapitaal is veilig, geen "
                    f"handmatige actie nodig -- de volgende cyclus opent normaal "
                    f"een nieuwe positie.{recovered_msg}"
                )
            elif still_open is True:
                telegram_notify.report_error(
                    "regime_loop: herbalanceren (sluiten)",
                    f"{e} -- ON-CHAIN BEVESTIGD: positie {token_id} staat nog "
                    f"open (liquidity={position[5]}). Kapitaal zit nog veilig "
                    f"in de bestaande positie, geen actie ondernomen. Dit lijkt "
                    f"een tijdelijke netwerkfout -- de bot probeert het "
                    f"vanzelf opnieuw bij de volgende cyclus.",
                )
            else:
                telegram_notify.report_error(
                    "regime_loop: herbalanceren (sluiten)",
                    f"{e} -- kapitaal mogelijk nog (deels) in de oude positie, "
                    f"EN de automatische verificatie zelf mislukte ook. "
                    f"HANDMATIGE CONTROLE nodig.",
                )
            return

        hbar_balance = self._get_swappable_hbar_balance(current_price)
        usdc_balance = self._get_swappable_usdc_balance()
        if hbar_balance <= 0 or usdc_balance <= 0:
            telegram_notify.report_error(
                "regime_loop: herbalanceren (heropenen)",
                "Onvoldoende balans aan een van beide kanten na het sluiten -- "
                "positie NIET heropend, kapitaal staat los in de wallet.",
            )
            return

        from lp_manager import compute_amount1_for_amount0, compute_amount0_for_amount1, get_live_pool_price
        try:
            fresh_price = get_live_pool_price(
                self.rpc_client, self.lp_manager.config.factory_address,
                self.lp_manager.config.token0, self.lp_manager.config.token1,
                self.lp_manager.config.fee_tier,
                self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,
            )
        except Exception:
            fresh_price = current_price

        combined_score_now = compute_fixed_combined_score(self._cached_btc_score, self._cached_hbar_score)
        combined_volatility_sigma_now = compute_combined_volatility_sigma(
            self._cached_btc_volatility_sigma, self._cached_hbar_volatility_sigma
        )
        combined_volatility_sigma_now = min(
            1.0, combined_volatility_sigma_now * self._volatility_calibration_factor
        )
        combined_score_now = apply_regime_bias(combined_score_now, self._cached_macro_regime)
        tick_lower, tick_upper = self.lp_manager.compute_range_via_gbm(
            fresh_price, combined_score_now, combined_volatility_sigma_now,
            self._cached_hourly_volatility,
            macro_regime=self._cached_macro_regime,
            confidence_level=self._determine_gbm_confidence_level(combined_score_now),
        )

        # Herbalanceren voor maximale kapitaalbenutting (26 aug 2026,
        # terecht gevonden aandachtspunt) -- zonder dit zou de beperkende-
        # kant-logica hieronder gewoon de kleinste kant volledig gebruiken
        # en de rest van de andere kant ongebruikt laten liggen, ook als
        # een kleine swap vooraf een grotere, volledigere positie had
        # kunnen opleveren.
        balanceren_gelukt = await self._ensure_balanced_liquidity_ratio(fresh_price, tick_lower, tick_upper)
        if not balanceren_gelukt:
            telegram_notify.report_error(
                "regime_loop: herbalanceren (heropenen)",
                "Balanceren werd tegengehouden door de veiligheidsklem -- "
                "positie NIET heropend, kapitaal staat los in de wallet. "
                "HANDMATIGE CONTROLE aanbevolen.",
            )
            return
        hbar_balance = self._get_swappable_hbar_balance(fresh_price)
        usdc_balance = self._get_swappable_usdc_balance()

        hbar_raw_available = int(hbar_balance * (10 ** self._hbar_decimals))
        usdc_raw_available = int(usdc_balance * (10 ** self._usdc_decimals))
        needed_usdc_for_full_hbar = self.lp_manager.compute_needed_usdc_for_hbar(
            hbar_raw_available, fresh_price, tick_lower, tick_upper,
        )
        if needed_usdc_for_full_hbar <= usdc_raw_available:
            hbar_raw, usdc_raw = hbar_raw_available, needed_usdc_for_full_hbar
        else:
            usdc_raw = usdc_raw_available
            hbar_raw = self.lp_manager.compute_needed_hbar_for_usdc(
                usdc_raw_available, fresh_price, tick_lower, tick_upper,
            )

        try:
            self.lp_manager.open_position(
                hbar_raw, usdc_raw, fresh_price, slippage_tolerance=0.15,
                gas_limit_override=1_200_000,
                precomputed_tick_range=(tick_lower, tick_upper),
            )
            await self.db.save_active_lp_position(
                self.lp_manager.state.token_id,
                self.lp_manager.state.tick_lower,
                self.lp_manager.state.tick_upper,
            )
            telegram_notify.send_telegram_message(
                f"LP-positie geherbalanceerd: {hbar_raw/(10**self._hbar_decimals):.4f} HBAR "
                f"+ {usdc_raw/(10**self._usdc_decimals):.2f} {self._quote_label}."
                + (" [Gematigde-zone: bredere range i.p.v. volledig uitstappen.]"
                   if abs(combined_score_now) >= MODERATE_SENTIMENT_THRESHOLD else "")
            )
            self._last_lp_rebalance_at = time.time()
            self._out_of_range_detected_at = None  # genade-periode-tracking resetten, klaar voor een volgende keer
        except Exception as e:
            telegram_notify.report_error(
                "regime_loop: herbalanceren (heropenen)",
                f"{e} -- kapitaal staat los in de wallet, HANDMATIGE CONTROLE nodig.",
            )

    async def _ensure_balanced_liquidity_ratio(self, current_price: float,
                                                  tick_lower: int, tick_upper: int,
                                                  max_hbar_to_use: Optional[float] = None) -> bool:
        """
        Checkt of de huidige HBAR/SAUCE-balans al voldoende in verhouding
        is voor de gegeven tick-range, en swapt indien nodig -- in BEIDE
        richtingen (26 aug 2026, symmetrische versie: de eerdere losse
        implementaties in het vangnet/de reguliere overgangslogica
        checkten alleen "is SAUCE genoeg voor de volledige HBAR-inzet",
        nooit de omgekeerde richting "is HBAR genoeg voor de volledige
        SAUCE-inzet" -- wat kapitaal liet liggen als de wallet juist een
        overschot aan SAUCE had i.p.v. HBAR).

        max_hbar_to_use: optioneel plafond op de HBAR-kant (bv. het
        vangnet houdt bewust een reserve aan, dus mag niet de VOLLEDIGE
        wallet-balans als uitgangspunt nemen voor deze berekening).

        Retourneert False (30 aug 2026, na een gevonden vervolgprobleem)
        als de veiligheidsklem het balanceren heeft tegengehouden -- de
        aanroeper moet dan ZELF ook stoppen (niet doorgaan met een
        vervolgstap die een nog-onbalanceerde balans aanneemt), i.p.v.
        blind te veronderstellen dat balanceren altijd lukt. True in
        alle andere gevallen (inclusief "geen swap nodig, was al in
        balans").

        Wordt vanuit meerdere plekken aangeroepen (vangnet, reguliere
        LP_MODE-heropening, out-of-range-herbalancering) om deze logica
        niet driemaal apart te hoeven onderhouden.
        """
        # HERSCHREVEN (6 sep 2026, op verzoek): gebruikt nu
        # compute_optimal_swap_for_position() -- een wiskundig exacte,
        # ene-staps berekening -- i.p.v. de oude "raad de helft van het
        # tekort, geef anders volledig op"-heuristiek. Die oude aanpak
        # kon een 100% eenzijdige positie (bv. na een reflex-uitstap)
        # STRUCTUREEL nooit balanceren: het berekende swap-bedrag was
        # dan per definitie groter dan de eenzijdige balans, en de
        # functie gaf het simpelweg op i.p.v. het resterende, wel
        # haalbare deel te verdelen. De nieuwe berekening werkt vanuit
        # ELKE startverhouding, inclusief 0%/100%.
        hbar_balance = self._get_swappable_hbar_balance(current_price)
        if max_hbar_to_use is not None:
            hbar_balance = min(hbar_balance, max_hbar_to_use)
        usdc_balance = self._get_swappable_usdc_balance()
        hbar_raw = int(hbar_balance * (10 ** self._hbar_decimals))
        usdc_raw = int(usdc_balance * (10 ** self._usdc_decimals))

        if hbar_raw <= 0 and usdc_raw <= 0:
            return True  # BEIDE kanten zijn leeg -- er valt niets te swappen, geen fout

        richting, bedrag_raw = self.lp_manager.compute_optimal_swap_for_position(
            hbar_raw, usdc_raw, current_price, tick_lower, tick_upper,
        )
        print(f"[balans-diagnose] hbar_raw={hbar_raw} ({hbar_balance:.4f} HBAR), "
              f"usdc_raw={usdc_raw} ({usdc_balance:.4f} {self._quote_label}), "
              f"current_price={current_price}, tick_lower={tick_lower}, tick_upper={tick_upper}, "
              f"richting={richting}, bedrag_raw={bedrag_raw}")

        if richting is None:
            return True  # al voldoende gebalanceerd, geen swap nodig

        if richting == "HBAR_TO_USDC":
            hbar_to_swap = bedrag_raw / (10 ** self._hbar_decimals)
            # Deze klem zou met de exacte berekening praktisch nooit meer
            # mogen triggeren (het berekende bedrag komt per constructie
            # nooit boven de totale, beschikbare waarde uit) -- blijft
            # als pure defensieve marge staan, en klemt nu naar 95% i.p.v.
            # volledig op te geven.
            if hbar_to_swap > hbar_balance:
                print(f"[balans-diagnose] Onverwacht: berekend swap-bedrag "
                      f"({hbar_to_swap:.4f} HBAR) overschrijdt de balans "
                      f"({hbar_balance:.4f} HBAR) -- geklemd naar 95%.")
                hbar_to_swap = hbar_balance * 0.95
            if hbar_to_swap > 0.01:  # ondergrens om micro-swaps met alleen gaskosten te voorkomen
                swap_gelukt = await self._run_swap_and_log("HBAR_TO_USDC", hbar_to_swap, None)
                if not swap_gelukt:
                    return False  # swap mislukt -- NIET doorgaan met een verouderde balans-aanname
            return True
        else:  # richting == "USDC_TO_HBAR"
            usdc_to_swap = bedrag_raw / (10 ** self._usdc_decimals)
            if usdc_to_swap > usdc_balance:
                print(f"[balans-diagnose] Onverwacht: berekend swap-bedrag "
                      f"({usdc_to_swap:.4f} {self._quote_label}) overschrijdt de balans "
                      f"({usdc_balance:.4f} {self._quote_label}) -- geklemd naar 95%.")
                usdc_to_swap = usdc_balance * 0.95
            if usdc_to_swap > 1.0:  # ondergrens
                swap_gelukt = await self._run_swap_and_log("USDC_TO_HBAR", usdc_to_swap, None)
                if not swap_gelukt:
                    return False  # swap mislukt -- NIET doorgaan met een verouderde balans-aanname
            return True

    async def _reconcile_lp_position_on_startup(self):
        """
        Checkt bij het opstarten of er al een LP-positie open staat
        (26 aug 2026 -- lost een kritieke bug op: LpManager.state.is_open
        is puur in-memory, dus zonder dit "vergeet" de bot bij ELKE
        herstart dat er al een positie was, en opent het vangnet blind
        een NIEUWE bovenop de bestaande. Empirisch bevestigd: de
        nachtelijke herkalibratie-herstart veroorzaakte precies dit,
        resulterend in meerdere tegelijk openstaande posities).

        Herstelt de bekende positie in LpManager.state ALS die nog
        daadwerkelijk on-chain open staat (nooit blind vertrouwen op de
        database alleen, altijd on-chain verifieren).
        """
        if not self.lp_manager:
            return

        saved = await self.db.get_active_lp_position()
        if not saved:
            return

        try:
            position_data = self.lp_manager.position_manager.functions.positions(
                saved["token_id"]
            ).call()
            actual_liquidity = position_data[5]
        except Exception as e:
            telegram_notify.report_error(
                "regime_loop: opstart-reconciliatie",
                f"Kon opgeslagen positie {saved['token_id']} niet verifieren: {e} -- "
                f"HANDMATIGE CONTROLE nodig.",
            )
            return

        if actual_liquidity > 0:
            self.lp_manager.state.token_id = saved["token_id"]
            self.lp_manager.state.tick_lower = saved["tick_lower"]
            self.lp_manager.state.tick_upper = saved["tick_upper"]
            self.lp_manager.state.is_open = True
            self._last_safetynet_attempt_at = time.time()  # er is al een positie, vangnet hoeft niet te vuren
            print(f"[regime] Bestaande LP-positie hersteld na herstart: "
                  f"token_id={saved['token_id']}, liquidity={actual_liquidity}")
        else:
            # Opgeslagen positie bleek toch gesloten (bv. handmatig, of via
            # een pad dat de database niet bijwerkte) -- opruimen.
            await self.db.clear_active_lp_position()
            print(f"[regime] Opgeslagen positie {saved['token_id']} bleek al gesloten, "
                  f"database-vermelding opgeruimd.")

    async def _check_depeg(self, current_price: float):
        """(8 sep 2026) Zie depeg_guard.py. current_price = HBAR in USDC (pool)."""
        import decision_log
        try:
            binance = None
            try:
                kl = self.binance_klines.get_klines("HBAR", interval="1m", limit=1)
                binance = kl[-1].close if kl else None
            except Exception:
                pass
            halt, reading = self.depeg_guard.check(current_price, binance)
        except Exception as e:
            print(f"[depeg] check mislukt: {str(e)[:100]}")
            return
        if reading is None:
            return
        if reading.signals:
            print(f"[depeg] signalen {reading.signals}: {reading.summary()}")
        if self.depeg_guard.should_warn(reading):
            telegram_notify.send_telegram_message(f"⚠️ USDC-waarschuwing: {reading.summary()}")
            decision_log.log("depeg_warning", **{k: getattr(reading, k) for k in
                             ("binance_usdc_usdt", "coingecko_usdc_usd", "pool_hbar_usdc", "binance_hbar_usdt", "signals")})
        if not halt:
            return
        telegram_notify.send_telegram_message(
            f"🚨 USDC-DEPEG-NOODSTOP: {reading.summary()} -- positie sluiten, alles naar HBAR, bot stopt (DEPEG_HALT). "
            f"Hervatten met /resume zodra je USDC weer vertrouwt.")
        decision_log.log("depeg_halt", price=current_price, **{k: getattr(reading, k) for k in
                         ("binance_usdc_usdt", "coingecko_usdc_usd", "pool_hbar_usdc", "binance_hbar_usdt", "signals")})
        await self._execute_depeg_halt(current_price)

    async def _execute_depeg_halt(self, current_price: float):
        from depeg_guard import DEPEG_SWAP_SLIPPAGE
        errors = []
        try:
            if self.lp_manager and self.lp_manager.state.is_open:
                self.lp_manager.close_position(self.lp_manager.state.token_id)
                await self.db.clear_active_lp_position()
        except Exception as e:
            errors.append(f"sluiten: {e}")
        try:
            usdc = self._get_swappable_usdc_balance()
            if usdc > 1.0:
                ok = await self._run_swap_and_log("USDC_TO_HBAR", usdc, None, slippage=DEPEG_SWAP_SLIPPAGE)
                if not ok:
                    errors.append("USDC->HBAR swap mislukt")
        except Exception as e:
            errors.append(f"swap: {e}")
        self.trailing_tracker = None
        self.bearish_tracker = None
        self.current_regime = Regime.DEPEG_HALT
        self._last_transition_at = time.time()
        try:
            await self.db.save_regime_state(Regime.DEPEG_HALT.value, None, self._active_reflex_episode_id,
                                            self._flash_defense_until)
        except Exception as e:
            errors.append(f"state opslaan: {e}")
        if errors:
            telegram_notify.report_error("depeg_halt", "; ".join(errors)[:400] +
                                         " -- CONTROLEER DE WALLET HANDMATIG.")

    def _write_bot_state(self, paused: bool = False):
        """(8 sep 2026) Klein statusbestand op de gedeelde logs-map: het
        dashboard toont hiermee het bot-regime naast de macro-analyse, en
        het heartbeat-script (heartbeat_check.sh) bewaakt de mtime."""
        try:
            import json
            path = os.environ.get("BOT_STATE_FILE", "/app/logs/bot_state.json")
            st = self.lp_manager.state if self.lp_manager else None
            data = {
                "updated_at": time.time(),
                "regime": self.current_regime.value,
                "macro_regime": self._cached_macro_regime,
                "paused": paused,
                "position_token_id": st.token_id if (st and st.is_open) else None,
                "hourly_volatility": self._cached_hourly_volatility,
            }
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except Exception as e:
            print(f"[state] statusbestand niet geschreven: {e}")

    async def _reconcile_regime_state_on_startup(self):
        """
        Herstelt de laatst-bekende regimestatus (LP_MODE/BULLISH_REFLEX/
        BEARISH_REFLEX) bij het opstarten (27 aug 2026) -- lost een reeel,
        empirisch waargenomen probleem op: current_regime viel bij ELKE
        herstart terug op de default LP_MODE, ongeacht de daadwerkelijke,
        laatst-bekende status. Dit veroorzaakte een onterechte
        vangnet-poging (probeerde een LP-positie te openen terwijl de bot
        legitiem in bullish_reflex zat met kapitaal volledig in HBAR) en
        een misleidende "OVERGANG"-regel in de reflex_episodes-logging.

        In tegenstelling tot de LP-positie is er geen directe on-chain
        manier om "het regime" te verifieren (het is geen on-chain
        toestand, slechts een interne beslissing) -- we vertrouwen hier
        dus op de database. Als de wallet-samenstelling duidelijk niet bij
        de opgeslagen regime past (bv. regime=LP_MODE maar geen LP-positie
        EN geen substantieel USDC-saldo), loggen we een waarschuwing maar
        overschrijven we niets automatisch -- handmatige controle is dan
        verstandiger dan een gok.
        """
        saved = await self.db.get_regime_state()
        if not saved:
            print("[regime] Geen opgeslagen regimestatus gevonden -- start in de default LP_MODE.")
            return

        try:
            self.current_regime = Regime(saved["current_regime"])
        except ValueError:
            print(f"[regime] Onbekende opgeslagen regime-waarde "
                  f"'{saved['current_regime']}' -- blijft op de default LP_MODE.")
            return

        self._active_reflex_episode_id = saved["active_reflex_episode_id"]

        # flash_defense_until inladen (30 aug 2026) -- .get() met een
        # default van 0.0, voor het geval de rij nog van vóór deze
        # kolomtoevoeging dateert (oudere rijen hebben de kolom via de
        # ALTER TABLE-default wel, maar dit is een extra vangnet).
        opgeslagen_flash_defense = saved.get("flash_defense_until") or 0.0
        if opgeslagen_flash_defense > time.time():
            self._flash_defense_until = opgeslagen_flash_defense
            resterend_min = (opgeslagen_flash_defense - time.time()) / 60
            telegram_notify.send_telegram_message(
                f"Herstart tijdens een actieve flash-verdedigingsperiode "
                f"gedetecteerd -- hersteld, nog {resterend_min:.1f} minuten te gaan."
            )

        if self.current_regime == Regime.BEARISH_REFLEX and saved["trailing_entry_price"]:
            self.bearish_tracker = BearishTrailingStopTracker(saved["trailing_entry_price"], TRAILING_STOP_PCT)
        if self.current_regime == Regime.BULLISH_REFLEX and saved["trailing_entry_price"]:
            self.trailing_tracker = TrailingStopTracker(
                entry_price=saved["trailing_entry_price"], trailing_distance_pct=TRAILING_STOP_PCT,
                initial_stop_loss=saved["trailing_entry_price"] * (1 - TRAILING_STOP_PCT),
            )

        print(f"[regime] Regimestatus hersteld na herstart: {self.current_regime.value} "
              f"(reflex-episode-id={self._active_reflex_episode_id})")

        # Telegram-melding (27 aug 2026) -- zonder dit is een herstart die
        # de status correct herstelt volledig stil, wat na een eerdere
        # foutmelding onnodig onzekerheid kan geven of alles goed is gegaan.
        if self.current_regime != Regime.LP_MODE:
            telegram_notify.send_telegram_message(
                f"Bot herstart -- regimestatus correct hersteld: "
                f"{self.current_regime.value}. Geen ongewenste actie ondernomen."
            )

    async def _refresh_volatility_regime_if_due(self):
        """
        Werkt self._cached_volatility_regime bij (26 aug 2026, herzien
        27 aug 2026) -- was voorheen altijd de default NORMAL, nooit
        daadwerkelijk aan live data gekoppeld. Draait elke paar uur, niet
        elke cyclus (zie VOLATILITY_REGIME_REFRESH_SECONDS).

        HERZIEN (27 aug 2026): gebruikt nu select_optimal_volatility_regime()
        i.p.v. compute_volatility_regime() -- die laatste keek ALLEEN naar
        marktvolatiliteit, deze houdt ook rekening met de economie
        (kapitaalgrootte vs. herbalancerings-kosten vs. verwachte
        fee-opbrengst). Empirisch bevestigd via backtest: bij klein
        kapitaal wint een bredere range, bij groter kapitaal een smallere
        -- een vaste, alleen-op-volatiliteit-gebaseerde keuze miste dit
        volledig.
        """
        if (time.time() - self._last_volatility_refresh) < VOLATILITY_REGIME_REFRESH_SECONDS:
            return

        try:
            # 1000 uur (~41,7 dagen, Binance's maximum per aanroep) i.p.v.
            # 48 uur (27 aug 2026) -- een kort venster kan toevallig 0
            # herbalanceringen op ALLE breedtes laten zien (bv. een
            # rustige periode), waardoor de economische afweging triviaal
            # altijd LOW kiest (hoogste fee-schatting, kosten overal nul)
            # ongeacht kapitaalgrootte -- empirisch waargenomen bij de
            # eerste live-poging. Een langer venster geeft een
            # statistisch betekenisvollere schatting van de daadwerkelijke
            # herbalancerings-frequentie.
            klines = self.binance_klines.get_klines("HBAR", interval="1h", limit=1000)
            closes = [k.close for k in klines]
            capital_hbar = self.rpc_client.get_hbar_balance() if self.rpc_client else 0.0
            self._cached_volatility_regime = select_optimal_volatility_regime(
                closes, float(capital_hbar)
            )

            # Echte, gemeten uurvolatiliteit cachen (28 aug 2026, voor het
            # GBM-range-model) -- zelfde berekening als compute_volatility_
            # regime() intern gebruikt, hier apart bewaard zodat we 'm
            # rechtstreeks kunnen gebruiken zonder een dubbele Binance-aanroep.
            import statistics
            hourly_returns = [
                (closes[i] - closes[i - 1]) / closes[i - 1]
                for i in range(1, len(closes)) if closes[i - 1] != 0
            ]
            if len(hourly_returns) >= 3:
                self._cached_hourly_volatility = statistics.pstdev(hourly_returns)

            # Macro-regimedetectie (28 aug 2026, op verzoek) -- hergebruikt
            # dezelfde, al-opgehaalde closes-data, geen extra Binance-
            # aanroep nodig. We hebben hier ~41,7 dagen data (Binance's
            # maximum per aanroep), dus lookback_days=30 gebruikt bijna
            # de volledige beschikbare reeks.
            from macro_regime_model import detect_macro_regime
            macro_result = detect_macro_regime(closes, lookback_days=30)
            oude_macro_regime = self._cached_macro_regime
            self._cached_macro_regime = macro_result.regime.value
            # (8 sep 2026) Meerlaagse macro-analyse in SCHADUWMODUS: alleen
            # loggen naast het oude 30d-momentum; beslist nog niets.
            try:
                from macro_analysis import compute_macro_analysis, format_log_line
                _m = compute_macro_analysis(self.binance_klines, current_bot_regime=self._cached_macro_regime)
                print(format_log_line(_m))
            except Exception as e:
                print(f"[macro] schaduw-analyse niet beschikbaar: {str(e)[:120]}")

            if oude_macro_regime is not None and self._cached_macro_regime != oude_macro_regime:
                telegram_notify.send_telegram_message(
                    f"Macro-regime gewijzigd: {oude_macro_regime} -> "
                    f"{self._cached_macro_regime} (momentum={macro_result.momentum_pct*100:+.1f}% "
                    f"over 30 dagen). Dit beinvloedt vanaf nu de asymmetrie van nieuwe LP-ranges."
                )

            print(f"[regime] Volatiliteitsregime bijgewerkt (economisch-bewust): "
                  f"{self._cached_volatility_regime.value} (kapitaal={capital_hbar:.2f} HBAR), "
                  f"gemeten uurvolatiliteit={self._cached_hourly_volatility*100:.4f}%, "
                  f"macro-regime={self._cached_macro_regime} "
                  f"(momentum={macro_result.momentum_pct*100:+.1f}% over 30 dagen)")
        except Exception as e:
            telegram_notify.report_error("regime_loop: volatiliteitsregime verversen", str(e))
            # self._cached_volatility_regime blijft op de vorige waarde staan

        self._last_volatility_refresh = time.time()

    async def _trigger_flash_defense(self, asset: str, flash_result) -> None:
        """
        Reageert op een gedetecteerde flash-event (28 aug 2026): sluit de
        LP-positie onmiddellijk (indien open) en activeert de
        verdedigingsperiode -- het doel verschuift van "fees verdienen"
        naar "kapitaalbehoud" totdat de volatiliteit is gaan liggen.

        Gebruikt hetzelfde, vandaag beproefde patroon voor het veilig
        sluiten (on-chain-verificatie na een eventuele mislukking, zie
        _rebalance_if_out_of_range() voor het origineel).
        """
        # Bericht op maat van het triggertype (30 aug 2026, na toevoeging
        # van de prijs-gebaseerde detectie hierboven) -- "asset" bevat nu
        # ofwel een asset-naam (BTC/HBAR, sentiment-trigger) ofwel de
        # tekst "PRIJS (...)" (prijs-trigger), en het bericht past zich
        # daarop aan zodat het altijd correct leesbaar blijft.
        if asset.startswith("PRIJS"):
            detail_regel = f"Directe koersbeweging: {asset}."
        else:
            detail_regel = (
                f"Sentiment-sprong {flash_result.delta_sentiment:+.2f} binnen een "
                f"verversing, confidence={flash_result.confidence:.2f} (onder de drempel)."
            )

        telegram_notify.send_telegram_message(
            f"FLASH-EVENT GEDETECTEERD ({asset}): {detail_regel} "
            f"Verdedigingsmodus geactiveerd voor "
            f"{self.flash_defense_duration_seconds/60:.0f} minuten -- "
            f"LP-positie wordt (indien open) direct gesloten."
        )

        self._flash_defense_until = time.time() + self.flash_defense_duration_seconds

        # Direct persisteren (30 aug 2026) -- flash-verdediging gaat niet
        # via het normale overgangs-pad (dat al elders self.db.save_
        # regime_state() aanroept), dus zonder deze expliciete aanroep
        # zou een herstart TIJDENS een actieve verdedigingsperiode dit
        # vergeten en het vangnet meteen weer (te vroeg) kunnen laten
        # heropenen.
        trailing_entry_price = (self.trailing_tracker.entry_price if self.trailing_tracker else (self.bearish_tracker.entry_price if self.bearish_tracker else None))
        await self.db.save_regime_state(
            self.current_regime.value, trailing_entry_price, self._active_reflex_episode_id,
            self._flash_defense_until,
        )

        if not self.lp_manager or not self.lp_manager.state.is_open:
            return

        token_id = self.lp_manager.state.token_id
        try:
            self.lp_manager.close_position(token_id)
            await self.db.clear_active_lp_position()
            # Reset (28 aug 2026, gevonden bij nazoeken, nu structureel
            # opgelost via de tijd-gebaseerde cooldown hierboven i.p.v.
            # een aparte, handmatige reset per sluitings-oorzaak): het
            # vangnet mag dit meteen weer proberen zodra de verdediging
            # eindigt, niet pas na de volledige cooldown-periode.
            self._last_safetynet_attempt_at = 0.0
            telegram_notify.send_telegram_message(
                f"Flash-verdediging: LP-positie {token_id} succesvol gesloten."
            )
        except Exception as e:
            # Zelfde veilige verificatie-patroon als elders (28 aug 2026)
            try:
                position = self.lp_manager.position_manager.functions.positions(token_id).call()
                still_open = position[5] > 0
            except Exception:
                still_open = None

            if still_open is False:
                self.lp_manager.state.is_open = False
                await self.db.clear_active_lp_position()
                self._last_safetynet_attempt_at = 0.0  # zelfde bugfix als hierboven

                recovered_msg = ""
                try:
                    recovered = self.lp_manager.check_and_recover_stuck_whbar()
                    if recovered > 0:
                        recovered_msg = (
                            f" Tevens {recovered:.4f} vastzittende WHBAR "
                            f"gevonden en hersteld naar native HBAR."
                        )
                except Exception:
                    pass  # niet kritiek -- de eerstvolgende opstart-check dekt dit ook af

                telegram_notify.send_telegram_message(
                    f"Flash-verdediging: sluiten leek te falen ({e}), maar "
                    f"on-chain verificatie bevestigt dat positie {token_id} "
                    f"daadwerkelijk gesloten is.{recovered_msg}"
                )
            else:
                telegram_notify.report_error(
                    "regime_loop: flash-verdediging sluiten",
                    f"{e} -- KRITIEK: kon LP-positie {token_id} niet bevestigd "
                    f"sluiten tijdens een gedetecteerde flash-event. "
                    f"HANDMATIGE CONTROLE DRINGEND VEREIST.",
                )

    async def _verwerk_macro_nieuws(self):
        items = self.rss_news.fetch_news("MACRO", max_age_hours=4.0)
        nieuw = [i for i in items if i.id not in self._processed_news_ids]
        if not nieuw:
            return
        try:
            bekend = {normalize_headline(h) for h in await self.db.recent_headlines(24.0)}
        except Exception:
            bekend = set()
        try:
            async with self.db._pool.acquire() as conn:
                rows = await conn.fetch("SELECT headline_key FROM news_events WHERE created_at > now() - interval '48 hours'")
            bekend |= {r["headline_key"] for r in rows}
        except Exception:
            pass
        gezien, bewaard, gezien_n = set(), 0, 0
        for i in nieuw:
            self._processed_news_ids.add(i.id)
            sleutel = normalize_headline(i.title)
            if not sleutel or sleutel in bekend or sleutel in gezien:
                continue
            gezien.add(sleutel)
            gezien_n += 1
            if gezien_n > MACRO_MAX_PER_REFRESH:
                break
            cls = self.llm.classify_headline("MACRO", i.title)
            if cls is None or cls.magnitude_guess < MACRO_MIN_MAGNITUDE:
                continue
            await self.db.log_news_event(
                asset="MACRO", headline=i.title, headline_key=sleutel, published_at=i.published_at,
                source_feed=i.source_feed, url=i.url, category=cls.category, entity=cls.entity,
                novelty=cls.novelty, magnitude_guess=cls.magnitude_guess, event_key=cls.event_key,
                rationale=cls.rationale,
            )
            bewaard += 1
            print(f"[nieuws] MACRO: {cls.category}/{cls.novelty} m={cls.magnitude_guess} [{cls.event_key}] {i.title[:60]}")
        if gezien_n:
            print(f"[nieuws] MACRO: {gezien_n} nieuwe koppen beoordeeld, {bewaard} relevant bewaard.")

    async def _refresh_sentiment_if_due(self):
        if (time.time() - self._last_sentiment_refresh) < SENTIMENT_REFRESH_SECONDS:
            return

        # ALGEMEEN NIEUWS (10 sep 2026): aparte tak -- alleen classificeren
        # en bewaren (news_events), geen richtingsscore, geen invloed op de
        # regime-beslissing. Alleen koppen met omvang >= MACRO_MIN_MAGNITUDE
        # worden opgeslagen; de rest is voor de markt niet relevant.
        try:
            await self._verwerk_macro_nieuws()
        except Exception as e:
            print(f"[nieuws] MACRO-tak mislukt (niet kritiek): {e}")

        for asset in ("BTC", "HBAR"):
            items = self.rss_news.fetch_news(asset, max_age_hours=4.0)
            # Messari's News API uitgeschakeld (27 aug 2026) -- vereist een
            # betaald abonnement-tier dat momenteel niet actief is (401/403
            # bevestigd, geen codefout). Regel hieronder simpelweg
            # uncommenten zodra dat wel het geval is -- de client zelf is
            # al volledig af en getest tegen de echte, gedocumenteerde
            # Messari-API-structuur.
            # items += self.messari_news.fetch_news(asset, max_age_hours=4.0)
            new_items = [i for i in items if i.id not in self._processed_news_ids]
            # ONTDUBBELING over herstarts en bronnen heen (10 sep 2026):
            # sentiment_log van de laatste 24u is de waarheid, niet de
            # in-memory set. Zelfde kop via een andere link (Google News
            # vs. CoinDesk) of na een herstart wordt niet opnieuw gescoord
            # en telt dus niet dubbel mee in de combined score.
            try:
                bekend = {normalize_headline(h) for h in await self.db.recent_headlines(24.0)}
            except Exception as e:
                print(f"[nieuws] Ontdubbeling via sentiment_log mislukt ({e}) -- alleen in-memory set gebruikt.")
                bekend = set()
            uniek, gezien = [], set()
            for i in new_items:
                sleutel = normalize_headline(i.title)
                if not sleutel or sleutel in bekend or sleutel in gezien:
                    self._processed_news_ids.add(i.id)
                    continue
                gezien.add(sleutel)
                uniek.append(i)
            if len(uniek) < len(new_items):
                print(f"[nieuws] {asset}: {len(new_items) - len(uniek)} dubbele headline(s) overgeslagen.")
            new_items = uniek
            if not new_items:
                continue

            results = [self.llm.analyze_headline(asset, i.title) for i in new_items]
            timestamps = [i.published_at for i in new_items]

            # FASE 1 nieuws/macro-plan (10 sep 2026): elke unieke kop óók
            # classificeren (categorie/entiteit/nieuwheid/omvang/event_key,
            # géén richting) en opslaan in news_events. De event-study-cron
            # voegt daar later de markt-labels aan toe. Faalt stil.
            for item in new_items:
                cls = self.llm.classify_headline(asset, item.title)
                if cls is None:
                    continue
                try:
                    await self.db.log_news_event(
                        asset=asset, headline=item.title, headline_key=normalize_headline(item.title),
                        published_at=item.published_at, source_feed=item.source_feed, url=item.url,
                        category=cls.category, entity=cls.entity, novelty=cls.novelty,
                        magnitude_guess=cls.magnitude_guess, event_key=cls.event_key, rationale=cls.rationale,
                    )
                    print(f"[nieuws] {asset}: {cls.category}/{cls.novelty} m={cls.magnitude_guess} [{cls.event_key}] {item.title[:60]}")
                except Exception as e:
                    print(f"[nieuws] news_events schrijven mislukt: {e}")

            # Gedifferentieerde halfwaardetijd per asset (28 aug 2026, op
            # verzoek): BTC is een large-cap met snelle, liquide
            # prijsvorming -- nieuws wordt binnen 1-2u grotendeels
            # ingeprijsd. HBAR is een kleinere-cap met tragere
            # informatieverwerking -- nieuws blijft langer relevant.
            # AANNAME, geen empirisch geijkte waarde -- instelbaar hier.
            half_life = SENTIMENT_HALF_LIFE_HOURS_BY_ASSET.get(asset, 1.5)

            score = LlmSentimentEngine.aggregate_with_decay(results, timestamps, half_life_hours=half_life)
            # BIAS-CORRECTIE (10 sep 2026, kalibratie): de LLM scoort
            # structureel positief (30d-gemiddelde BTC +0,17, HBAR +0,27 in
            # een dalende markt), waardoor "neutraal" in de bot feitelijk
            # bullish was. Recentreren op het gemeten gemiddelde, zodat 0
            # weer 0 is. Waarden herijken na de volgende kalibratierun;
            # instelbaar via SENTIMENT_BIAS_BTC / SENTIMENT_BIAS_HBAR.
            score -= SENTIMENT_BIAS_BY_ASSET.get(asset, 0.0)
            volatility_sigma = LlmSentimentEngine.aggregate_volatility_with_decay(
                results, timestamps, half_life_hours=half_life
            )

            # KRITIEK: elke losse headline-score loggen naar sentiment_log --
            # zonder dit heeft recalibrate_from_live_history.py (de nachtelijke
            # zelf-herkalibratie) niets meer om uit te putten, aangezien
            # TradingOrchestrator (die dit voorheen deed) niet meer draait.
            for item, result in zip(new_items, results):
                await self.db.log_sentiment(
                    asset=asset, headline=item.title,
                    sentiment_score=result.sentiment_score,
                    confidence=result.confidence,
                    is_idiosyncratic=result.is_idiosyncratic,
                    rationale=result.rationale, source="llm",
                    volatility_sigma=result.volatility_sigma,
                )

            if asset == "BTC":
                previous_score = self._previous_btc_score
                self._previous_btc_score = score  # voor de VOLGENDE verversing
            else:
                previous_score = self._previous_hbar_score
                self._previous_hbar_score = score

            confidence_now = LlmSentimentEngine.aggregate_confidence_with_decay(results, timestamps)
            flash_result = detect_flash_event(previous_score, score, confidence_now)
            if flash_result.is_flash_event:
                # Vastleggen voor latere mean-reversion-detectie (30 aug
                # 2026) -- VOORDAT _trigger_flash_defense() wordt
                # aangeroepen, zodat deze twee waarden meteen klaarstaan
                # voor de eerstvolgende verversing.
                self._mean_reversion_pre_event_score[asset] = previous_score
                self._mean_reversion_event_score[asset] = score
                await self._trigger_flash_defense(asset, flash_result)
            elif asset in self._mean_reversion_event_score and self._flash_defense_until > time.time():
                # Geen NIEUWE flash-event, maar we zitten nog in een
                # actieve verdedigingsperiode van een EERDERE event voor
                # DEZE asset -- controleer of dit een overreactie bleek.
                from flash_event_model import detect_mean_reversion
                reversion_result = detect_mean_reversion(
                    self._mean_reversion_pre_event_score[asset],
                    self._mean_reversion_event_score[asset],
                    score,
                )
                if reversion_result.is_mean_reversion:
                    resterend_min = (self._flash_defense_until - time.time()) / 60
                    self._flash_defense_until = time.time()  # verdediging direct beeindigen
                    trailing_entry_price = (self.trailing_tracker.entry_price if self.trailing_tracker else (self.bearish_tracker.entry_price if self.bearish_tracker else None))
                    await self.db.save_regime_state(
                        self.current_regime.value, trailing_entry_price,
                        self._active_reflex_episode_id, self._flash_defense_until,
                    )
                    telegram_notify.send_telegram_message(
                        f"Mean-reversion gedetecteerd ({asset}): sentiment is voor "
                        f"{reversion_result.reversion_fraction*100:.0f}% teruggekeerd naar het "
                        f"niveau van vóór de flash-event -- lijkt een overreactie te zijn "
                        f"geweest. Verdedigingsperiode direct beeindigd "
                        f"({resterend_min:.1f} min eerder dan gepland), normale werking hervat."
                    )
                    del self._mean_reversion_event_score[asset]
                    del self._mean_reversion_pre_event_score[asset]

            if asset == "BTC":
                self._cached_btc_score = score
                self._cached_btc_volatility_sigma = volatility_sigma
            else:
                self._cached_hbar_score = score
                self._cached_hbar_volatility_sigma = volatility_sigma

            for i in new_items:
                self._processed_news_ids.add(i.id)

        self._last_sentiment_refresh = time.time()

    def _determine_gbm_confidence_level(self, combined_score: float) -> float:
        """
        Stateful, hysterese-versie van determine_gbm_confidence_level_
        stateless() hierboven (30 aug 2026, op verzoek) -- voorkomt dat
        de bot bij een schommelend signaal (bv. rond 0.30) elke cyclus
        heen-en-weer wisselt tussen normale en gematigde-zone-breedte,
        wat onnodige gas-kosten zou opleveren.

        Instappen (normaal -> gematigd) bij MODERATE_SENTIMENT_THRESHOLD
        (0.30), maar pas weer UITSTAPPEN (gematigd -> normaal) bij
        MODERATE_ZONE_EXIT_THRESHOLD (0.20, lager) -- tussen deze twee
        drempels in blijft de bot gewoon in zijn HUIDIGE modus, ongeacht
        welke kant het signaal op schommelt.
        """
        score_abs = abs(combined_score)

        if self._in_moderate_zone:
            if score_abs < MODERATE_ZONE_EXIT_THRESHOLD:
                self._in_moderate_zone = False
        else:
            if score_abs >= MODERATE_SENTIMENT_THRESHOLD:
                self._in_moderate_zone = True

        return MODERATE_ZONE_CONFIDENCE_LEVEL if self._in_moderate_zone else 0.80

    def _determine_target_regime(self, combined_score: float) -> Regime:
        """
        Hysterese toegevoegd (30 aug 2026, op verzoek) -- gebruikt
        self.current_regime als geheugen (geen nieuwe status-variabele
        nodig): instappen in een reflex-regime gebeurt bij
        REGIME_THRESHOLD, maar zodra de bot AL in die reflex-regime zit,
        wordt pas bij de lagere REGIME_THRESHOLD_EXIT weer teruggegaan
        naar lp_mode. Voorkomt dat target_regime bij een schommelend
        signaal rond 0.55 heen-en-weer wisselt.
        """
        if self.current_regime == Regime.BULLISH_REFLEX:
            if combined_score < REGIME_THRESHOLD_EXIT:
                return Regime.LP_MODE
            return Regime.BULLISH_REFLEX
        elif self.current_regime == Regime.BEARISH_REFLEX:
            if combined_score > -REGIME_THRESHOLD_EXIT:
                return Regime.LP_MODE
            return Regime.BEARISH_REFLEX
        else:  # LP_MODE
            if combined_score >= REGIME_THRESHOLD:
                return Regime.BULLISH_REFLEX
            elif combined_score <= -REGIME_THRESHOLD:
                return Regime.BEARISH_REFLEX
            return Regime.LP_MODE

    def _check_market_confirmed_reflex_exit(self, current_price: float) -> tuple:
        """
        NIEUW (3 sep 2026, HERZIEN op verzoek met een bevestigingsstap):
        controleert of de MARKT zelf (los van de sentiment-score)
        aangeeft dat een reflex-uitstap voorbij is -- ofwel via een
        terugval vanaf de piek/dal sinds de uitstap, ofwel via een
        periode van zijwaartse consolidatie. Beide zijn RUWE triggers --
        zodra er EEN actief wordt, moet die nog reflex_exit_
        confirmation_seconds (default 30 min) ONONDERBROKEN blijven
        gelden vóórdat daadwerkelijk teruggekeerd wordt. Voorkomt dat een
        kortstondige terugval of toevallige stilstand direct tot actie
        leidt.

        Drempels (samen met de gebruiker bepaald, 3 sep 2026, AANNAMES,
        geen empirisch geijkte waarden):
        - reflex_pullback_threshold_pct (default 1%): terugval vanaf het
          extreem (piek bij bullish, dal bij bearish) sinds de uitstap.
        - reflex_sideways_band_pct (default 1%) gedurende
          reflex_sideways_duration_seconds (default 30 min, HERZIEN van
          1 uur): de koers is binnen deze bandbreedte gebleven -- ruim
          boven HBAR's normale uurvolatiliteit (~0,6%, empirisch
          gemeten), zodat gewone marktruis niet als "gestabiliseerd"
          telt.
        - reflex_exit_confirmation_seconds (default 30 min): hoe lang een
          RUWE trigger ononderbroken moet blijven gelden vóór actie.

        Reset alle interne tracking (inclusief de bevestigingsperiode)
        zodra we NIET in een reflex-regime zitten, EN annuleert een
        lopende bevestiging zodra de onderliggende, ruwe conditie niet
        meer geldt (bv. de koers herstelt weer boven de terugval-drempel
        tijdens het wachten).

        Geeft (bool, str) terug: of de voorwaarde BEVESTIGD gehaald is
        (dus mag NU teruggekeerd worden), en een leesbare reden.
        """
        if self.current_regime not in (Regime.BULLISH_REFLEX, Regime.BEARISH_REFLEX):
            self._reflex_extreme_price = None
            self._reflex_price_history = []
            self._reflex_entered_at = None
            self._reflex_exit_pending_since = None
            self._reflex_exit_pending_reason = ""
            return False, ""

        nu = time.time()
        if self._reflex_entered_at is None:
            self._reflex_entered_at = nu
        if self._reflex_extreme_price is None:
            self._reflex_extreme_price = current_price
        elif self.current_regime == Regime.BULLISH_REFLEX:
            self._reflex_extreme_price = max(self._reflex_extreme_price, current_price)
        else:  # BEARISH_REFLEX
            self._reflex_extreme_price = min(self._reflex_extreme_price, current_price)

        self._reflex_price_history.append((nu, current_price))
        afsnijpunt = nu - self.reflex_sideways_duration_seconds
        self._reflex_price_history = [
            (t, p) for t, p in self._reflex_price_history if t >= afsnijpunt
        ]

        # Ruwe (nog niet bevestigde) triggers bepalen -- terugval-route.
        if self.current_regime == Regime.BULLISH_REFLEX:
            terugval_pct = (self._reflex_extreme_price - current_price) / self._reflex_extreme_price
        else:
            terugval_pct = (current_price - self._reflex_extreme_price) / self._reflex_extreme_price
        ruwe_terugval = terugval_pct >= self.reflex_pullback_threshold_pct
        terugval_reden = (
            f"{terugval_pct*100:.1f}% teruggevallen vanaf het extreem "
            f"({self._reflex_extreme_price:.5f}) sinds de uitstap"
        )

        # Ruwe (nog niet bevestigde) trigger -- zijwaarts-route. Alleen
        # relevant als we al minstens de volledige duur in reflex-modus
        # zitten, anders is de prijsgeschiedenis nog te kort.
        ruwe_zijwaarts = False
        zijwaarts_reden = ""
        if (nu - self._reflex_entered_at) >= self.reflex_sideways_duration_seconds:
            prijzen = [p for _, p in self._reflex_price_history]
            if prijzen:
                bandbreedte_pct = (max(prijzen) - min(prijzen)) / min(prijzen)
                if bandbreedte_pct <= self.reflex_sideways_band_pct:
                    ruwe_zijwaarts = True
                    zijwaarts_reden = (
                        f"{self.reflex_sideways_duration_seconds/60:.0f} min zijwaarts gebleven "
                        f"(binnen {bandbreedte_pct*100:.2f}%)"
                    )

        ruwe_trigger = ruwe_terugval or ruwe_zijwaarts
        ruwe_reden = terugval_reden if ruwe_terugval else zijwaarts_reden

        if not ruwe_trigger:
            # Geen van beide condities is momenteel actief -- een eventueel
            # lopende bevestigingsperiode annuleren (de markt is niet
            # aanhoudend genoeg gekalmeerd/teruggevallen).
            self._reflex_exit_pending_since = None
            self._reflex_exit_pending_reason = ""
            return False, ""

        if self._reflex_exit_pending_since is None:
            self._reflex_exit_pending_since = nu
            self._reflex_exit_pending_reason = ruwe_reden
            print(f"[regime] Ruwe markt-trigger gedetecteerd tijdens {self.current_regime.value}: "
                  f"{ruwe_reden} -- bevestigingsperiode van "
                  f"{self.reflex_exit_confirmation_seconds/60:.0f} min gestart.")
            return False, ""

        if (nu - self._reflex_exit_pending_since) < self.reflex_exit_confirmation_seconds:
            return False, ""  # nog binnen de bevestigingsperiode

        return True, (
            f"{self._reflex_exit_pending_reason} "
            f"(bevestigd na {self.reflex_exit_confirmation_seconds/60:.0f} min ononderbroken)"
        )

    async def _cycle(self):
        self._balance_fetch_failed_this_cycle = False  # opnieuw resetten bij elke cyclus
        await self._refresh_sentiment_if_due()
        await self._refresh_volatility_regime_if_due()
        combined_score = compute_fixed_combined_score(self._cached_btc_score, self._cached_hbar_score)

        try:
            pool_snapshot = self.geckoterminal.get_pool_snapshot()
            current_price = pool_snapshot.price_usd
        except Exception as e:
            telegram_notify.report_error("regime_loop: prijs ophalen", str(e))
            return

        # (8 sep 2026) USDC-depeg-noodstop: overrulet alle regimes.
        if self.current_regime == Regime.DEPEG_HALT:
            print("[depeg] DEPEG_HALT actief -- 100% HBAR, wacht op /resume.")
            return
        await self._check_depeg(current_price)
        if self.current_regime == Regime.DEPEG_HALT:
            return

        # Live Fees-APR berekenen (30 aug 2026, op verzoek) -- puur
        # INFORMATIEF/LOGGEND voor nu, nog niet gekoppeld aan een
        # daadwerkelijke beslissing (bewust, stapsgewijze aanpak). Kost
        # GEEN extra API-aanroep: volume_24h_usd en liquidity_usd zaten
        # al in de snapshot die hierboven toch al voor de prijs werd
        # opgehaald, maar werden voorheen genegeerd. l_bal gebruikt
        # de pool's TOTALE liquiditeit als benadering (SaucerSwap's
        # eigen, gedocumenteerde vereenvoudiging) -- geeft dus de
        # GEMIDDELDE APR over de volle range, niet specifiek onze eigen,
        # geconcentreerde positie (die doorgaans hoger ligt).
        from lp_manager import compute_fees_apr
        self._cached_pool_fees_apr = compute_fees_apr(
            pool_snapshot.volume_24h_usd, self.lp_manager.config.fee_tier if self.lp_manager else 3000,
            pool_snapshot.liquidity_usd,
        )
        print(f"[regime] Live pool-APR (gemiddeld, hele range): {self._cached_pool_fees_apr*100:.1f}% "
              f"(24u-volume=${pool_snapshot.volume_24h_usd:,.0f}, liquiditeit=${pool_snapshot.liquidity_usd:,.0f})")
        # (7 sep 2026) Nauwkeurige Fees-APR met SaucerSwap's "balanced
        # range"-noemer + LARI-schatting, on-chain (max. elke 10 min --
        # kost een handvol eth_calls). Vervangt de pool-brede benadering
        # hierboven als bron voor beslissingen zodra beschikbaar.
        if self.lp_manager and (time.time() - getattr(self, "_pool_metrics_at", 0.0)) > 600:
            try:
                from pool_range_analysis import compute_pool_metrics
                from lp_manager import DEFAULT_TICK_SPACING_BY_FEE
                cfg = self.lp_manager.config
                quote = cfg.token1 if cfg.token0.lower() == cfg.whbar_address.lower() else cfg.token0
                quote_dec = cfg.token1_decimals if cfg.token0.lower() == cfg.whbar_address.lower() else cfg.token0_decimals
                st = self.lp_manager.state
                our_L = 0
                if st.is_open and st.token_id is not None:
                    try:
                        our_L = int(self.lp_manager.position_manager.functions.positions(st.token_id).call()[5])
                    except Exception:
                        our_L = 0
                pm = compute_pool_metrics(
                    self.rpc_client.w3, cfg.factory_address, cfg.whbar_address, quote, cfg.fee_tier,
                    DEFAULT_TICK_SPACING_BY_FEE.get(cfg.fee_tier, 30), quote_dec,
                    current_price, (1.0 if HEDERA_NETWORK == "mainnet" else current_price),
                    pool_snapshot.volume_24h_usd,
                    volume_1h_usd=getattr(pool_snapshot, "volume_1h_usd", 0.0),
                    volume_7d_avg_usd=self.geckoterminal.get_avg_daily_volume_7d(),
                    our_liquidity=our_L,
                    our_tick_lower=st.tick_lower if st.is_open else None,
                    our_tick_upper=st.tick_upper if st.is_open else None,
                    position_value_usd=0.0,
                )
                self._pool_metrics_at = time.time()
                if os.environ.get("FEES_APR_SOURCE", "pool") == "balanced":
                    self._cached_pool_fees_apr = pm["fees_apr_balanced"]
                lari = pm["lari"]
                _now = f"{pm['fees_apr_now']*100:.1f}%" if pm.get('fees_apr_now') is not None else "n/b"
                _7d = f"{pm['fees_apr_7d']*100:.1f}%" if pm.get('fees_apr_7d') is not None else "n/b"
                print(f"[regime] Fees-APR (balanced range +-{pm['range_ticks'][1]-pm['tick_current']} ticks, "
                      f"TVL in venster=${pm['tvl_in_range_usd']:,.0f}): nu {_now} | 24u {pm['fees_apr_balanced']*100:.1f}% | "
                      f"7d {_7d}"
                      + (f" | LARI pool-APR {lari.pool_reward_apr*100:.1f}%, ons L-aandeel {lari.our_liquidity_share*100:.3f}%"
                         f" ≈ ${lari.our_reward_per_epoch_usd:.2f}/epoch" if lari else ""))
            except Exception as e:
                print(f"[regime] balanced-range APR niet beschikbaar ({str(e)[:100]}) -- pool-brede APR blijft in gebruik")

        # Snelle, prijs-gebaseerde flash-detectie (30 aug 2026, op
        # aangeleverde feedback) -- de sentiment-gebaseerde flash-
        # detectie (elders, elke 5 minuten) reageert te traag: vaak
        # crasht de prijs EERST, en volgt het nieuws pas 2-10 minuten
        # later. Deze check vergelijkt de prijs met die van de VORIGE
        # cyclus (60s geleden) en reageert DIRECT bij een te grote
        # beweging, zonder op sentiment te wachten.
        if self._previous_cycle_price is not None and self._previous_cycle_price > 0:
            prijs_verandering = abs(current_price - self._previous_cycle_price) / self._previous_cycle_price
            if prijs_verandering > PRICE_DELTA_FLASH_THRESHOLD:
                from flash_event_model import FlashEventResult
                prijs_flash_result = FlashEventResult(
                    is_flash_event=True,
                    delta_sentiment=0.0,  # niet van toepassing, dit is een prijs-trigger, geen sentiment-sprong
                    confidence=1.0,  # de prijsbeweging zelf is de zekerheid, geen LLM-inschatting
                )
                await self._trigger_flash_defense(
                    f"PRIJS ({prijs_verandering*100:.1f}% binnen 60s)", prijs_flash_result
                )
        self._previous_cycle_price = current_price

        # Flash-verdedigingsperiode (28 aug 2026, herzien na nazoeken) --
        # als actief, slaat de rest van deze cyclus (herbalanceren,
        # vangnet, regime-overgangen) bewust over. De positie is al
        # gesloten door _trigger_flash_defense() op het moment van
        # detectie -- hier voorkomen we alleen dat de bot tussentijds
        # weer iets opent voordat de volatiliteit is gaan liggen.
        #
        # BEPERKT TOT LP_MODE (bugfix, gevonden bij nazoeken): als de bot
        # al in BULLISH_REFLEX/BEARISH_REFLEX zit, is er geen LP-positie
        # om te beschermen (flash-verdediging deed dan sowieso al niets),
        # en zou deze blokkade de trailing-stop-check hieronder onterecht
        # blokkeren -- precies het mechanisme dat JUIST zou moeten kunnen
        # reageren op een plotselinge crash tijdens BULLISH_REFLEX.
        if self._flash_defense_until > time.time() and self.current_regime == Regime.LP_MODE:
            remaining_min = (self._flash_defense_until - time.time()) / 60
            print(f"[regime] Flash-verdedigingsmodus actief, nog {remaining_min:.1f} min.")
            return

        # Checkt of een bestaande, open positie inmiddels buiten zijn range
        # is gelopen (26 aug 2026) -- los van de vangnet-check hieronder,
        # die alleen checkt OF er iets open staat, niet OF het nog goed
        # gepositioneerd is. Draait elke cyclus, dus ook direct na een
        # herstart (nadat de opstart-reconciliatie een bestaande positie
        # heeft hersteld).
        await self._rebalance_if_out_of_range(current_price)
        # NIEUW (1 sep 2026): regime-drift-check -- reageert AL wanneer
        # het regime zelf substantieel afwijkt van het regime waarmee de
        # positie ooit geopend is, ongeacht of de prijs toevallig nog
        # binnen de (mogelijk te smalle) oude range zit. Zie de volledige
        # toelichting in de functie zelf.
        await self._regime_drift_check(current_price)
        await self._fee_underperformance_check(current_price)

        # Automatisch overtollig kapitaal bijstorten (30 aug 2026, op
        # verzoek) -- WEER AANGEZET (30 aug 2026, zelfde dag) na een
        # eerdere, tijdelijke uitschakeling vanwege een onverklaarde
        # herhaal-loop. De exacte, onderliggende oorzaak is niet
        # gevonden ondanks meerdere onderzochte hypotheses, maar er is
        # nu WEL een harde veiligheidsklem toegevoegd in _ensure_
        # balanced_liquidity_ratio() (nooit meer swappen dan
        # daadwerkelijk in bezit, ongeacht de berekening) plus
        # uitgebreide diagnostische logging -- een eventuele
        # vergelijkbare situatie kan nu niet meer tot een loop leiden,
        # en is bovendien volledig herleidbaar als het zich voordoet.
        await self._deploy_excess_capital_if_available(current_price)

        # VANGNET (26 aug 2026, HERZIEN 3 sep 2026 naar een periodieke,
        # tijd-gebaseerde cooldown i.p.v. een eenmalige vlag): current_regime
        # start standaard op LP_MODE (zie __init__), maar dat betekent NIET
        # automatisch dat er ook daadwerkelijk een LP-positie open staat --
        # open_position() wordt normaal alleen aangeroepen bij een
        # gedetecteerde OVERGANG naar LP_MODE, wat bij het opstarten nooit
        # gebeurt (er is geen vorig regime om vandaan te komen) EN niet bij
        # een positie die later, om welke reden dan ook, sluit zonder
        # succesvolle heropening. Draait nu voortaan PERIODIEK (elke
        # safetynet_retry_cooldown_seconds, standaard 30 minuten) zolang er
        # geen actieve positie is -- kapitaal staat anders nutteloos los in
        # de wallet i.p.v. fees te verdienen, voor onbepaalde tijd.
        print(f"[DEBUG-vangnet] regime={self.current_regime}, lp_manager={self.lp_manager is not None}, is_open={self.lp_manager.state.is_open if self.lp_manager else 'N/A'}, seconds_since={time.time() - self._last_safetynet_attempt_at:.1f}, cooldown={self.safetynet_retry_cooldown_seconds}")
        seconds_since_last_safetynet_attempt = time.time() - self._last_safetynet_attempt_at
        if (self.current_regime == Regime.LP_MODE and self.lp_manager
                and not self.lp_manager.state.is_open
                and seconds_since_last_safetynet_attempt >= self.safetynet_retry_cooldown_seconds):
            self._last_safetynet_attempt_at = time.time()  # ALTIJD zetten, ongeacht succes/falen -- voorkomt een cyclus-lus
            total_hbar_balance = self._get_swappable_hbar_balance(current_price)

            # Reserve = het GROOTSTE van de percentage-gebaseerde marge en de
            # absolute ondergrens (26 aug 2026, op verzoek) -- zodat er bij
            # een kleine positie altijd genoeg HBAR overblijft voor een paar
            # transacties, en bij een grote positie het percentage al genoeg
            # marge geeft zonder onnodig veel HBAR inactief te laten liggen.
            percentage_reserve = total_hbar_balance * (1 - LP_SAFETYNET_DEPLOY_FRACTION)
            reserve_hbar = max(percentage_reserve, LP_SAFETYNET_MIN_RESERVE_HBAR)
            deployable_hbar = max(0.0, total_hbar_balance - reserve_hbar)
            print(f"[DEBUG-vangnet2] total_hbar_balance={total_hbar_balance:.4f}, reserve_hbar={reserve_hbar:.4f}, deployable_hbar={deployable_hbar:.4f}")

            if deployable_hbar > 0:
                from lp_manager import compute_amount1_for_amount0, compute_amount0_for_amount1, get_live_pool_price
                # BUGFIX (30 aug 2026, KRITIEK, empirisch gevonden): gebruikte
                # voorheen current_price (GeckoTerminal's USD-schatting van
                # HBAR, bv. 0.075) rechtstreeks voor de tick-berekening --
                # maar price_to_tick() heeft de POOL'S EIGEN, interne
                # SAUCE-per-HBAR-koers nodig (bv. 51.5), een compleet andere
                # grootheid (SAUCE is op testnet GEEN 1:1 USD-proxy, bleek
                # ~685x kleiner waard). Dit liet positie 348 volledig
                # eenzijdig (100% HBAR) landen. Zelfde fix-patroon als
                # elders al correct toegepast (_rebalance_if_out_of_range()).
                try:
                    fresh_price = get_live_pool_price(
                        self.rpc_client, self.lp_manager.config.factory_address,
                        self.lp_manager.config.token0, self.lp_manager.config.token1,
                        self.lp_manager.config.fee_tier,
                        self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,
                    )
                except Exception:
                    fresh_price = current_price

                # Prijs-orakel-manipulatie-check (30 aug 2026, HERZIEN
                # naar TWAP-gebaseerd) -- vóórdat we op basis van
                # fresh_price een positie gaan openen.
                from lp_manager import price_to_tick
                huidige_tick = price_to_tick(
                    fresh_price, self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,
                )
                if not self._check_price_oracle_divergence(huidige_tick):
                    return  # wacht tot de volgende cyclus, veiligheidsmelding is al verstuurd

                combined_score_now = compute_fixed_combined_score(self._cached_btc_score, self._cached_hbar_score)
                combined_volatility_sigma_now = compute_combined_volatility_sigma(
                    self._cached_btc_volatility_sigma, self._cached_hbar_volatility_sigma
                )
                combined_volatility_sigma_now = min(
                    1.0, combined_volatility_sigma_now * self._volatility_calibration_factor
                )
                combined_score_now = apply_regime_bias(combined_score_now, self._cached_macro_regime)
                tick_lower, tick_upper = self.lp_manager.compute_range_via_gbm(
                    fresh_price, combined_score_now, combined_volatility_sigma_now,
                    self._cached_hourly_volatility,
                    macro_regime=self._cached_macro_regime,
                    confidence_level=self._determine_gbm_confidence_level(combined_score_now),
                )

                # Symmetrische herbalancering (26 aug 2026, vervangt eerdere
                # eenzijdige check) -- respecteert de reserve via
                # max_hbar_to_use.
                # BUGFIX (30 aug 2026): fresh_price i.p.v. current_price --
                # deze functie moet in dezelfde prijsschaal werken als de
                # ticks hierboven (pool-intern, niet GeckoTerminal-USD).
                swap_success = await self._ensure_balanced_liquidity_ratio(
                    fresh_price, tick_lower, tick_upper, max_hbar_to_use=deployable_hbar
                )

                if swap_success:
                    print("[DIAGNOSE-stap] 1: if swap_success: bereikt")
                    hbar_balance = self._get_swappable_hbar_balance(current_price)
                    # Niet meer inzetten dan het inzetbare deel, ook al kan de
                    # totale swappable balans nu toevallig hoger zijn.
                    hbar_balance = min(hbar_balance, deployable_hbar)
                    usdc_balance = self._get_swappable_usdc_balance()

                    from lp_manager import compute_amount1_for_amount0, compute_amount0_for_amount1
                    # Prijs VERVERSEN vlak voor gebruik (26 aug 2026) -- de
                    # current_price (via GeckoTerminal) kan een eigen
                    # indexerings-vertraging hebben t.o.v. de daadwerkelijke,
                    # live pool-staat -- en de pool zelf beoordeelt onze
                    # mint()-transactie altijd tegen ZIJN EIGEN actuele
                    # prijs. Daarom hier de prijs rechtstreeks uit de pool
                    # zelf halen (26 aug 2026, na herhaalde "Price slippage
                    # check"-fouten bij grotere bedragen die niet optraden
                    # bij een kleine test eerder deze week).
                    from lp_manager import get_live_pool_price
                    try:
                        fresh_price = get_live_pool_price(
                            self.rpc_client, self.lp_manager.config.factory_address,
                            self.lp_manager.config.token0, self.lp_manager.config.token1,
                            self.lp_manager.config.fee_tier,
                            self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,
                        )
                    except Exception:
                        fresh_price = current_price  # val terug op de oude prijs als ophalen faalt
                    print(f"[DIAGNOSE-stap] 2: fresh_price ververst = {fresh_price}")
                    combined_score_now = compute_fixed_combined_score(self._cached_btc_score, self._cached_hbar_score)
                    combined_volatility_sigma_now = compute_combined_volatility_sigma(
                        self._cached_btc_volatility_sigma, self._cached_hbar_volatility_sigma
                    )
                    combined_volatility_sigma_now = min(
                        1.0, combined_volatility_sigma_now * self._volatility_calibration_factor
                    )
                    combined_score_now = apply_regime_bias(combined_score_now, self._cached_macro_regime)
                    tick_lower, tick_upper = self.lp_manager.compute_range_via_gbm(
                        fresh_price, combined_score_now, combined_volatility_sigma_now,
                        self._cached_hourly_volatility,
                        macro_regime=self._cached_macro_regime,
                        confidence_level=self._determine_gbm_confidence_level(combined_score_now),
                    )
                    print(f"[DIAGNOSE-stap] 3: range berekend, tick_lower={tick_lower}, tick_upper={tick_upper}")

                    hbar_raw_available = int(hbar_balance * (10 ** self._hbar_decimals))
                    usdc_raw_available = int(usdc_balance * (10 ** self._usdc_decimals))

                    # Zelfde beperkende-kant-logica als voorheen -- na de
                    # herbalancering zou dit meestal HBAR moeten zijn, maar
                    # niet gegarandeerd (bv. bij prijsbeweging tijdens de
                    # swap), dus blijft dit defensief gecheckt.
                    needed_usdc_for_full_hbar = self.lp_manager.compute_needed_usdc_for_hbar(
                        hbar_raw_available, fresh_price, tick_lower, tick_upper,
                    )
                    if needed_usdc_for_full_hbar <= usdc_raw_available:
                        hbar_raw = hbar_raw_available
                        usdc_raw = needed_usdc_for_full_hbar
                    else:
                        usdc_raw = usdc_raw_available
                        hbar_raw = self.lp_manager.compute_needed_hbar_for_usdc(
                            usdc_raw_available, fresh_price, tick_lower, tick_upper,
                        )

                    hbar_to_deploy = hbar_raw / (10 ** self._hbar_decimals)
                    usdc_to_deploy = usdc_raw / (10 ** self._usdc_decimals)
                    print(f"[DIAGNOSE-stap] 4: bedragen berekend, hbar_raw={hbar_raw}, usdc_raw={usdc_raw}")
                    # BUGFIX (6 sep 2026): prijs NOGMAALS verversen, vlak
                    # vóór open_position() zelf -- de swap hierboven (met
                    # wachten op bevestiging) kost echte tijd, waarin de
                    # eerder opgehaalde fresh_price kan zijn verouderd.
                    # SaucerSwap's eigen developer-documentatie (new-
                    # liquidity-position.md) haalt de prijs ÉÉN keer op en
                    # gebruikt die DIRECT, zonder een tijdrovende stap
                    # ertussen -- onze flow moet dat patroon zo dicht
                    # mogelijk benaderen door hier opnieuw te verversen.
                    from lp_manager import get_live_pool_price as _get_live_pool_price_voor_mint
                    try:
                        mint_price = _get_live_pool_price_voor_mint(
                            self.rpc_client, self.lp_manager.config.factory_address,
                            self.lp_manager.config.token0, self.lp_manager.config.token1,
                            self.lp_manager.config.fee_tier,
                            self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,
                        )
                    except Exception:
                        mint_price = fresh_price
                    print(f"[DIAGNOSE-stap] 5: vlak voor open_position(), mint_price={mint_price}")
                    try:
                        self.lp_manager.open_position(
                            hbar_raw, usdc_raw, mint_price, slippage_tolerance=0.25,
                            gas_limit_override=1_200_000,
                            precomputed_tick_range=(tick_lower, tick_upper),
                        )
                        await self.db.save_active_lp_position(
                            self.lp_manager.state.token_id,
                            self.lp_manager.state.tick_lower,
                            self.lp_manager.state.tick_upper,
                        )
                        telegram_notify.send_telegram_message(
                            f"LP-positie geopend (vangnet, na herbalancering, "
                            f"reserve={reserve_hbar:.2f} HBAR achtergehouden): "
                            f"{hbar_to_deploy:.4f} HBAR + {usdc_to_deploy:.2f} {self._quote_label}."
                        )
                    except Exception as e:
                        telegram_notify.report_error(
                            "regime_loop: LP-positie openen (vangnet)",
                            f"{e} -- kapitaal staat los in de wallet. Vangnet probeert NIET automatisch opnieuw (voorkomt herhaal-lus) -- herstart de bot handmatig na controle.",
                        )
                else:
                    # Rustige, informatieve melding (4 sep 2026, op
                    # verzoek na herhaalde vals-alarmerende meldingen
                    # elke ~30 min) -- de balancerings-swap weigerde
                    # HIER vóór enige transactie (dezelfde balanceringsklem
                    # als elders), dus kapitaal is gegarandeerd nog
                    # exact waar het was. Het vangnet probeert dit
                    # vanzelf, periodiek opnieuw (zie de cooldown
                    # hierboven) -- geen HANDMATIGE CONTROLE nodig voor
                    # dit routinematige, veilige geval.
                    print("[regime] Vangnet: herbalancerings-swap nog niet mogelijk -- "
                          "kapitaal onaangeroerd, wordt periodiek opnieuw geprobeerd.")

        target_regime = self._determine_target_regime(combined_score)

        # LAAG 7 event-risico-kalender (10 sep 2026): binnen ±2u van een
        # geplande macro-gebeurtenis (CPI, FOMC, NFP, ETF-besluit) geen
        # NIEUWE reflex-instap -- dat is een gok op het cijfer, niet op het
        # regime. Lopende reflex-posities en trailing-stops blijven
        # ongemoeid; alleen de overgang LP_MODE -> reflex wordt tegengehouden.
        if (self.current_regime == Regime.LP_MODE and target_regime != Regime.LP_MODE
                and self.event_guard is not None):
            if await self.event_guard.blocks_new_reflex_entry(combined_score):
                target_regime = Regime.LP_MODE
        is_profit_take = False
        is_market_confirmed_reentry = False
        market_confirmed_reason = ""

        # Economische poort VERWIJDERD (28 aug 2026 gebouwd, 3 sep 2026 op
        # expliciet verzoek weer verwijderd): woog voorheen af of de
        # volledige heen-en-terug-cyclus (sluiten+swappen, later weer
        # openen+swappen) daadwerkelijk meerwaarde had t.o.v. gewoon in de
        # pool blijven -- maar bleek in de praktijk zelfs een gematigd,
        # geldig signaal (combined_score=0.59) te weigeren puur door een
        # vaste kostenpost die bij voldoende kapitaal verwaarloosbaar is.
        # De gebruiker geeft aan: bij voldoende opstartkapitaal wegen de
        # transactiekosten niet op tegen het risico van gedeeltelijke
        # blootstelling + impermanent loss tijdens een sterke, eenzijdige
        # beweging -- de bestaande drempel-overschrijding (REGIME_THRESHOLD,
        # die al rekening houdt met hoe belangrijk/marktbreed de LLM het
        # nieuws vindt via de gewogen, idiosyncratisch-bewuste score) is nu
        # zelf de enige, voldoende poort. evaluate_reflex_transition_economics()
        # zelf blijft bestaan in gbm_range_model.py (niet verwijderd, voor
        # het geval dit ooit heroverwogen wordt), alleen deze aanroep hier.

        # BUGFIX (3 sep 2026, KRITIEK, gevonden na een gemiste terugval):
        # zowel de trailing-stop hieronder als de nieuwe markt-bevestigde-
        # terugkeer-check gebruikten voorheen current_price (GeckoTerminal),
        # maar GeckoTerminal's data voor DEZE testnet-pool bleek voor
        # langere tijd (30+ minuten) niet te verversen, ook al bewoog de
        # markt daadwerkelijk (bevestigd: rechtstreeks bij GeckoTerminal
        # nagevraagd, gaf nog steeds exact dezelfde, verouderde prijs
        # terug). fresh_price (rechtstreeks van de pool zelf, on-chain)
        # wordt nu gebruikt voor BEIDE checks -- ongevoelig voor
        # GeckoTerminal's eigen verversings-cadans.
        if self.current_regime in (Regime.BULLISH_REFLEX, Regime.BEARISH_REFLEX) and self.lp_manager:
            try:
                from lp_manager import get_live_pool_price
                fresh_reflex_price = get_live_pool_price(
                    self.rpc_client, self.lp_manager.config.factory_address,
                    self.lp_manager.config.token0, self.lp_manager.config.token1,
                    self.lp_manager.config.fee_tier,
                    self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,
                )
                # fresh_reflex_price staat in de POOL-EIGEN, interne
                # SAUCE-per-HBAR-schaal, niet USD -- voor de trailing-stop/
                # markt-bevestigde-terugkeer-checks (die alleen relatieve
                # bewegingen t.o.v. een eerder vastgelegd extreem meten,
                # geen USD-bedragen) is dat prima, zolang het maar
                # consistent dezelfde schaal is doorheen een hele episode.
            except Exception:
                fresh_reflex_price = current_price  # val terug, beter dan crashen
        else:
            fresh_reflex_price = current_price

        import decision_log
        if self.current_regime == Regime.BULLISH_REFLEX and self.trailing_tracker:
            stop_price = self.trailing_tracker.update(fresh_reflex_price)
            if fresh_reflex_price <= stop_price:
                print(f"[regime] Trailing-stop getriggerd tijdens BULLISH_REFLEX "
                      f"(prijs={fresh_reflex_price:.5f} <= stop={stop_price:.5f}) -- winst nemen.")
                target_regime = Regime.LP_MODE
                is_profit_take = True
                decision_log.log("trailing_stop", side="bullish", price=fresh_reflex_price, stop=stop_price,
                                 highest=self.trailing_tracker.highest_price, entry=self.trailing_tracker.entry_price,
                                 pct=TRAILING_STOP_PCT, combined_score=combined_score)
            elif fresh_reflex_price <= stop_price * 1.015:
                decision_log.near_miss("trailing_stop_bullish", price=fresh_reflex_price, stop=stop_price,
                                       highest=self.trailing_tracker.highest_price, combined_score=combined_score)

        # (8 sep 2026) Spiegel: bearish trailing-stop. 100% USDC; stijgt de
        # prijs 5% vanaf het dal (of 5% boven instap), dan is de daling
        # voorbij -> direct terug naar LP. Zelfde cooldown-uitzondering.
        if self.current_regime == Regime.BEARISH_REFLEX and self.bearish_tracker:
            stop_price = self.bearish_tracker.update(fresh_reflex_price)
            if fresh_reflex_price >= stop_price:
                print(f"[regime] Bearish trailing-stop getriggerd tijdens BEARISH_REFLEX "
                      f"(prijs={fresh_reflex_price:.5f} >= stop={stop_price:.5f}) -- daling voorbij, terug naar LP.")
                target_regime = Regime.LP_MODE
                is_profit_take = True
                decision_log.log("trailing_stop", side="bearish", price=fresh_reflex_price, stop=stop_price,
                                 lowest=self.bearish_tracker.lowest_price, entry=self.bearish_tracker.entry_price,
                                 pct=TRAILING_STOP_PCT, combined_score=combined_score)
            elif fresh_reflex_price >= stop_price * 0.985:
                decision_log.near_miss("trailing_stop_bearish", price=fresh_reflex_price, stop=stop_price,
                                       lowest=self.bearish_tracker.lowest_price, combined_score=combined_score)

        # Near-miss op de reflex-drempels: score binnen 0,10 van +-0,55
        if self.current_regime == Regime.LP_MODE and REGIME_THRESHOLD - 0.10 <= abs(combined_score) < REGIME_THRESHOLD:
            decision_log.near_miss("reflex_threshold", combined_score=combined_score, threshold=REGIME_THRESHOLD,
                                   price=current_price, side="bullish" if combined_score > 0 else "bearish")

        # NIEUW (3 sep 2026, op verzoek): markt-bevestigde terugkeer naar
        # LP_MODE -- ANDERS dan de trailing-stop hierboven (specifiek
        # voor winst-name bij BULLISH_REFLEX, 5% afstand), werkt dit voor
        # BEIDE reflex-richtingen en is bedoeld om terug te keren zodra de
        # markt daadwerkelijk lijkt te kalmeren, niet om winst te
        # beschermen. Wordt alleen gecontroleerd als de sentiment-score
        # ZELF nog geen terugkeer aangeeft (target_regime nog steeds de
        # reflex-modus) -- dit is een AANVULLENDE, geen vervangende, weg
        # terug naar de pool.
        if (target_regime == self.current_regime
                and self.current_regime in (Regime.BULLISH_REFLEX, Regime.BEARISH_REFLEX)):
            markt_bevestigd, reden = self._check_market_confirmed_reflex_exit(fresh_reflex_price)
            if markt_bevestigd:
                print(f"[regime] Markt-bevestigde terugkeer naar LP_MODE tijdens "
                      f"{self.current_regime.value}: {reden}.")
                telegram_notify.send_telegram_message(
                    f"Markt-bevestigde terugkeer naar LP_MODE: {reden}. "
                    f"Positie wordt heropend."
                )
                target_regime = Regime.LP_MODE
                is_market_confirmed_reentry = True
                decision_log.log("market_confirmed_exit", regime=self.current_regime.value,
                                 price=fresh_reflex_price, reason=market_confirmed_reason, combined_score=combined_score)
                market_confirmed_reason = reden

        if target_regime == self.current_regime:
            # Toont fresh_reflex_price tijdens reflex-modus (3 sep 2026,
            # ter verduidelijking na eerdere verwarring) -- dat is de
            # prijs die de trailing-stop/markt-bevestigde-terugkeer-check
            # hierboven DAADWERKELIJK gebruikten, niet noodzakelijk gelijk
            # aan current_price (GeckoTerminal, kan een eigen, tragere
            # verversings-cadans hebben voor deze testnet-pool).
            weergave_prijs = (
                fresh_reflex_price
                if self.current_regime in (Regime.BULLISH_REFLEX, Regime.BEARISH_REFLEX)
                else current_price
            )
            print(f"[regime] Blijft in {self.current_regime.value} "
                  f"(combined_score={combined_score:+.2f}, prijs={weergave_prijs:.5f})")
            return

        # Cooldown tegen flapping -- winst-name via de trailing-stop, en
        # een markt-bevestigde terugkeer (3 sep 2026, zelfde redenering:
        # als de markt zelf al bevestigd heeft dat de beweging voorbij
        # is, is verder wachten niet zinvol), zijn hiervan uitgezonderd.
        seconds_since_last = time.time() - self._last_transition_at
        if (not is_profit_take and not is_market_confirmed_reentry
                and seconds_since_last < self.regime_cooldown_seconds):
            remaining_min = (self.regime_cooldown_seconds - seconds_since_last) / 60
            print(f"[regime] Overgang naar {target_regime.value} uitgesteld -- "
                  f"cooldown actief, nog {remaining_min:.1f} min.")
            decision_log.near_miss("regime_deferred_cooldown", from_regime=self.current_regime.value,
                                   to_regime=target_regime.value, combined_score=combined_score,
                                   price=current_price, remaining_min=round(remaining_min, 1))
            return

        print(f"[regime] OVERGANG: {self.current_regime.value} -> {target_regime.value} "
              f"(combined_score={combined_score:+.2f})")

        signal_id = await self.db.log_strategy_signal(
            direction=target_regime.value, confidence=abs(combined_score),
            position_fraction=1.0, btc_score=self._cached_btc_score,
            hbar_score=self._cached_hbar_score,
            panic_override_triggered=(target_regime == Regime.BEARISH_REFLEX),
            reasoning=f"Regime-overgang {self.current_regime.value} -> {target_regime.value}"
                      f"{' (winst-name)' if is_profit_take else ''}"
                      f"{f' (markt-bevestigd: {market_confirmed_reason})' if is_market_confirmed_reentry else ''}",
        )

        if DRY_RUN:
            print(f"[DRY RUN] Zou overgaan van {self.current_regime.value} naar {target_regime.value}")
            if target_regime == Regime.BULLISH_REFLEX:
                self.trailing_tracker = TrailingStopTracker(
                    entry_price=current_price, trailing_distance_pct=TRAILING_STOP_PCT,
                    initial_stop_loss=current_price * (1 - TRAILING_STOP_PCT),
                )
            self.current_regime = target_regime
            self._last_transition_at = time.time()
            return

        previous_regime = self.current_regime  # nodig om exit correct te loggen, voor overschrijven
        transition_succeeded = await self._execute_transition(target_regime, current_price, signal_id)
        self._last_transition_at = time.time()
        decision_log.log("regime_change", from_regime=previous_regime.value, to_regime=target_regime.value,
                         succeeded=transition_succeeded, price=current_price, combined_score=combined_score,
                         threshold=REGIME_THRESHOLD, exit_threshold=REGIME_THRESHOLD_EXIT,
                         trigger=("trailing_stop" if is_profit_take else
                                  "market_confirmed" if is_market_confirmed_reentry else "score"),
                         macro_regime=self._cached_macro_regime, hourly_vol=self._cached_hourly_volatility)

        # BUGFIX (4 sep 2026, KRITIEK, gevonden na een spam-lus van
        # identieke Telegram-berichten, elke cyclus): als een markt-
        # bevestigde terugkeer WEL gedetecteerd wordt maar de overstap
        # zelf mislukt (bv. de balanceringsklem), bleef _reflex_exit_
        # pending_since ongewijzigd staan -- de ONDERLIGGENDE, ruwe
        # conditie (bv. "30 min zijwaarts") blijft dan gewoon waar, dus
        # de VOLGENDE cyclus werd de bevestiging METEEN weer als "net
        # bevestigd" gezien, en stuurde opnieuw dezelfde melding. Reset
        # nu expliciet bij een mislukte poging -- de VOLGENDE keer moet
        # de conditie opnieuw de volledige bevestigingsperiode
        # ononderbroken gelden, wat vanzelf ook de meldingsfrequentie
        # begrenst (net als de balanceringsklem-cooldown elders).
        if is_market_confirmed_reentry and not transition_succeeded:
            self._reflex_exit_pending_since = None
            self._reflex_exit_pending_reason = ""

        if transition_succeeded:
            # Reflex-episode-logging (27 aug 2026): exit loggen als we een
            # reflex-regime VERLATEN, entry loggen als we er een INSTAPPEN.
            # Beide kunnen in dezelfde overgang gebeuren (bv. bearish_reflex
            # -> bullish_reflex, zonder tussenstop in LP_MODE).
            if previous_regime in (Regime.BULLISH_REFLEX, Regime.BEARISH_REFLEX) \
                    and self._active_reflex_episode_id is not None:
                if is_profit_take:
                    exit_reason = "trailing_stop"
                elif is_market_confirmed_reentry:
                    exit_reason = "market_confirmed"
                else:
                    exit_reason = "sentiment_reverted"
                await self.db.log_reflex_exit(
                    self._active_reflex_episode_id, current_price, exit_reason
                )
                self._active_reflex_episode_id = None

            if target_regime in (Regime.BULLISH_REFLEX, Regime.BEARISH_REFLEX):
                self._active_reflex_episode_id = await self.db.log_reflex_entry(
                    target_regime.value, current_price, combined_score
                )
                # Markt-bevestigde-terugkeer-tracking resetten bij ELKE
                # nieuwe reflex-episode (3 sep 2026) -- ook bij een
                # directe wissel tussen bullish/bearish zonder tussenstop
                # in LP_MODE, anders zou data van de vorige episode
                # doorlekken naar de nieuwe.
                self._reflex_extreme_price = None
                self._reflex_price_history = []
                self._reflex_entered_at = None
                self._reflex_exit_pending_since = None
                self._reflex_exit_pending_reason = ""

            self.current_regime = target_regime

            # Regimestatus persisteren (27 aug 2026) -- zodat een herstart
            # niet langer altijd terugvalt op de default LP_MODE.
            trailing_entry_price = (self.trailing_tracker.entry_price if self.trailing_tracker else (self.bearish_tracker.entry_price if self.bearish_tracker else None))
            await self.db.save_regime_state(
                self.current_regime.value, trailing_entry_price, self._active_reflex_episode_id,
                self._flash_defense_until,
            )
        # Bij falen: current_regime blijft bewust ongewijzigd (de vorige,
        # bekende staat) -- de foutmelding is al verstuurd in
        # _execute_transition. Handmatige controle is dan nodig voordat
        # de bot hier weer op vertrouwt.

    # Hedera's transactiekosten zijn vastgesteld in USD-termen (fee-schedule),
    # maar worden betaald in HBAR -- een vaste HBAR-reserve zou dus fout zijn
    # in twee richtingen als de HBAR-prijs beweegt: te veel kapitaal
    # inactief bij een hoge prijs, te weinig dekking bij een lage prijs.
    # $2 dekt ruimschoots meerdere toekomstige transacties, gezien Hedera's
    # kosten doorgaans een fractie van een cent tot een paar cent per tx zijn.
    GAS_RESERVE_USD = 2.0
    # Ondergrens -- ongeacht de prijs nooit minder dan dit bedrag
    # reserveren. Verhoogd van 10 naar 50 HBAR (30 aug 2026, op
    # structureel verzoek) -- functioneert vanaf nu niet meer puur als
    # gas-buffer, maar als algemene operationele veiligheidsreserve die
    # de bot bij ELKE toekomstige positie-opening/herbalancering
    # aanhoudt, niet alleen voor transactiekosten.
    # HERZIEN (4 sep 2026, EMPIRISCH BEVESTIGD na twee losse, live
    # "Insufficient funds for transfer"-fouten -- de eerste keer werd dit
    # ten onrechte toegeschreven aan een verouderde balans-cache
    # (teruggedraaid op verzoek); die fix loste het echter NIET op bij
    # een tweede, herhaalde test, wat de ECHTE oorzaak blootlegde:
    #
    # Dit is GEEN kwestie van "de reserve gebruiken voor de pool-
    # inhoud" (die zorg blijft terecht en onveranderd) -- het gaat om
    # wat het NETWERK vooraf blokkeert als garantie (gas_limit x
    # max_fee_per_gas, bij open_position()'s gas_limit_override van
    # 1.200.000) VOORDAT een transactie uberhaupt wordt uitgevoerd, ook
    # al wordt er uiteindelijk maar een fractie daarvan daadwerkelijk in
    # rekening gebracht. 50 HBAR bleek deze gereserveerde marge niet
    # altijd te dekken. Verdubbeld naar 100 HBAR, AANNAME, geen
    # empirisch exact geijkte waarde -- de reserve zelf wordt nog steeds
    # NOOIT bewust ingezet als positie-kapitaal (dat principe blijft
    # onveranderd), dit vergroot alleen de marge voor wat het netwerk
    # vooraf kan blokkeren.
    # (7 sep 2026, op verzoek) Ondergrens van wat ALTIJD als native HBAR in
    # de wallet blijft: nooit geswapt, nooit bijgestort, alleen voor gas/
    # fees. Instelbaar via .env; zelfde default als het vangnet-pad
    # (LP_SAFETYNET_MIN_RESERVE_HBAR).
    MIN_GAS_RESERVE_HBAR = float(os.environ.get("MIN_GAS_RESERVE_HBAR", "50.0"))
    ROUND_GAS_BUFFER_HBAR = float(os.environ.get("ROUND_GAS_BUFFER_HBAR", "8.0"))

    def _get_swappable_hbar_balance(self, current_price: float) -> float:
        """
        Vraagt de WERKELIJKE on-chain HBAR-balans op i.p.v. te herberekenen
        vanuit total_capital_usdc/current_price -- dat laatste zou bij een
        koersstijging tijdens BULLISH_REFLEX stelselmatig te weinig HBAR
        teruggeven (de koerswinst wordt dan nooit verzilverd), en na het
        sluiten van een LP-positie klopt de aanname van "100% in één token"
        sowieso niet meer (er komt een mix van HBAR+USDC terug).

        De gas-reserve is het GROOTSTE van (a) de USD-gebaseerde berekening
        (schaalt correct mee met de prijs) en (b) een vaste ondergrens van
        MIN_GAS_RESERVE_HBAR, zodat de reserve bij een hoge HBAR-prijs nooit
        te klein wordt.
        """
        if not self.rpc_client:
            return 0.0
        # Korte TTL-cache (30 aug 2026, op verzoek: onderzoek naar
        # onnodige RPC-belasting) -- deze functie wordt meerdere keren
        # per cyclus aangeroepen (rebalance-check, kapitaal-bijstorten,
        # etc.), en deed voorheen ELKE keer een verse RPC-aanroep. Een
        # korte cache (5s, ruim binnen een enkele 60s-cyclus, maar kort
        # genoeg om nooit een echt-verouderde waarde te gebruiken bij
        # een volgende cyclus) elimineert de meeste overbodige, dubbele
        # aanroepen zonder de vereiste versheid op te offeren.
        now = time.time()
        if (self._hbar_balance_cache is not None
                and (now - self._hbar_balance_cache_at) < 5.0):
            balance = self._hbar_balance_cache
        else:
            try:
                balance = float(self.rpc_client.get_hbar_balance())
                self._hbar_balance_cache = balance
                self._hbar_balance_cache_at = now
            except Exception:
                self._balance_fetch_failed_this_cycle = True
                return 0.0
        usd_based_reserve = self.GAS_RESERVE_USD / current_price if current_price > 0 else 0.0
        gas_reserve_hbar = max(usd_based_reserve, self.MIN_GAS_RESERVE_HBAR)
        # (10 sep 2026) Plus een buffer voor de gas van de ronde ZELF
        # (sluiten+swap+wrap+approves+mint ~3-4 HBAR): anders eindigt de
        # wallet na elke herbalancering ONDER de reserve (97,9 -> 46,9).
        gas_reserve_hbar += self.ROUND_GAS_BUFFER_HBAR
        return max(0.0, balance - gas_reserve_hbar)

    def _get_swappable_usdc_balance(self) -> float:
        """Zelfde principe als hierboven, voor USDC (inclusief dezelfde
        korte TTL-cache, 30 aug 2026)."""
        if not self.rpc_client:
            return 0.0
        now = time.time()
        if (self._usdc_balance_cache is not None
                and (now - self._usdc_balance_cache_at) < 5.0):
            return self._usdc_balance_cache
        try:
            if HEDERA_NETWORK == "testnet":
                base = resolve_testnet_addresses()
            else:
                base = resolve_mainnet_addresses()
            from swap_executor import ERC20_ABI
            balance = self.rpc_client.get_token_balance(
                base.usdc, ERC20_ABI, decimals=base.usdc_decimals
            )
            result = max(0.0, float(balance))
            self._usdc_balance_cache = result
            self._usdc_balance_cache_at = now
            return result
        except Exception as e:
            self._balance_fetch_failed_this_cycle = True
            telegram_notify.report_error("regime_loop: USDC-balans opvragen", str(e))
            return 0.0

    async def _run_swap_and_log(self, direction: str, amount: float,
                                  signal_id: Optional[int] = None,
                                  slippage: Optional[float] = None) -> bool:
        """Voert een swap uit en logt het resultaat naar Postgres. Geeft True terug bij succes."""
        # BUGFIX (7 sep 2026): fee-tier EXPLICIET meegeven. Zonder dit
        # viel het subprocess terug op zijn eigen default (3000), terwijl
        # de LP-positie in de 1500-pool zit -- op mainnet bestaat er geen
        # WHBAR/USDC-pool op 3000, dus elke swap revertte op de quoter.
        fee_tier = (self.lp_manager.config.fee_tier if self.lp_manager
                    else int(os.environ.get("LP_FEE_TIER", "3000")))
        result = subprocess.run(
            ["python3", "execute_hbar_swap_standalone.py",
             "--direction", direction, "--amount", str(amount),
             "--network", HEDERA_NETWORK, "--engine", "v2",
             "--fee-tier", str(fee_tier)]
            + (["--slippage", str(slippage)] if slippage else []),
            capture_output=True, text=True,
        )
        status = "success" if result.returncode == 0 else "failed"
        # (7 sep 2026) Subprocess-uitvoer ALTIJD naar stdout -- voorheen
        # ging een swap-fout alleen naar Telegram en stond er niets in de
        # docker-logs.
        print(f"[swap] {direction} {amount:.4f} fee_tier={fee_tier} -> {status}")
        if result.stderr.strip():
            print("[swap] stderr: " + result.stderr.strip()[-800:])
        if status == "failed" and result.stdout.strip():
            print("[swap] stdout: " + result.stdout.strip()[-1200:])

        # Gestructureerde output parsen (23 aug 2026 toegevoegd aan
        # execute_hbar_swap_standalone.py) -- zonder dit werden tx_hash en
        # estimated_amount_out altijd als None gelogd, wat elke vorm van
        # winst/verlies-analyse achteraf onmogelijk maakte.
        tx_hash, estimated_amount_out = None, None
        try:
            last_line = result.stdout.strip().splitlines()[-1]
            parsed = json.loads(last_line)
            tx_hash = parsed.get("tx_hash")
            estimated_amount_out = parsed.get("estimated_amount_out")
        except (IndexError, json.JSONDecodeError):
            pass  # subprocess gaf geen geldige JSON terug -- blijft None, geen crash

        await self.db.log_trade(
            direction=direction, engine="v2", network=HEDERA_NETWORK,
            amount_in=amount, estimated_amount_out=estimated_amount_out,
            actual_amount_out=None,  # SaucerSwap's exactInputSingle-return-waarde
                                       # wordt nog niet teruggegeven door de subprocess-
                                       # aanroep -- estimated_amount_out is het beste
                                       # wat we nu hebben, nog geen exacte uitkomst.
            tx_hash=tx_hash, status=status,
            strategy_signal_id=signal_id,
        )

        if status == "failed":
            telegram_notify.report_error(
                "regime_loop: swap", f"Swap {direction} ({amount:.4f}) mislukt: {result.stderr[-400:]}"
            )
        else:
            # Pauze na een succesvolle swap (26 aug 2026) -- deze swap
            # liep via een APART subprocess, met zijn EIGEN RPC-client-
            # instantie. De centrale nonce-timing-fix in
            # hedera_rpc_client.wait_for_receipt() (time.sleep(2) na elke
            # bevestigde tx) geldt alleen BINNEN diezelfde procesinstantie
            # -- als DIT (aanroepende) proces meteen daarna ZELF een
            # transactie stuurt (bv. open_position() in de
            # herbalancerings-flow), kan de RPC-relay zijn nonce-teller
            # nog niet bijgewerkt hebben, wat een "Nonce too low"-fout
            # geeft (empirisch bevestigd bij een handmatige test).
            await asyncio.sleep(4)

            # Caches ongeldig maken na een succesvolle swap (30 aug 2026)
            # -- de balans is nu daadwerkelijk veranderd, een volgende
            # lezing binnen dezelfde cyclus (bv. na _ensure_balanced_
            # liquidity_ratio()'s eigen swap, gevolgd door een directe
            # her-lezing) moet de VERSE waarde krijgen, niet een
            # verouderde, gecachete waarde van vóór deze swap.
            self._hbar_balance_cache = None
            self._usdc_balance_cache = None

        return status == "success"

    async def _execute_transition(self, target_regime: Regime, current_price: float,
                                    signal_id: Optional[int] = None) -> bool:
        """
        Geeft True terug als de overgang volledig is gelukt, False als er
        ergens een swap is mislukt. De aanroeper mag self.current_regime
        ALLEEN bijwerken bij True -- anders raakt de interne staat
        losgezongen van de werkelijke, on-chain positie.
        """
        # Expliciete guard: zonder rpc_client geven de balans-functies 0.0
        # terug, wat de amount>0-checks verderop stil zou laten slagen
        # (geen swap nodig bij bedrag 0) -- zonder deze check zou de bot
        # zichzelf dan valselijk als "overgang geslaagd" registreren,
        # inclusief een misleidende Telegram-bevestiging, terwijl er
        # helemaal geen wallet is aangesloten en er dus niets is gebeurd.
        if not self.rpc_client:
            telegram_notify.report_error(
                "regime_loop",
                f"Overgang naar {target_regime.value} geweigerd -- geen rpc_client "
                f"(HEDERA_BOT_PRIVATE_KEY ontbreekt?) terwijl DRY_RUN=false staat. "
                f"HANDMATIGE CONTROLE VEREIST: de bot kan geen transacties uitvoeren.",
            )
            return False

        all_succeeded = True
        # Standaard False -- alleen de LP_MODE-tak hieronder (waar de
        # balanceringsklem kan weigeren vóór enige transactie) zet dit
        # ooit op True (3 sep 2026, zie toelichting daar).
        geen_actie_ondernomen_door_klem = False

        if self.current_regime == Regime.LP_MODE and self.lp_manager and self.lp_manager.state.is_open:
            try:
                self.lp_manager.close_position(self.lp_manager.state.token_id)
                await self.db.clear_active_lp_position()
                telegram_notify.send_telegram_message("Regime-schakelaar: LP-positie volledig geleegd.")
            except Exception as e:
                # Zelfde automatische, veilige on-chain-verificatie als
                # elders (28 aug 2026) -- voorkomt onnodige "HANDMATIGE
                # CONTROLE"-paniek bij een transiente RPC-fout terwijl de
                # close-transactie zelf wel degelijk doorging.
                token_id = self.lp_manager.state.token_id
                try:
                    position = self.lp_manager.position_manager.functions.positions(token_id).call()
                    still_open = position[5] > 0
                except Exception:
                    still_open = None

                if still_open is False:
                    self.lp_manager.state.is_open = False
                    await self.db.clear_active_lp_position()

                    recovered_msg = ""
                    try:
                        recovered = self.lp_manager.check_and_recover_stuck_whbar()
                        if recovered > 0:
                            recovered_msg = (
                                f" Tevens {recovered:.4f} vastzittende WHBAR "
                                f"gevonden en hersteld naar native HBAR."
                            )
                    except Exception:
                        pass

                    telegram_notify.send_telegram_message(
                        f"Regime-schakelaar: sluiten leek te falen ({e}), maar "
                        f"on-chain verificatie bevestigt dat positie {token_id} "
                        f"daadwerkelijk gesloten is. Kapitaal is veilig.{recovered_msg}"
                    )
                elif still_open is True:
                    all_succeeded = False
                    telegram_notify.report_error(
                        "regime_loop: LP-positie sluiten",
                        f"{e} -- ON-CHAIN BEVESTIGD: positie {token_id} staat nog "
                        f"open (liquidity={position[5]}). Kapitaal zit nog veilig "
                        f"in de bestaande positie, geen actie ondernomen.",
                    )
                else:
                    all_succeeded = False
                    telegram_notify.report_error(
                        "regime_loop: LP-positie sluiten",
                        f"{e} -- HANDMATIGE CONTROLE VEREIST, LP-positie mogelijk "
                        f"nog (deels) open, EN de automatische verificatie zelf "
                        f"mislukte ook.",
                    )

        if target_regime == Regime.BULLISH_REFLEX:
            usdc_to_swap = self._get_swappable_usdc_balance()
            success = True
            if usdc_to_swap > 0:
                success = await self._run_swap_and_log("USDC_TO_HBAR", usdc_to_swap, signal_id)
            all_succeeded = all_succeeded and success
            if success:
                self.bearish_tracker = None
                self.trailing_tracker = TrailingStopTracker(
                    entry_price=current_price, trailing_distance_pct=TRAILING_STOP_PCT,
                    initial_stop_loss=current_price * (1 - TRAILING_STOP_PCT),
                )
                telegram_notify.send_telegram_message(
                    f"Regime-schakelaar: BULLISH_REFLEX -- {usdc_to_swap:.2f} USDC naar HBAR "
                    f"bij {current_price:.5f}."
                )

        elif target_regime == Regime.BEARISH_REFLEX:
            hbar_to_swap = self._get_swappable_hbar_balance(current_price)
            success = True
            if hbar_to_swap > 0:
                success = await self._run_swap_and_log("HBAR_TO_USDC", hbar_to_swap, signal_id)
            all_succeeded = all_succeeded and success
            if success:
                self.trailing_tracker = None
                self.bearish_tracker = BearishTrailingStopTracker(current_price, TRAILING_STOP_PCT)
                telegram_notify.send_telegram_message(
                    f"Regime-schakelaar: BEARISH_REFLEX -- {hbar_to_swap:.4f} HBAR naar USDC "
                    f"bij {current_price:.5f}."
                )

        elif target_regime == Regime.LP_MODE:
            # Flash-verdediging respecteren (28 aug 2026, gevonden bij
            # nazoeken): als de trailing-stop winst neemt TERWIJL een
            # flash-verdedigingsperiode nog actief is, mag de bot NIET
            # meteen een nieuwe LP-positie openen middenin de volatiliteit
            # die de verdediging net probeerde te vermijden. Kapitaal
            # blijft dan gewoon in HBAR/USDC staan; het vangnet (nu een
            # tijd-gebaseerde cooldown, zie __init__) pakt het heropenen
            # vanzelf weer op zodra de verdedigingsperiode afloopt.
            if self._flash_defense_until > time.time():
                self._last_safetynet_attempt_at = 0.0
                telegram_notify.send_telegram_message(
                    "Regime-schakelaar: overgang naar LP_MODE uitgesteld -- "
                    "flash-verdediging nog actief. Kapitaal blijft in HBAR/USDC "
                    "staan tot de verdedigingsperiode afloopt; het vangnet "
                    "heropent dan automatisch."
                )
                return all_succeeded

            # Tick-range vooraf berekenen, nodig om de gedeelde
            # herbalancerings-functie hieronder de JUISTE verhouding te
            # laten aanhouden (26 aug 2026) i.p.v. altijd blind 50/50.
            # BUGFIX (30 aug 2026, KRITIEK): fresh_price i.p.v. current_price
            # -- zie uitgebreide toelichting bij de vangnet-fix hierboven
            # (_cycle()). price_to_tick() heeft de pool's eigen, interne
            # SAUCE-per-HBAR-koers nodig, niet GeckoTerminal's USD-schatting.
            from lp_manager import get_live_pool_price
            try:
                fresh_price = get_live_pool_price(
                    self.rpc_client, self.lp_manager.config.factory_address,
                    self.lp_manager.config.token0, self.lp_manager.config.token1,
                    self.lp_manager.config.fee_tier,
                    self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,
                ) if self.lp_manager else current_price
            except Exception:
                fresh_price = current_price

            # Prijs-orakel-manipulatie-check (30 aug 2026, HERZIEN naar
            # TWAP-gebaseerd).
            from lp_manager import price_to_tick
            huidige_tick = price_to_tick(
                fresh_price, self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,
            )
            if not self._check_price_oracle_divergence(huidige_tick):
                return all_succeeded  # wacht tot de volgende cyclus

            combined_score_now = compute_fixed_combined_score(self._cached_btc_score, self._cached_hbar_score)
            combined_volatility_sigma_now = compute_combined_volatility_sigma(
                self._cached_btc_volatility_sigma, self._cached_hbar_volatility_sigma
            )
            combined_volatility_sigma_now = min(
                1.0, combined_volatility_sigma_now * self._volatility_calibration_factor
            )
            combined_score_now = apply_regime_bias(combined_score_now, self._cached_macro_regime)
            # apply_fat_tail_buffer=False (4 sep 2026, op verzoek): dit
            # codepad is UITSLUITEND het heropenen NA een reflex-uitstap
            # (target_regime == LP_MODE wordt alleen hier bereikt vanuit
            # BULLISH_REFLEX/BEARISH_REFLEX) -- kapitaal staat dan al 100%
            # in een enkel token. De normale, fat-tail-scheve range kan
            # dan een onhaalbare heropenings-verhouding vereisen (empirisch
            # gevonden: 8145 HBAR nodig, 2279 beschikbaar). Een symmetrische
            # range is hier direct haalbaar. Andere aanroepers (normale
            # herbalancering, regime-drift, fee-onderprestatie) blijven
            # ongewijzigd de fat-tail-bescherming gebruiken.
            tick_lower, tick_upper = self.lp_manager.compute_range_via_gbm(
                fresh_price, combined_score_now, combined_volatility_sigma_now,
                self._cached_hourly_volatility,
                macro_regime=self._cached_macro_regime,
                confidence_level=self._determine_gbm_confidence_level(combined_score_now),
                apply_fat_tail_buffer=False,
            ) if self.lp_manager else (0, 0)

            if self.lp_manager:
                # BUGFIX (30 aug 2026): fresh_price i.p.v. current_price --
                # zelfde reden als hierboven. all_succeeded baseert zich nu
                # op de daadwerkelijke uitkomst i.p.v. hardcoded True.
                all_succeeded = await self._ensure_balanced_liquidity_ratio(fresh_price, tick_lower, tick_upper)
                # NIEUW (3 sep 2026, gevonden na een onterecht-alarmerende
                # melding): onthoudt of de balanceringsklem HIER al weigerde
                # -- als dat zo is, is er NOG NIETS naar de blockchain
                # gestuurd, dus kapitaal is gegarandeerd nog exact waar het
                # was. Dat verdient een rustige melding, geen "HANDMATIGE
                # CONTROLE VEREIST"-alarm (dat is voor als een transactie
                # WEL onderweg was en toen pas misging).
                geen_actie_ondernomen_door_klem = not all_succeeded
            else:
                all_succeeded = True
                geen_actie_ondernomen_door_klem = False

            if all_succeeded and self.lp_manager:
                # Balans NA de herbalancerings-swap opvragen, niet vooraf
                # geschat -- dat is de daadwerkelijke inzet voor de LP-positie.
                #
                # BUGFIX (4 sep 2026, gevonden na een "Insufficient funds
                # for transfer"-fout van de RPC-node zelf): de 5-seconden-
                # cache op _get_swappable_hbar_balance() kon hier een
                # VEROUDERDE balans teruggeven als deze aanroep binnen die
                # 5 seconden na de balancerings-swap plaatsvond -- de
                # cache wist dan nog niet dat DIE swap al gas had gekost,
                # waardoor het (foutief) dacht dat er meer natieve HBAR
                # over was dan er werkelijk was. Cache expliciet ongeldig
                # maken vlak vóór deze cruciale meting dwingt een ECHTE,
                # verse RPC-aanroep af.
                self._hbar_balance_cache = None
                final_hbar_balance = self._get_swappable_hbar_balance(current_price)
                final_usdc_balance = self._get_swappable_usdc_balance()

                # Zelfde robuustheids-fixes als het vangnet in _cycle()
                # (26 aug 2026): proportionele amount-afleiding + ruimere
                # marge + expliciete gas-limiet + prijs RECHTSTREEKS uit de
                # pool zelf (i.p.v. GeckoTerminal, die een eigen
                # indexerings-vertraging kan hebben t.o.v. de daadwerkelijke
                # live pool-staat -- de pool beoordeelt onze transactie
                # altijd tegen zijn EIGEN actuele prijs).
                from lp_manager import compute_amount1_for_amount0, compute_amount0_for_amount1, get_live_pool_price
                try:
                    current_price = get_live_pool_price(
                        self.rpc_client, self.lp_manager.config.factory_address,
                        self.lp_manager.config.token0, self.lp_manager.config.token1,
                        self.lp_manager.config.fee_tier,
                        self.lp_manager.config.token0_decimals, self.lp_manager.config.token1_decimals,
                    )
                except Exception:
                    pass  # val terug op de bestaande current_price als ophalen faalt
                combined_score_now = compute_fixed_combined_score(self._cached_btc_score, self._cached_hbar_score)
                combined_volatility_sigma_now = compute_combined_volatility_sigma(
                    self._cached_btc_volatility_sigma, self._cached_hbar_volatility_sigma
                )
                combined_volatility_sigma_now = min(
                    1.0, combined_volatility_sigma_now * self._volatility_calibration_factor
                )
                combined_score_now = apply_regime_bias(combined_score_now, self._cached_macro_regime)
                tick_lower, tick_upper = self.lp_manager.compute_range_via_gbm(
                    current_price, combined_score_now, combined_volatility_sigma_now,
                    self._cached_hourly_volatility,
                    macro_regime=self._cached_macro_regime,
                    confidence_level=self._determine_gbm_confidence_level(combined_score_now),
                )
                hbar_raw_available = int(final_hbar_balance * (10 ** self._hbar_decimals))
                usdc_raw_available = int(final_usdc_balance * (10 ** self._usdc_decimals))
                needed_usdc_for_full_hbar = self.lp_manager.compute_needed_usdc_for_hbar(
                    hbar_raw_available, current_price, tick_lower, tick_upper,
                )
                if needed_usdc_for_full_hbar <= usdc_raw_available:
                    hbar_raw, usdc_raw = hbar_raw_available, needed_usdc_for_full_hbar
                else:
                    usdc_raw = usdc_raw_available
                    hbar_raw = self.lp_manager.compute_needed_hbar_for_usdc(
                        usdc_raw_available, current_price, tick_lower, tick_upper,
                    )

                try:
                    self.lp_manager.open_position(
                        hbar_raw, usdc_raw, current_price,
                        # Verruimd naar 30% (4 sep 2026, op verzoek) --
                        # deze dunne testnet-pool blijkt door ONZE EIGEN,
                        # relatief grote transacties (bevestigd: onze
                        # enkele swap was al een aanzienlijk deel van het
                        # TOTALE 24u-volume) meerdere procenten prijsimpact
                        # te ondervinden binnen een enkele herbalancerings-
                        # reeks -- op mainnet, met veel diepere liquiditeit,
                        # zou dezelfde transactiegrootte een verwaarloosbare
                        # impact hebben. Puur een testnet-aanpassing.
                        slippage_tolerance=0.30,
                        gas_limit_override=1_200_000,
                        precomputed_tick_range=(tick_lower, tick_upper),
                    )
                    await self.db.save_active_lp_position(
                        self.lp_manager.state.token_id,
                        self.lp_manager.state.tick_lower,
                        self.lp_manager.state.tick_upper,
                    )
                    self.trailing_tracker = None
                    self.bearish_tracker = None
                    telegram_notify.send_telegram_message(
                        f"Regime-schakelaar: terug naar LP_MODE -- {hbar_raw/(10**self._hbar_decimals):.4f} HBAR "
                        f"+ {usdc_raw/(10**self._usdc_decimals):.2f} USDC in de pool."
                    )
                    # NIEUW (4 sep 2026, op verzoek): direct na een
                    # geslaagde heropening proberen om eventueel
                    # restkapitaal (door balancerings-onnauwkeurigheid
                    # of een kleine prijsbeweging tussen berekening en
                    # daadwerkelijke mint) METEEN bij te storten, zonder
                    # op de normale cooldown te wachten -- voorkomt dat
                    # het te lang los blijft staan terwijl de prijs
                    # intussen verder wegdrijft.
                    await self._deploy_excess_capital_if_available(current_price, bypass_cooldown=True)
                except Exception as e:
                    all_succeeded = False
                    telegram_notify.report_error(
                        "regime_loop: LP-positie openen",
                        f"{e} -- herbalancerings-swap is al gebeurd, maar de LP-positie zelf niet "
                        f"geopend. Kapitaal staat nu los in HBAR/USDC. HANDMATIGE CONTROLE VEREIST.",
                    )

        if not all_succeeded:
            if geen_actie_ondernomen_door_klem:
                # Rustige, informatieve melding -- de balanceringsklem
                # weigerde vóórdat er iets naar de blockchain ging, dus
                # kapitaal is gegarandeerd nog exact waar het was.
                print(f"[regime] Overgang naar {target_regime.value} nog niet mogelijk -- "
                      f"balanceringsklem weigerde vóór enige transactie. Kapitaal onaangeroerd, "
                      f"regime blijft {self.current_regime.value}. Wordt de eerstvolgende cyclus "
                      f"opnieuw geprobeerd.")
            else:
                telegram_notify.report_error(
                    "regime_loop",
                    f"Overgang naar {target_regime.value} DEELS OF VOLLEDIG MISLUKT -- "
                    f"regime blijft geregistreerd als {self.current_regime.value}, maar de "
                    f"werkelijke on-chain positie is mogelijk inconsistent. HANDMATIGE "
                    f"CONTROLE VEREIST voordat de bot hier verder op vertrouwt.",
                )

        return all_succeeded
