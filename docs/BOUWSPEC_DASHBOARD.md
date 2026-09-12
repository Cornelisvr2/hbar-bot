# Bouwspec: nieuw dashboard + bediening (volgende sessie)

Vastgelegd 11 sep 2026, bijgewerkt met alle ontwerpkeuzes. Alles is besloten;
bouwen gebeurt in een verse sessie, zorgvuldig — dit beweegt echt geld.

## 1. Architectuur
- Dashboard doet GEEN live on-chain calls bij laden (oorzaak traagheid).
  De BOT schrijft elke cyclus de status weg (JSON/DB); dashboard leest dat.
- Login via TELEGRAM-GOEDKEURING: username invullen -> bot stuurt Telegram
  "inlogverzoek om HH:MM vanaf <herkomst>, [Goedkeuren] [Weigeren]" ->
  na Goedkeuren ben je in. Geen wachtwoord. Verzoek verloopt na 2 min.
  Werkt omdat alleen jouw TELEGRAM_CHAT_ID het verzoek krijgt.
- Alles over HTTPS (Caddy staat al).

## 2. Weergave (definitief)
KPI-rij: HBAR-stapel (muntjes) · totale waarde USDC · ingelegd (EUR->USDC) ·
netto fees · HBAR-koers.

Koersgrafiek met MA200-lijn. Marktstemming (S&P/BTC/HBAR + "HBAR volgt BTC 0,66").
"Wat de bot nu doet" + fasekompas.

SPLITSING:
- WALLET (los saldo, telt mee in totale waarde): eigen helder blok met een
  TOTAAL bovenaan ($) en per token een regel met AANTAL + WAARDE in USDC
  (het oude blok liet de waarde weg). Generiek uit de Mirror Node: HBAR,
  USDC, SAUCE (LARI-airdrop, grijs als 0), overige tokens met saldo > 0.
  HINT tonen als er meer dan de bijstort-drempel (~100 HBAR) los staat:
  "de bot voegt dit bij de volgende cyclus toe aan de pool" -- verklaart
  waarom er los saldo is en wat ermee gebeurt. Bevat ALLEEN wallet, geen
  positie-regels (die horen in het pool-blok).
- POOLS: een generieke LIJST van pool-blokken (nu 1 pool, klaar voor meer --
  de eigenaar wil later in meerdere pools). Elk pool-blok toont:
  * inhoud (bv. HBAR + USDC), range met een RUSTIGE BALK (variant B):
    neutrale grijze balk, rand-zones (~15% aan elke kant) subtiel geel
    gemarkeerd als waarschuwingszone, en één duidelijke donkere marker op de
    huidige prijs. Zo zie je meteen of de prijs veilig in het midden of in de
    gevarenzone bij de rand staat, zonder percentages te hoeven lezen.
  * opgebouwde fees van de HUIDIGE positie (niet-geoogst, reset bij
    herbalancering) -- PER TOKEN getoond (bv. 0,003 HBAR + 0,12 USDC = $0,27)
    uit de collect-uitlezing (fee0/fee1). TELT MEE in de totale waarde, MITS
    die niet al in de positiewaarde zit (bij bouw verifiëren: SaucerSwap V2
    houdt niet-geclaimde fees meestal apart -> dan erbij optellen, anders
    niet, om dubbeltelling te voorkomen).
  * fee-APR (swap) + reward-APR (LARI) los ernaast (reward niet opgeteld)
  * REWARD-OVERZICHT per pool: welke reward-token(s) deze pool geeft, PER
    token: opgebouwde/ontvangen hoeveelheid (uit wallet-airdrops), actuele
    prijs, waarde in USDC, en verwacht per epoch (schatting uit
    our_reward_per_epoch_usd). Generiek ophalen uit de LARI-data van de pool
    zodat het klopt welke reward-token het ook is (kan per pool verschillen,
    niet per se SAUCE).
Totale waarde = wallet los + som van alle pool-posities. Totaal rendement telt
op over alle pools + wallet.

BELANGRIJK bouwvolgorde: het DASHBOARD wordt nu multi-pool-KLAAR gemaakt (de
weergave, een lijst i.p.v. 1 vast blok). De BOT zelf handelt voorlopig in 1
pool; daadwerkelijk in meerdere pools handelen is een apart, veel groter
strategie-project voor later, GEEN dashboard-taak.

