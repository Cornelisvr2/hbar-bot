"""
self_calibration_model.py

Zelflerende feedback-loop (28 aug 2026): meet hoe goed de voorspelde
(LLM-geaggregeerde) volatiliteit overeenkwam met de daadwerkelijk
gerealiseerde marktvolatiliteit, en past de kalibratiefactor traag en
veilig aan -- NIET de LLM-scores zelf (die blijven puur tekst-
classificatie), maar de WISKUNDIGE VERTALING daarvan (zie
implementatie-valkuilen hieronder).

BELANGRIJKE VEILIGHEIDSMAATREGELEN (letterlijk overgenomen uit het
voorstel, want dit zijn reele, welbekende risico's bij zelflerende
systemen):
1. Trage learning rate -- past pas aan na tientallen/honderden
   datapunten, niet na een enkele observatie (voorkomt overfitting op
   toevallige correlaties, bv. een Musk-tweet die toevallig samenviel
   met een ongerelateerde whale-verkoop).
2. Laat het LLM de TEKST scoren (0-1), laat de wiskundige laag de
   VERTALING naar percentages/tijd-decay optimaliseren -- niet de
   ruwe LLM-scores zelf aanpassen.
3. Harde, absolute grenzen (hardcoded, niet zelf aan te passen door het
   leerproces) tegen "exploderende" ranges.
"""

import math
from dataclasses import dataclass
from typing import List, Optional

# Veiligheidsmaatregel 1: trage learning rate, en een MINIMUM aantal
# datapunten voordat er uberhaupt wordt aangepast.
MIN_DATAPOINTS_BEFORE_CALIBRATION = 30
LEARNING_RATE = 0.02  # hoe sterk elke aanpassing doorwerkt, klein = traag/voorzichtig

# Veiligheidsmaatregel 3: harde, absolute grenzen -- de kalibratiefactor
# kan de effectieve sigma-multiplier NOOIT verder dan dit laten afwijken
# van de ongekalibreerde basiswaarde (1.0), ongeacht wat het leerproces
# "zou willen".
MIN_CALIBRATION_FACTOR = 0.5   # kan de sigma-multiplier max HALVEREN
MAX_CALIBRATION_FACTOR = 2.0   # kan de sigma-multiplier max VERDUBBELEN


@dataclass
class CalibrationDataPoint:
    predicted_sigma: float  # de geaggregeerde volatility_sigma op moment t
    realized_sigma: float   # de daadwerkelijk gemeten prijsvolatiliteit over het venster erna
    timestamp: float


@dataclass
class CalibrationResult:
    calibration_factor: float
    mean_squared_error: float
    n_datapoints: int
    is_calibrated: bool  # False zolang er te weinig datapunten zijn (blijft dan op 1.0)


def compute_calibration_factor(history: List[CalibrationDataPoint],
                                 current_factor: float = 1.0) -> CalibrationResult:
    """
    Berekent een nieuwe kalibratiefactor op basis van de volledige
    geschiedenis van (voorspelde, gerealiseerde)-paren.

    Als de voorspelde sigma consequent HOGER is dan de gerealiseerde
    (de bot is "te paniekerig"), daalt de factor -- en omgekeerd.

    history: ALLE bekende datapunten tot nu toe (niet slechts de
        laatste) -- MSE en de gemiddelde bias worden over de volledige
        geschiedenis berekend, wat vanzelf een dempend, traag effect
        geeft naarmate er meer data bijkomt (een enkel nieuw, afwijkend
        datapunt verschuift het gemiddelde nauwelijks meer bij honderden
        bestaande punten).
    """
    n = len(history)

    if n < MIN_DATAPOINTS_BEFORE_CALIBRATION:
        # Veiligheidsmaatregel 1: te weinig data, blijf op de
        # ongekalibreerde basiswaarde.
        mse = (
            sum((p.realized_sigma - p.predicted_sigma) ** 2 for p in history) / n
            if n > 0 else 0.0
        )
        return CalibrationResult(
            calibration_factor=1.0, mean_squared_error=mse,
            n_datapoints=n, is_calibrated=False,
        )

    mse = sum((p.realized_sigma - p.predicted_sigma) ** 2 for p in history) / n

    # Gemiddelde bias: positief betekent "voorspelling was gemiddeld te
    # hoog" (te paniekerig), negatief betekent "te laag" (te
    # zelfgenoegzaam).
    mean_bias = sum(p.predicted_sigma - p.realized_sigma for p in history) / n

    # Kleine, voorzichtige aanpassing in de richting die de bias verkleint.
    adjustment = -LEARNING_RATE * mean_bias
    new_factor = current_factor + adjustment

    # Veiligheidsmaatregel 3: harde grenzen, ongeacht wat het leerproces
    # "zou willen".
    new_factor = max(MIN_CALIBRATION_FACTOR, min(MAX_CALIBRATION_FACTOR, new_factor))

    return CalibrationResult(
        calibration_factor=new_factor, mean_squared_error=mse,
        n_datapoints=n, is_calibrated=True,
    )
