"""
llm_sentiment_engine.py

Vervangt/vult aan op de vote/tijd-gewogen scoring in cryptopanic_client.py
met een LLM-gebaseerde sentiment-analyse (Claude), zoals besproken in het
Gemini-gesprek. In plaats van de 'Instructor'-library (Pydantic + OpenAI)
gebruiken we Claude's tool-use met een gedwongen tool_choice -- dat is het
Anthropic-equivalent: het garandeert dat het antwoord altijd het exacte
JSON-schema volgt, nooit vrije tekst.

Waarom Claude i.p.v. GPT-4o-mini (uit het Gemini-gesprek): je werkt al met
Claude, dus geen aparte OpenAI-key/account nodig. Claude Haiku 4.5 is qua
snelheid en kosten vergelijkbaar met GPT-4o-mini.

BELANGRIJK -- latency-afweging (zoals in het Gemini-gesprek besproken):
elke los nieuwsitem via een aparte LLM-call sturen is trager en duurder
dan onze bestaande vote-gewogen berekening. Dit is dus een bewuste
kwaliteit-voor-snelheid-ruil: rijkere contextbegrip (bv. "Google Cloud
breidt Hedera-nodes uit" correct als sterk bullish herkennen, iets wat
VADER/vote-counting mist), tegen hogere latency (~0.5-2s per call) en
kosten (fractie van een cent per call, maar niet nul).
"""

import os
import json
import time
import math
from dataclasses import dataclass
from typing import List, Optional

import anthropic


LLM_MODEL = "claude-haiku-4-5-20251001"

# Het gedwongen JSON-schema -- Claude's tool-use garandeert dat de output
# hier exact aan voldoet, net als Instructor/Pydantic in het Gemini-voorbeeld.
SENTIMENT_TOOL_SCHEMA = {
    "name": "record_sentiment_analysis",
    "description": "Registreert de sentiment-analyse van crypto-nieuws voor een specifieke asset.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sentiment_score": {
                "type": "number",
                "description": "Sentiment-score van -1.0 (extreem negatief) tot +1.0 (extreem positief).",
                "minimum": -1.0,
                "maximum": 1.0,
            },
            "volatility_sigma": {
                "type": "number",
                "description": (
                    "Marktonzekerheid/chaos-score van dit specifieke nieuwsitem, 0.0 tot 1.0 "
                    "(28 aug 2026, voor het GBM-model). 0.0 = saai, verwacht nieuws, brede "
                    "consensus. 0.5 = omstreden nieuws, regelgeving-verschuivingen. 1.0 = "
                    "black-swan-gebeurtenis, hack, sterk tegenstrijdige berichtgeving, "
                    "onverwachte, massale liquidaties. Dit is een ANDERE as dan sentiment_score "
                    "-- zelfs zeer positief OF zeer negatief nieuws kan hoge onzekerheid geven."
                ),
                "minimum": 0.0,
                "maximum": 1.0,
            },
            "confidence": {
                "type": "number",
                "description": "Hoe zeker het model is van deze inschatting, 0.0 tot 1.0.",
                "minimum": 0.0,
                "maximum": 1.0,
            },
            "rationale": {
                "type": "string",
                "description": "Korte onderbouwing (1-2 zinnen) in het Nederlands.",
            },
            "counter_argument": {
                "type": "string",
                "description": (
                    "Verplicht tegenargument tegen je eigen sentiment_score -- als de score "
                    "positief is: waarom zou de markt NIET stijgen? Als negatief: waarom zou "
                    "de markt NIET dalen? Dit dwingt zelfreflectie af en voorkomt dat je "
                    "eerste ingeving klakkeloos wordt bevestigd."
                ),
            },
            "is_idiosyncratic": {
                "type": "boolean",
                "description": (
                    "True als dit nieuws specifiek is voor de asset zelf (bv. een "
                    "partnership-aankondiging), False als het puur bredere marktbeweging "
                    "reflecteert die ook andere crypto's raakt."
                ),
            },
        },
        "required": ["sentiment_score", "volatility_sigma", "confidence", "rationale",
                      "counter_argument", "is_idiosyncratic"],
    },
}

CALIBRATION_EXAMPLES_PATH = os.path.join(os.path.dirname(__file__), "calibration_examples.json")