LARI openstaand: apart blok, "te oogsten" bedrag + status. Telt NIET mee voor
rendement tot geoogst (dan zit het in wallet-SAUCE of in de pool). Toon of
herinvesteren AAN/UIT staat (staat nu UIT: min $10, MA 7d, max 30d -> rewards
worden nu niet automatisch geoogst). OPEN BESLISSING: herinvestering aanzetten?

Totale waarde = wallet los + pool. (LARI openstaand erbuiten.)

Kosten & rendement: fees verdiend totaal (+142 HBAR), gas betaald (Mirror Node,
ontdubbeld), echt rendement in USDC.

Kalender (grote events), marktnieuws (σ-reactie, "stuurt bot niet"), botactiviteit.

## 3. Ingelegd / echt rendement (in EUR, weergegeven in USDC)
- Chain kent alleen binnengekomen HBAR, niet wat je in EUR betaalde aan MoonPay.
- Daarom: bot detecteert MoonPay-storting (van 0.0.7302893), schat HBAR x koers
  + rondt naar heel EUR-bedrag, en vraagt via Telegram: "Storting X HBAR ≈ $Y.
  Betaald: €Z? [Ja] [Ander bedrag]". Jij bevestigt met 1 tik.
- "Ingelegd" = som van bevestigde EUR-betalingen x EUR/USD-koers van die dag.
  Echt rendement = huidige totale waarde - ingelegd. Klopt met wat er van de
  rekening ging, incl. MoonPay-fee.
- Geen reactie -> voorlopig de koers-schatting, opnieuw vragen later.
- BIJ EERSTE RUN: de twee bestaande stortingen (2717,8 HBAR 4 sep; 4145,0 HBAR
  11 sep) met terugwerkende kracht als Telegram-vraag sturen (gok €200 / €300),
  zodat de historie klopt en de flow meteen testbaar is.

## 4. Bedieningsknoppen (hergebruiken bestaande geteste functies)
- Play / Pauze -> command_state.paused (bestaat al)
- DIT IS DE BULL -> pool sluiten + 100% HBAR, auto-fase pauzeren
- NOODUITSTAP -> pool sluiten + alles naar USDC + pauze (handmatig; crash-stop
  automatiseren kostte muntjes in de backtest, elke drempel negatief vs pool)
- Crash-bescherming NIET automatisch (besloten).

## 5. Beveiliging: Telegram-2-factor op ALLE knoppen
Knop -> Telegram "bevestig <actie>, [Ja]/[Nee]" (2 min geldig) -> na Ja voert
de bot uit. Zelfde mechaniek als de login. (Op play/pauze wat omslachtig maar
zo besloten; bij bouw makkelijk te differentiëren.)

## 6. Notificaties: 3 niveaus (instelbaar)
ALLES / BELANGRIJK / ALLEEN URGENT. Per knop-actie: aangevraagd -> bevestig in
Telegram -> uitgevoerd (details) / mislukt (reden, positie ongewijzigd).
Volledig overzicht: TELEGRAM_MELDINGEN.md.

## 7. Los op de lijst
- Herbalancering rustiger afstellen (195 tx = 111 HBAR gas vs +142 fees; breder
  + minder herbalanceren wint, bewezen in backtest_pool_muntjes).
- Beslissing: LARI-herinvestering aan/uit.

## 8. Slim herinvesteren van LARI-SAUCE en losse HBAR (nieuw, 11 sep)

Probleem: LARI-rewards komen per epoch als los SAUCE-saldo in de wallet
(airdrop, geen "oogsten" nodig). Losse SAUCE/HBAR levert niets op tot het
terug in de pool zit. Maar de MIN_DEPLOYABLE_CAPITAL_HBAR-drempel (~100 HBAR
inzetbaar, ~150 in wallet want ~50 gas-reserve) houdt losse bijstortingen
tegen om te voorkomen dat de bot bij elk klein bedrag herbalanceert (elke
herbalancering ~1 HBAR gas). Gevolg nu: rewards blijven nutteloos liggen, en
de oude 30-dagen-noodklep swapt kleine bedragen tegen volle gaskost.

Nieuw systeem:
1. MIN_DEPLOYABLE_CAPITAL_HBAR-drempel BLIJFT voor gewone losse stortingen
   (voorkomt gas-verspilling bij kleine bedragen).
