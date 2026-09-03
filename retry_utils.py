"""
retry_utils.py

Generieke retry-met-backoff-decorator (28 aug 2026), gebouwd naar
aanleiding van herhaalde 502/RemoteDisconnected-fouten van
testnet.hashio.io en (incidenteel) GeckoTerminal.

BELANGRIJK: uitsluitend bedoeld voor LEESOPERATIES (prijs ophalen,
saldo checken, on-chain state lezen) -- NOOIT toepassen op
transactie-VERSTUUR-operaties. Een 502 tijdens het versturen van een
transactie kan betekenen dat de transactie WEL is aangekomen en alleen
het antwoord verloren ging; blind opnieuw proberen zou dan tot een
dubbele actie kunnen leiden. Voor schrijfoperaties die mislukken is
altijd EERST verifiëren wat de daadwerkelijke, on-chain staat is de
juiste aanpak (zie _reconcile_lp_position_on_startup() als bestaand
voorbeeld van dat patroon), niet blind herhalen.
"""

import time
import functools


def retry_with_backoff(max_retries: int = 3, base_delay: float = 2.0,
                         exceptions: tuple = (Exception,)):
    """
    Decorator: probeert de functie tot max_retries keer, met exponentieel
    oplopende wachttijd ertussen (base_delay, base_delay*2, base_delay*4, ...).
    Geeft de LAATSTE fout door als alle pogingen mislukken.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        print(f"[retry] {func.__name__}: poging {attempt + 1}/{max_retries} "
                              f"mislukt ({e}), probeer opnieuw over {delay:.0f}s...")
                        time.sleep(delay)
            raise last_exception
        return wrapper
    return decorator