_FALLBACK_EXAMPLES_TEXT = (
    "(LET OP: dit zijn PLACEHOLDER-voorbeelden ter illustratie van het format -- "
    "calibration_examples.json bestaat nog niet of is leeg. Draai "
    "generate_calibration_examples.py na een backtest om deze te vervangen door "
    "echte, bevestigde voorbeelden. Verzonnen voorbeelden geven een vals gevoel "
    "van kalibratie):\n"
    "- 'Hedera Council verwelkomt nieuw lid [grote onderneming]' -> koers +4-8% "
    "binnen 24u -> dit soort nieuws verdient een score rond +0.6 tot +0.8\n"
    "- 'Analist voorspelt HBAR zal stijgen' -> koers gemiddeld genomen VLAK -- "
    "opinie-stukken zonder concrete aanleiding hebben nauwelijks voorspellende "
    "waarde, score rond 0.0-0.2\n"
    "- 'SEC onderzoekt [beurs] voor onduidelijke reden' -> koers -2-5%, maar "
    "herstelt vaak binnen dagen als er geen vervolg komt -- korte, tijdelijke "
    "impact, score rond -0.3 tot -0.5"
)


def _load_calibration_examples_text() -> str:
    """
    Laadt few-shot-voorbeelden uit calibration_examples.json (gegenereerd
    door generate_calibration_examples.py op basis van echte backtest-
    resultaten). Valt terug op illustratieve placeholders als dat bestand
    nog niet bestaat -- zo blijft duidelijk zichtbaar dat er nog geen
    echte kalibratie heeft plaatsgevonden.
    """
    if not os.path.exists(CALIBRATION_EXAMPLES_PATH):
        return _FALLBACK_EXAMPLES_TEXT

    try:
        with open(CALIBRATION_EXAMPLES_PATH) as f:
            examples = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _FALLBACK_EXAMPLES_TEXT

    if not examples:
        return _FALLBACK_EXAMPLES_TEXT

    lines = [
        f"(Gebaseerd op {len(examples)} bevestigde voorbeelden uit een echte backtest "
        f"-- zie generate_calibration_examples.py):"
    ]
    for ex in examples:
        lines.append(
            f"- '{ex['headline']}' -> koers {ex['return_pct']:+.1f}% binnen {ex['horizon']} "
            f"-> score was {ex['sentiment_score']:+.2f}, dit klopte met de uitkomst"
        )
    return "\n".join(lines)


def _build_system_prompt() -> str:
    return (
        "Je bent een kwantitatieve crypto-analist die nieuwsheadlines beoordeelt voor een "
        "geautomatiseerde trading bot. Wees nuchter en sceptisch -- de meeste headlines zijn "
        "neutraal of hebben marginale impact. Reserveer extreme scores (>0.7 of <-0.7) voor "
        "nieuws met duidelijk, direct koerseffect (bv. hacks, grote partnerships, "
        "regelgeving-beslissingen). Roep altijd de tool aan, geef nooit vrije tekst.\n\n"
        "Naast sentiment_score beoordeel je ook volatility_sigma (28 aug 2026, voor het "
        "GBM-koersmodel) -- een APARTE as die marktonzekerheid meet, los van richting: "
        "0.0 = saai, verwacht nieuws, brede consensus (bv. een routine-technische-update). "
        "0.5 = omstreden nieuws, regelgeving-verschuivingen (bv. een SEC-onderzoek zonder "
        "duidelijke uitkomst). 1.0 = black-swan-gebeurtenis, hack, sterk tegenstrijdige "
        "berichtgeving, onverwachte massale liquidaties. LET OP: zeer positief EN zeer "
        "negatief nieuws kunnen allebei hoge volatility_sigma hebben -- het gaat om hoe "
        "CHAOTISCH/onvoorspelbaar de situatie is, niet om de richting.\n\n"
        "Kalibratie -- historische voorbeelden van vergelijkbare headlines en wat de koers "
        "daarna daadwerkelijk deed:\n"
        f"{_load_calibration_examples_text()}\n"
        "Gebruik deze ijkpunten om vergelijkbare headlines proportioneel te scoren, niet als "
        "exacte sjablonen."
    )


