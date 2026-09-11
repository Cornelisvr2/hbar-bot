# Conclusie nieuws-analyse (11 sep 2026) — wat de 2 jaar data zegt

Na de volledige backfill (2 jaar candles + ~10.000 geclassificeerde koppen),
de event-study en de inzoom-analyse (nieuws_inzoom.py: korte horizons,
event-clustering, hit-rate per regime) is dit de harde uitkomst. Bedoeld om
de volgende sessie NIET opnieuw naar losse-nieuws-signalen te laten zoeken.

## Wat NIET werkt: reactief traden op crypto-nieuwscategorieën

Adoptie, listing, regulering, hack (BTC-kant): allemaal grotendeels een
LAGGING indicator. Bewijs uit de events zelf:
- Op dagen dat de markt tóch al bewoog, verschenen meerdere koppen die
  ALLEMAAL de dagbeweging toegewezen kregen (bv. 3 mrt: 4 adoptie-koppen
  allemaal -2,40; 21 mei: 4 koppen allemaal +1,62). Het nieuws beschrijft de
  beweging, veroorzaakt hem niet.
- Richting is inconsistent: MicroStrategy koopt 1M BTC → +2, maar Schwab
  lanceert crypto trading → -1,3; Trump reserve → +1,6, Block bank charter
  → -1,3. Geen bruikbare logica.
- De eerdere "signalen" (adoptie +0,32/66%, HBAR listing "sell the news")
  waren artefacten van clustering-op-dag + categorievervuiling (ETF-nieuws
  belandde in 'listing', hackdag-koppen in meerdere categorieën) + een paar
  grote uitschieters. Houden geen stand na inspectie.
- Bevestigt de allereerste kalibratie (10 sep): LLM-richtingsscore had ~0
  voorspelkracht op 1-4u. De reden is nu duidelijk: nieuws loopt achter de
  koers aan.

Gevolg: de REACTIEVE override uit het oude V4-plan (sectie 7a: bij een grote
gebeurtenis snel schakelen) is GESCHRAPT. Er is geen crypto-nieuwscategorie
die de koers betrouwbaar vóór is.

## Wat WEL werkt: geplande momenten (de kalender)

`macro_fed` is de enige categorie met een echt, niet-lagging signaal:
+0,18σ / 71% hit op 15 min (bear-dagen 72%). De reden dat juist deze wél
werkt: Fed/CPI/FOMC zijn GEPLANDE, plotselinge gebeurtenissen — de markt
reageert op het moment zelf, dus de reactie komt ná het nieuws i.p.v.
ervoor. Dat is precies waar een strategie op kan handelen.

→ De kalender (laag 7, event_guard) is de kern. Die draait al defensief
  (geen nieuwe reflex-entries ±2u rond high-impact events). De ANTICIPERENDE
  variant (V4-plan 7b: vóór het cijfer naar USDC, daarna schakelen op de
  verrassing = uitkomst vs. verwachting uit event_calendar) is de juiste
  uitbouw en de enige nieuws-gedreven strategie die de data steunt.

## Wat een KANDIDAAT blijft: HBAR-hackdefensie

HBAR hack_security na clustering: 4 echte events sinds maart, maar consistent
(60m: 100% hit, 120m: -1,47σ / 100%). Te weinig om nu op te bouwen. Actie:
verzamelen; her-evalueren zodra er >= 15-20 losse hack-events zijn. Dit is
een risico-guard (uit HBAR bij een ecosysteem-hack), geen alfa-strategie.

## Openstaand technisch werk dat de conclusies raakte

1. Categorie-vervuiling: de LLM-classificatie labelt ETF-nieuws als
   'listing', en hackdag-koppen lekken over categorieën. Voor de
   event-study (aggregatie per categorie) moet dit schoner. Optie: strengere
   prompt (ETF ≠ listing) OF trefwoord-herindeling achteraf.
2. event_key-clustering zit nu alleen in nieuws_inzoom.py (analyse), niet in
   event_study.py (die de news_weights vult). Als news_weights ooit de bot
   voedt, moet de clustering daarheen.

## Richting vooruit (bouwvolgorde)

1. Kalender-anticipatie (V4 7b) uitwerken en backtesten op de 2 jaar
   event_calendar + candles: vóór high-impact events naar USDC, schakelen op
   de verrassing. Dit is nu de hoofdstrategie voor nieuws/macro.
2. Fasestrategie (V4 secties 1-3): bull→HBAR, bear→USDC, sideways→pool, op de
   bestaande macro-analyse. Backtest go/no-go: > kale pool (€2.577).
3. Hackdefensie: laten verzamelen, later.
4. Reactieve nieuws-override: geschrapt, niet meer bouwen.
