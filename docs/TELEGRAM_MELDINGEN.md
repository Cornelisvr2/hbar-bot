# Telegram-meldingen van de HBAR-bot — overzicht

Wat de bot je kan sturen, gegroepeerd naar type. Kolom "actie" = of jij
iets moet doen. Stand 11 sep 2026, uit de code.

## 🟢 Routine — ter info, geen actie nodig

| Melding | Wanneer | Actie |
|---|---|---|
| 📅 Dagelijks statusrapport (saldo, positie, waarde, koers) | 1x per dag (09:00) | nee — je overzicht |
| ✅ Swap SUCCESS: HBAR_TO_USDC / USDC_TO_HBAR | bij elke swap voor de poolbalans | nee |
| ♻️ LP-positie geherbalanceerd: X HBAR + Y USDC | als de prijs uit range liep en de bot hercentreert | nee |
| 💰 Overtollig kapitaal bijgestort in positie | nadat jij hebt gestort en de bot het in de pool zet | nee |
| 🔧 Bij opstarten: vastzittende WHBAR hersteld naar HBAR | routineopschoning bij (her)start | nee |
| [fase] gewenst regime … (in de log, niet altijd Telegram) | elke cyclus | nee |

## 🔵 Fase & regime — de strategie schakelt

| Melding | Wanneer | Actie |
|---|---|---|
| Regime-overgang LP_MODE → BULLISH_REFLEX | bull bevestigd (7d boven MA200) → 100% HBAR | nee — dit wil je |
| Regime-schakelaar: LP-positie volledig geleegd | bij een schakeling die de pool sluit | nee, maar goed om te weten |
| Bot herstart — regimestatus hersteld | na een herstart/rebuild | nee |

## 🟠 Let op — meestal zelfherstellend, maar houd in de gaten

| Melding | Wanneer | Actie |
|---|---|---|
| ⚠️ LP-positie buiten range, genade-periode gestart | prijs buiten range, wacht vóór herbalanceren | nee, tenzij het blijft hangen |
| ⏱️/❌ rebalance_skipped (niet economisch / niet mogelijk) | herbalanceren nu te duur of tijdelijk geblokkeerd | nee — bewuste keuze van de bot |
| 🔁 [rpc] relay-hapering opgevangen (fallback) | een read-call faalde, bot wisselde van relay | nee — sinds de fallback zelfherstellend |

## 🔴 Fout — de bot vangt het af ("geen actie ondernomen"), maar lees mee

Allemaal via *HBAR Bot — FOUT* met de context erbij:

| Context | Betekenis | Actie |
|---|---|---|
| regime_loop: prijs ophalen | prijsbron (GeckoTerminal/pool) even niet bereikbaar | nee bij 1x; bij herhaling checken |
| regime_loop: USDC-balans / kapitaal bijstorten | balans/ storting-stap faalde | nee bij 1x |
| fee_underperformance_check: fees opvragen | fee-uitlezing (collect) gaf lege bytes | nee — fallback vangt dit nu op |
| regime_loop: volatiliteitsregime verversen | volatiliteitsberekening faalde | nee bij 1x |
| Swap … mislukt | een swap ging niet door | ja bij herhaling — kan geld raken |

## 🚨 Urgent — hier moet je (mogelijk) ingrijpen

| Melding | Betekenis | Actie |
|---|---|---|
| 🚨 USDC-DEPEG-NOODSTOP | USDC verliest z'n $1-koppeling → bot sluit alles naar HBAR en stopt (DEPEG_HALT) | JA — controleer, hervat met /resume als veilig |
| 🚨 trade-proces direct gecrasht (dispatch-guard) | een gestart trade-proces stierf meteen | JA — er is iets stuk |
| ❌ ZOWEL TP als SL plaatsen mislukt — positie ONBESCHERMD | een positie staat zonder stop-loss | JA — handmatig ingrijpen |

## Commando's die JIJ naar de bot kunt sturen
- `/resume` — hervat na een DEPEG_HALT of pauze
- (komend, via dashboard i.p.v. Telegram: start/stop, swap, in/uit pool, "DIT IS DE BULL")

## Aanbevolen: filteren
De routine- en fout-bij-1x-meldingen zijn veel. Overweeg voor de rust:
- routine (swaps, herbalanceringen) samenvatten in het dagrapport i.p.v. per stuk;
- alleen 🟠/🔴/🚨 los pushen.
Dat is een instelbare keuze; nu krijg je vrijwel alles.