2. BIJ ELKE HERBALANCERING (het gas is dan toch al betaald):
   - losse HBAR -> altijd mee de pool in, ongeacht de drempel (geen swap
     nodig, HBAR is al de juiste token).
   - SAUCE en andere tokens -> alleen mee als de swap het WAARD is, PER
     TOKEN (elke token is een aparte swap met eigen fee+gas):
       swap alleen als (actuele swapkost gas+fee in $) < X% van de
       tokenwaarde. Standaard X = 1%.
     Dus bij $0,08 swapkost is de effectieve drempel ~$8; wordt gas duurder
     of daalt HBAR (Hedera-fee is vast in $, kost dus meer HBAR-muntjes als
     HBAR laag staat), dan schuift de drempel vanzelf omhoog. Per token, niet
     het totaal: 3 tokens van elk $4 blijven allemaal staan (elke swap apart
     niet de moeite); pas als één token individueel boven de drempel komt
     gaat alleen die mee. Bot haalt actuele gaskost + koers toch al op, dus
     geen vaste drempel meer te heroverwegen -- klopt altijd met de
     werkelijke kost op dat moment.
3. ACHTERVANG voor als er lang niet geherbalanceerd wordt: als swapkost <
   X% van de SAUCE-waarde EN koers op/boven 7d-gemiddelde -> alsnog een losse
   herinvestering (zelfde dynamische drempel als punt 2, i.p.v. de oude vaste
   $10).
4. De oude 30-dagen-mini-verkoop VERVALT (swapte kleine bedragen te duur).

Resultaat: HBAR nooit nutteloos vastgehouden; SAUCE alleen geswapt als het de
fee waard is; geen swap ooit voor een bedrag waar de fee het opeet.
Bouwen: raakt de herbalanceer-kernlogica -> eerst backtesten (hoeveel SAUCE
kwam er terug in de pool vs de huidige uit-stand), dan schaduw, dan live.

## Correctie LARI-weergave (t.o.v. sectie 2)
LARI = airdrop per epoch, komt automatisch als los SAUCE in de wallet -> staat
dus al in het WALLET-blok en telt mee. GEEN apart "te oogsten"-blok nodig.
Wel tonen: LARI-APR (indicatie reward/epoch) + of herinvesteren aan/uit staat.

## 9. Voorspelling — opgesplitst in twee segmenten (11 sep)

De huidige "Voorspelling bij aanhoudende APR" ($541/$616/$748 over 30/90/180d)
rekent dagelijks samengesteld op de 7-daags fee-APR + LARI-APR. GOED als basis,
maar hij vermengt stilzwijgend twee dingen: fee-groei EN de aanname dat de
koers gelijk blijft. Splitsen:

