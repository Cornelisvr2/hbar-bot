"""
flash_event_model.py

Detecteert plotselinge, mogelijk toxische sentiment-sprongen (pump/dump-
achtige patronen) op basis van de AFGELEIDE van het sentiment (d(mu)/dt)
i.p.v. het absolute niveau (28 aug 2026).

Logica: een sentiment-score die binnen een kort tijdvenster hard
verschuift, GECOMBINEERD met lage LLM-confidence (een enkel, vaag of
tegenstrijdig bericht in plaats van brede, betrouwbare consensus), is
een aanwijzing voor een kortstondige, mogelijk manipulatieve gebeurtenis
-- niet voor een genuine, betrouwbare marktverschuiving.
"""

from dataclasses import dataclass

# Drempels, expliciet instelbaar -- AANNAME, geen empirisch geijkte
# waarde (net als de rest van dit voorstel).
DELTA_SENTIMENT_THRESHOLD = 0.6  # verandering binnen het venster
CONFIDENCE_THRESHOLD = 0.5  # ONDER deze waarde is verdacht


@dataclass
class FlashEventResult:
    is_flash_event: bool
    delta_sentiment: float
    confidence: float


def detect_flash_event(previous_score: float, current_score: float,
                         current_confidence: float) -> FlashEventResult:
    """
    previous_score/current_score: de geaggregeerde sentiment-score bij de
        vorige, resp. huidige sentiment-verversing (elke
        SENTIMENT_REFRESH_SECONDS, standaard 5 minuten -- dit dient dus
        automatisch als het "5-minuten-venster" uit het voorstel, zonder
        een aparte, continue tijdreeks te hoeven bijhouden).
    current_confidence: de (confidence-gewogen) betrouwbaarheid van de
        headlines die de HUIDIGE score bepaalden.
    """
    delta_sentiment = current_score - previous_score

    is_flash_event = (
        abs(delta_sentiment) > DELTA_SENTIMENT_THRESHOLD
        and current_confidence < CONFIDENCE_THRESHOLD
    )

    return FlashEventResult(
        is_flash_event=is_flash_event,
        delta_sentiment=delta_sentiment,
        confidence=current_confidence,
    )


# Mean-reversion-detectie (28 aug 2026, op verzoek) -- als sentiment na
# een eerder gedetecteerde flash-event snel TERUGKEERT naar het oude
# niveau (bv. het nieuws bleek nep, of de markt corrigeert de
# overreactie), is dit een aanwijzing dat de crash/pump een overreactie
# was, geen genuine trendverandering. AANNAME, geen empirisch geijkte
# waarde.
MEAN_REVERSION_THRESHOLD = 0.7  # hoeveel van de oorspronkelijke sprong al is teruggedraaid


@dataclass
class MeanReversionResult:
    is_mean_reversion: bool
    reversion_fraction: float  # 0.0-1.0+, hoeveel van de oorspronkelijke sprong is teruggedraaid


def detect_mean_reversion(pre_event_score: float, event_score: float,
                            current_score: float) -> MeanReversionResult:
    """
    pre_event_score: het sentiment-niveau VOOR de gedetecteerde
        flash-event (dus de "previous_score" die destijds aan
        detect_flash_event() werd meegegeven).
    event_score: het sentiment-niveau TIJDENS de flash-event zelf.
    current_score: het HUIDIGE, meest recente sentiment-niveau.
    """
    original_jump = event_score - pre_event_score
    if abs(original_jump) < 1e-9:
        return MeanReversionResult(is_mean_reversion=False, reversion_fraction=0.0)

    current_reversion = event_score - current_score  # hoeveel is teruggedraaid, in dezelfde richting als origineel
    reversion_fraction = current_reversion / original_jump if original_jump != 0 else 0.0

    is_mean_reversion = reversion_fraction >= MEAN_REVERSION_THRESHOLD

    return MeanReversionResult(
        is_mean_reversion=is_mean_reversion,
        reversion_fraction=reversion_fraction,
    )
