# Dashboard-blauwdruk + scripts (12 sep 2026)

Voorbereiding voor de bouw van het nieuwe dashboard. Nog GEEN werkende
dashboard-code -- dat is de volgende (verse) sessie. Dit is de spec + de
losse analyse-scripts die het dashboard straks als databron gebruikt.

## Bestanden
- BOUWSPEC_DASHBOARD.md  -- de volledige bouwspec (login, blokken, bediening,
  2-factor, herinvesteer-systeem, voorspelling, calculator). Leidend document.
- TELEGRAM_MELDINGEN.md  -- overzicht van alle Telegram-meldingen + 3 niveaus.
- apr_historie.py        -- fee-APR-spreiding (p25/mediaan/p75) uit
  GeckoTerminal-volume. Voedt de voorspelling. Draaien:
  docker compose run --rm -T hbar-bot python3 apr_historie.py
- stortingen_teller.py   -- MoonPay-stortingen + koers-op-datum -> echte inleg.
- kosten_teller.py       -- gas/kosten uit de Mirror Node (ontdubbeld).

## Al LIVE doorgevoerd deze sessie (niet in deze bundel, zit in de bot)
- Fase-strategie live (MACRO_ENABLED-schakelaar, fase_signaal.py)
- Relay-fallback voor read-calls
- Macro/nieuws-LLM-laag UIT (MACRO_ENABLED=false)

## Volgende sessie: bouwen
Zie BOUWSPEC_DASHBOARD.md. Bouwvolgorde: 1) lees-architectuur (bot schrijft
status weg), 2) login via Telegram-goedkeuring, 3) blokken, 4) bediening met
2-factor. Geld-knoppen als laatste, getest voor live.