SYSTEM_PROMPT = _build_system_prompt()


@dataclass
class LlmSentimentResult:
    asset: str
    sentiment_score: float
    volatility_sigma: float
    confidence: float
    rationale: str
    counter_argument: str
    is_idiosyncratic: bool
    headline: str


class LlmSentimentEngine:
    def __init__(self, api_key: Optional[str] = None, model: str = LLM_MODEL):
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model

    def analyze_headline(self, asset: str, headline: str,
                          price_context: Optional[str] = None) -> LlmSentimentResult:
        """
        price_context: optionele extra context, bv. "1u prijsactie: +2.4%, 24u volume: +150%"
        -- dit is precies het CoinGecko-marktdata-element uit het Gemini-gesprek,
        meegegeven zodat het LLM prijsbeweging en nieuws in samenhang beoordeelt.
        """
        user_content = f"Asset: {asset}\nHeadline: {headline}"
        if price_context:
            user_content += f"\nMarktcontext: {price_context}"

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                system=SYSTEM_PROMPT,
                tools=[SENTIMENT_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": "record_sentiment_analysis"},
                messages=[{"role": "user", "content": user_content}],
            )

            tool_use_block = next(b for b in response.content if b.type == "tool_use")
            data = tool_use_block.input

            sentiment_score = data.get("sentiment_score", 0.0)
            volatility_sigma = data.get("volatility_sigma", 0.5)
            if not isinstance(sentiment_score, (int, float)) or not (-1.0 <= sentiment_score <= 1.0):
                sentiment_score = 0.0
            if not isinstance(volatility_sigma, (int, float)) or not (0.0 <= volatility_sigma <= 1.0):
                volatility_sigma = 0.5

            return LlmSentimentResult(
                asset=asset,
                sentiment_score=sentiment_score,
                volatility_sigma=volatility_sigma,
                confidence=data["confidence"],
                rationale=data["rationale"],
                counter_argument=data["counter_argument"],
                is_idiosyncratic=data["is_idiosyncratic"],
                headline=headline,
            )
        except Exception as e:
            # Volledige fallback (28 aug 2026, op verzoek): een API-fout,
            # onverwachte responsvorm, of ontbrekend verplicht veld mag de
            # bot nooit laten crashen of tot een extreme actie leiden --
            # val terug op mu=0.0 (neutraal), sigma=0.5 (gematigde
            # onzekerheid), confidence=0.0 (telt vrijwel niet mee in de
            # confidence-gewogen aggregatie).
            print(f"[llm_sentiment] Analyse mislukt voor '{headline[:60]}...': {e} "
                  f"-- val terug op mu=0.0, sigma=0.5, confidence=0.0.")
            return LlmSentimentResult(
                asset=asset,
                sentiment_score=0.0,
                volatility_sigma=0.5,
                confidence=0.0,
                rationale="Analyse mislukt -- fallback-waarden gebruikt.",
                counter_argument="",
                is_idiosyncratic=False,
                headline=headline,
            )

    def analyze_batch(self, asset: str, headlines: List[str],
                       price_context: Optional[str] = None) -> List[LlmSentimentResult]:
        """
        Analyseert meerdere headlines na elkaar. Voor productiegebruik met
        veel nieuws per minuut: overweeg dit te async/parallelliseren
        (zie Gemini's advies over asyncio/aiohttp) i.p.v. sequentieel.
        """
        return [self.analyze_headline(asset, h, price_context) for h in headlines]

    @staticmethod
    def aggregate(results: List[LlmSentimentResult]) -> float:
        """
        Confidence-gewogen gemiddelde van meerdere LLM-scores tot één
        eindscore. Items waar het LLM zelf weinig vertrouwen in heeft
        (lage confidence) wegen minder zwaar mee.
        """
        if not results:
            return 0.0
        weighted_sum = sum(r.sentiment_score * r.confidence for r in results)
        weight_total = sum(r.confidence for r in results)
        return round(weighted_sum / weight_total, 3) if weight_total > 0 else 0.0

    @staticmethod
    def aggregate_with_decay(results: List[LlmSentimentResult],
                              published_timestamps: List[float],
                              half_life_hours: float = 1.5) -> float:
        """
        Zelfde als aggregate(), maar weegt elk item ook naar leeftijd --
        een headline van 3u50 binnen een 4-uur-venster telt anders mee
        dan eentje van 2 minuten oud (Gemini-feedback, 23 aug 2026; zelfde
        principe als cryptopanic_client.py's SENTIMENT_HALF_LIFE_HOURS,
        nu ook toegepast op de RSS+LLM-pipeline).

        results en published_timestamps moeten dezelfde lengte en volgorde
        hebben. half_life_hours=1.5 betekent: een item van 1.5 uur oud
        weegt nog voor 50% mee, na 3 uur voor 25%, etc.
        """
        if not results:
            return 0.0

        now = time.time()
        weighted_sum = 0.0
        weight_total = 0.0

        for result, published_at in zip(results, published_timestamps):
            age_hours = max(0.0, (now - published_at) / 3600.0)
            decay = math.pow(0.5, age_hours / half_life_hours)
            weight = result.confidence * decay

            weighted_sum += result.sentiment_score * weight
            weight_total += weight

        return round(weighted_sum / weight_total, 3) if weight_total > 0 else 0.0

    @staticmethod
    def aggregate_volatility_with_decay(results: List[LlmSentimentResult],
                                          published_timestamps: List[float],
                                          half_life_hours: float = 1.5) -> float:
        """
        Zelfde tijd-verval-gewogen aggregatie als aggregate_with_decay(),
        maar dan voor volatility_sigma i.p.v. sentiment_score (28 aug
        2026, voor het GBM-koersmodel). Als aparte methode toegevoegd
        i.p.v. de bestaande aggregate_with_decay() te wijzigen, om de
        bestaande aanroepen (main_orchestrator.py, regime_orchestrator.py)
        niet te breken -- die verwachten een enkele sentiment-float terug.
        """
        if not results:
            return 0.5  # zelfde neutrale fallback als bij een individuele analyse-mislukking

        now = time.time()
        weighted_sum = 0.0
        weight_total = 0.0

        for result, published_at in zip(results, published_timestamps):
            age_hours = max(0.0, (now - published_at) / 3600.0)
            decay = math.pow(0.5, age_hours / half_life_hours)
            weight = result.confidence * decay

            weighted_sum += result.volatility_sigma * weight
            weight_total += weight

        return round(weighted_sum / weight_total, 3) if weight_total > 0 else 0.5

    @staticmethod
    def aggregate_confidence_with_decay(results: List[LlmSentimentResult],
                                          published_timestamps: List[float],
                                          half_life_hours: float = 1.5) -> float:
        """
        Tijd-gewogen gemiddelde confidence over een batch headlines (28
        aug 2026, voor de flash-event-detectie) -- ALLEEN naar leeftijd
        gewogen (niet naar confidence zelf, om circulariteit te
        vermijden zoals bij de andere aggregate_*_with_decay-methodes).
        """
        if not results:
            return 0.0

        now = time.time()
        weighted_sum = 0.0
        weight_total = 0.0

        for result, published_at in zip(results, published_timestamps):
            age_hours = max(0.0, (now - published_at) / 3600.0)
            decay = math.pow(0.5, age_hours / half_life_hours)

            weighted_sum += result.confidence * decay
            weight_total += decay

        return round(weighted_sum / weight_total, 3) if weight_total > 0 else 0.0


if __name__ == "__main__":
    # Structuur-test zonder live API-call (vereist ANTHROPIC_API_KEY om echt te draaien)
    print("Tool-schema geldig JSON:", json.dumps(SENTIMENT_TOOL_SCHEMA, indent=2)[:200], "...")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\nGeen ANTHROPIC_API_KEY gezet -- skip live test.")
    else:
        engine = LlmSentimentEngine()
        result = engine.analyze_headline(
            asset="HBAR",
            headline="Google Cloud breidt node-netwerk op Hedera uit en lanceert nieuwe enterprise tools.",
            price_context="1u prijsactie: +2.4%, 24u volume: +150%",
        )
        print(f"\nScore: {result.sentiment_score}, confidence: {result.confidence}")
        print(f"Idiosyncratisch: {result.is_idiosyncratic}")
        print(f"Reden: {result.rationale}")