### 9a. POOL-SEGMENT (nu bouwen) -- puur de pool in MUNTJES, geen koers, geen $
Alleen wat de pool/positie oplevert, uitgedrukt in MUNTJES (geen $-waarde --
die hoort in de scenario's). Drie rijen op basis van de HISTORISCHE fee-APR-
SPREIDING (niet één getal):
- LAAG = 25e percentiel, MIDDEN = mediaan, HOOG = 75e percentiel van de
  dagelijkse fee-APR over ~365 dagen. Bron: apr_historie.py -- reconstrueert
  de fee-APR per dag uit GeckoTerminal-dagvolume + SaucerSwap-formule
  compute_fees_apr (bot bewaart APR niet historisch). Gemeten (11 sep, tier
  0,15%): laag ~19% / mediaan ~37% / gem ~58% / hoog ~78%. Gebruik MEDIAAN als
  "midden" (niet het rekenkundig gemiddelde -- dat wordt opgeblazen door een
  paar drukke dagen; APR-verdeling is scheef).
- Per rij: verwachte toename HBAR + reward-tokens (fee+LARI in muntjes) over
  30/90/180 dagen, dagelijks samengesteld, zonder stortingen, met APR-% erbij.
- Kanttekening: TVL-benadering is de huidige waarde -> absolute % indicatief,
  maar de SPREIDING (laag/hoog) is betrouwbaar.
Herbruikbaar in de scenario's: pure muntjes-groei, los van de koers.

### 9b. SCENARIO-SEGMENT (later) -- bouwt VOORT op 9a
Neemt de pool-groei uit 9a en zet er koersscenario's overheen die de eigenaar
kiest (koers gelijk / bull +X% / bear -Y%), + MA200 als trendcontext. Toont de
verwachte totale walletwaarde per scenario. Eén voorspeld koersgetal doen we
NIET (koers is bewezen niet voorspelbaar); scenario's wel.

## 10. Extra live-metrics + log-herindeling (11 sep)

Het losse "Transactiegeschiedenis"-blok (totale kosten/fee-inkomsten 30d)
VERVALT als apart blok -> naar de LOG-sectie onderaan. NB gemeten "kosten 30d"
= 114,6 HBAR, bijna gelijk aan totaal-sinds-begin 111 HBAR (bijna alle tx in
de laatste 30d, of de 30d-afbakening klopt niet -> bij bouw checken).

### Indeling (alles tonen, maar geordend naar hoe vaak je kijkt)
KPI-rij bovenaan (ongewijzigd): stapel, totale waarde, ingelegd, netto fees, koers.

NIEUWE "Statistiek"-sectie (inzoomen als je wilt):
- Tijd in-range vs out-of-range (7d/30d) -- verdiende de positie echt fees?
- Netto muntjes-groei (7d/30d) -- kern-KPI als trend, los van koers.
- Aantal herbalanceringen (30d) + gemiddelde gaskost per stuk.
- Dagen sinds laatste herbalancering.
- Impermanent loss tot nu toe (in muntjes) -- wat de pool kostte vs hodl.
- Pool vs vasthouden -- heeft de strategie muntjes opgeleverd?
- Fee-opbrengst per dag -- klein grafiekje (goede/slechte dagen, trend).

BIJ DE BOTSTATUS (bij het fasekompas):
- Afstand tot bull-omschakeling: "nog X% + N dagen boven MA200" -- maakt
  "wachten op de bull" concreet.

LOG-sectie onderaan (nu deels leeg -> vullen):
- Transactie/kosten-blok (hierheen verplaatst).
- Swap-balans: de swaps die nu leeg zijn -> vullen (elke swap met richting,
  bedrag, resultaat).
- Fouten: nu leeg -> vullen met de FOUT-meldingen (zie TELEGRAM_MELDINGEN.md).
- Activiteitenlijst.


## 11. Macro/nieuws-laag UIT — dashboard-gevolgen (11 sep)

De macro/nieuws-LLM-laag is uitgezet (MACRO_ENABLED=false): stuurde niets
(fase-strategie stuurt), kostte ~$10-15/mnd aan Anthropic-credits. Enige
LLM-gebruik in de live bot zat hier; nu geen doorlopend credit-verbruik meer.
Analyse-scripts (backfill_nieuws, event_study, kalibratie) blijven los
bruikbaar, kosten alleen iets als je ze handmatig draait.

Dashboard-gevolgen:
- WEG: "Marktnieuws"-blok (σ-reactie) -- geen databron meer.
- WEG: macro-analyse-blok (score, drift-multiplier, uitlijning, schaduw).
- BLIJFT: marktstemming (S&P/BTC/HBAR) -- pure koersdata, geen LLM.
- BLIJFT: cyclus-context (halving-positie, MA200-trend) -- koersdata.
- BLIJFT: kalender (CPI/FOMC/NFP) -- komt van macro_data_loader (FRED +
  Forex Factory) via aparte dagelijkse cron, staat LOS van de nieuws-laag,
  geen LLM, blijft gewoon werken.

Nog te doen (opruim-taak, apart): de macro/nieuws-CODE echt verwijderen
(rss/messari-clients, LlmSentimentEngine, macro_regime_model, en de
combined_score/macro_regime-doorgifte naar het GBM-model). Nu alleen veilig
UITGEZET; de volledige verwijdering raakt de kernlogica en gebeurt met de
code compleet voor ons, getest vóór live.

## 12. Scenario-CALCULATOR (vervangt het oude scenario-blok, 12 sep)

Het oude scenario-blok (grafiek + 8-koloms-tabel + dichte voetnoot, 3
scenario's tegelijk) was onleesbaar. Vervangen door een interactieve
CALCULATOR waarmee de eigenaar zelf speelt. HODL/vasthouden-vergelijking
VERVALT (we weten dat de bot beter presteert).

INVOER (met een BEREKEN-knop; pas op klik rekenen):
- HBAR-piekprijs: schuif van $0,15 (bear-piek) tot $0,40 (bull-piek).
- Periode: knoppen 6 / 12 / 24 / 48 maanden.
- Bijstorting per maand: vrij invoerveld in EUR (bv. 100).

TWEE GESCHEIDEN STAPPEN (eerlijkst: bot bepaalt muntjes, markt bepaalt waarde):

STAP 1 -- HOEVEEL MUNTJES SPAAR IK? (het betrouwbare deel)
Invoer: Fee-APR (knoppen laag 19% / midden 37% / hoog 78% uit apr_historie.py,
of vrij veld), Periode (12/24/48m), Bijstorting €/maand (vrij veld).
Uitkomst: HBAR-stapel in MUNTJES (huidige stapel + dagelijks samengestelde
fee-groei op de APR + maandstortingen als DCA). Hangt af van bot + stortingen,
NIET van koersgok -> staat apart en eerst.

STAP 2 -- WAT IS DIE STAPEL WAARD? (de koersaanname, waar de onzekerheid zit)
Invoer: HBAR-prijs-schuif ($0,05 -- $0,40, met "nu" gemarkeerd).
Uitkomst: Totale waarde (stapel x prijs) groot, met een VERHOUDINGSBALK
eronder die de eindwaarde splitst in ingelegd vs winst:
  - Ingelegd: $-bedrag + als % VAN DE WAARDE (bv. 29%)
  - Winst (waarde - ingelegd): $-bedrag + als % VAN DE WAARDE (bv. 71%), groen
De balk verschuift live met de prijs (lagere prijs -> groter inleg-aandeel).
De muntjes uit stap 1 veranderen NIET als je aan de prijs draait -- alleen de
waarde en de verhouding. Zo zie je apart wat de bot doet en wat de markt doet.

Dagelijks samengesteld (zoals een daily-compound-calculator), maar de "rente"
is fee-opbrengst in MUNTJES, niet dollars -> APR groeit de stapel, prijs zet
om naar waarde. Open keuzes: APR/prijs als schuif of vrij veld; optioneel
klein verloop-grafiekje van de muntjes-groei.

## 13. Impermanent loss — de olifant, eerlijk in beeld (12 sep)

IL is de keerzijde van de fees: in een trend verkoopt/koopt de pool je HBAR
onderweg, dus je houdt minder muntjes over dan HODL. Voor het muntjes-doel is
de kernvraag altijd: WINNEN DE FEES VAN DE IL? Dat moet het dashboard eerlijk
tonen, niet verstoppen.

### 13a. Op het dashboard -- GEMETEN, geen formule
Toon IL als het echte verschil "pool vs vasthouden" in MUNTJES (niet de
theoretische IL-formule, die verwart -- die vergelijkt met 50/50-hold, niet
met alles-in-HBAR-hold). Naast elkaar, zodat het eerlijk is:
- IL: verschil in muntjes t.o.v. HODL, als bedrag ($) EN percentage (% t.o.v.
  vasthouden). Bv. "IL -500 HBAR / -$38 / -1,3%".
- Fees + LARI ertegenover (bv. +142 HBAR).
- NETTO: fees+LARI - IL (bv. +104 HBAR) -- het cijfer dat telt.
IL is alleen "erg" als netto negatief is; dat maakt deze weergave zichtbaar.

### 13b. In de live-log -- de DAADWERKELIJKE IL-historie
Per herbalancering reconstrueren wat de IL werkelijk was:
- VERLEDEN: uit de chain (Mirror Node LP-mint/burn-events + trades-tabel +
  open_positions.entry_price) de bedragen + koers per herbalancering halen ->
  IL per keer berekenen. Benadering, maar uit echte data.
- VANAF NU (exact): nieuwe tabel lp_rebalance_history die bij ELKE
  herbalancering de voor/na-bedragen (HBAR+USDC), de koers en het tijdstip
  wegschrijft. Dan bouwt de zuivere IL-historie zich op.
Log toont: regel per herbalancering (tijd, koers, IL in HBAR + $) + "totale
gemeten IL sinds start". DIT is "de hoeveelheid die er daadwerkelijk was".

### 13c. In de scenario-calculator -- IL als koers-afhankelijke drag
Vooruit kun je niet "meten", dus daar: de muntjes-groei (APR) verminderen met
een IL-drag die MEESCHAALT met de koersbeweging naar de piek. Grotere
beweging -> meer IL -> minder muntjes (maar hogere prijs compenseert in
waarde). Maakt zichtbaar dat een sterke bull meer muntjes aan IL kost.
Model: IL-factor ~ 1 - 2*sqrt(r)/(1+r) met r = piek/nu (de standaard
V2-IL-formule), toegepast op het in-pool-deel; daarnaast de bestaande
0,4%/mnd herbalanceer-drag.

BOUW: nieuw datamodel (lp_rebalance_history) + reconstructie-script + weergave.
Hoort bij de bouw met code compleet voor ons, niet los. Nu alleen vastgelegd.
