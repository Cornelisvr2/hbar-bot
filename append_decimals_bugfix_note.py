notitie = """

## Vervolg op de token0/token1-bugfix: decimalen-mismatch in 10 aanroepen (4 sep 2026)

Tijdens de kleinschalige mainnet-mechaniektest bleek een TWEEDE, gerelateerde
maar aparte bug: get_live_pool_price() werd door het hele bestand aangeroepen
met self.lp_manager.config.token0/token1 (correct, canoniek geordend, zie
_setup_lp_manager()'s eigen, al-correcte volgorde-bepaling) MAAR met
hardgecodeerde self._hbar_decimals, self._usdc_decimals als decimalen --
die ALLEEN correct zijn als token0 toevallig WHBAR is (altijd waar op
testnet, NIET gegarandeerd op mainnet, waar token0 canoniek USDC is).

Empirisch bevestigd via een live, kleinschalige positie-test (token_id
76712, mainnet): dit gaf dezelfde soort, compleet verkeerde prijs
(129263.98) als de eerder gerepareerde bug -- de positie kreeg
liquidity=0 (geen daadwerkelijke inzet, financieel geen schade, netjes
gesloten en kapitaal teruggehaald).

OPGELOST: alle 10 relevante get_live_pool_price()-aanroepen gebruiken nu
self.lp_manager.config.token0_decimals/token1_decimals (al correct
bepaald in _setup_lp_manager(), gewoon nooit consistent doorgegeven aan
de aanroepen zelf) i.p.v. de hardgecodeerde, asset-specifieke velden.

BELANGRIJKE NUANCE, ontdekt tijdens het repareren: een EERSTE, te-brede
poging verving ook 8 aanroepen van compute_amount1_for_amount0()/
compute_amount0_for_amount1() -- dat was FOUT en teruggedraaid. Die
functies gebruiken "amount0"/"amount1" als PUUR SEMANTISCHE labels (in
deze specifieke aanroepen: amount0 = altijd HBAR, amount1 = altijd USDC/
SAUCE, zie de variabelenamen hbar_raw/usdc_raw) -- NIET als verwijzing
naar de pool's canonieke token0/token1. Die 8 moesten dus wel de vaste,
asset-specifieke self._hbar_decimals/self._usdc_decimals BLIJVEN
gebruiken. Geverifieerd via git diff: precies 10 gewijzigd, 8 correct
teruggedraaid naar de oorspronkelijke vorm.

BREDERE LES: dit bevestigt hoe subtiel dit soort "canonieke volgorde vs.
semantische rol"-onderscheid is -- twee functies die oppervlakkig
vergelijkbare parameters delen (token0_decimals/token1_decimals) kunnen
toch compleet verschillende betekenissen aan die parameters hechten."""

with open("/root/hbar_bot/PLAN.md", "a") as f:
    f.write(notitie)
print("Toegevoegd aan PLAN.md.")
