"""
KRITIEKE BUGFIX (6 sep 2026, ontdekt zodra de EERSTE, echte positie
opende): de positie-weergave in bot_data.py mengde canonieke ticks
(uit de database) met een semantische prijs (pool_price_sauce_per_
hbar) -- dezelfde bug-klasse als de hele dag, nu zichtbaar in de
tonende cijfers: positie.hbar toonde 1.56 i.p.v. de daadwerkelijke
1512.80, prijsgrenzen stonden in de verkeerde schaal, en
range_status toonde ten onrechte "buiten_bereik".

Oplossing: de canoniek/semantisch-detectie naar boven verplaatsen
(vóór compute_position_amounts), een canonieke prijs berekenen voor
ALLE interne, tick-gebaseerde berekeningen, en pas HELEMAAL AAN HET
EIND terugrekenen naar de mensvriendelijke (semantische) schaal voor
de daadwerkelijke weergave-waarden.
"""
with open("/root/hbar_bot/bot_data.py", "r") as f:
    inhoud = f.read()

oud = '''        on_chain = position_manager.functions.positions(positie["token_id"]).call()
        liquidity = on_chain[5]
        positie_hbar, positie_sauce = compute_position_amounts(
            liquidity, positie["tick_lower"], positie["tick_upper"],
            pool_price_sauce_per_hbar, token0_decimals=8, token1_decimals=6,
        )
        positie_waarde_usd = positie_hbar * hbar_price_usd + positie_sauce * sauce_price_usd
        UINT128_MAX = (2 ** 128) - 1
        try:
            fee_amount0_raw, fee_amount1_raw = position_manager.functions.collect(
                (positie["token_id"], client.address, UINT128_MAX, UINT128_MAX)
            ).call({"from": client.address})
            fee_hbar = fee_amount0_raw / (10 ** 8)
            fee_sauce = fee_amount1_raw / (10 ** 6)
        except Exception as e:
            print(f"[waarschuwing] Kon opgebouwde fees niet opvragen: {e}")
            fee_hbar, fee_sauce = 0.0, 0.0
        fee_waarde_usd = fee_hbar * hbar_price_usd + fee_sauce * sauce_price_usd
        # Canonieke token0/token1-decimalen bepalen (5 sep 2026, systematische audit -- zelfde detectie als _setup_lp_manager()
        # in regime_orchestrator.py): ticks in de database zijn ALTIJD canoniek opgeslagen, ongeacht netwerk.
        if int(base.whbar_token, 16) < int(base.usdc, 16):
            _t0_dec, _t1_dec = 8, base.usdc_decimals
        else:
            _t0_dec, _t1_dec = base.usdc_decimals, 8
        prijs_onder = tick_to_price(positie["tick_lower"], _t0_dec, _t1_dec)
        prijs_boven = tick_to_price(positie["tick_upper"], _t0_dec, _t1_dec)
        if prijs_boven > prijs_onder:
            positie_in_range_pct = (
                (pool_price_sauce_per_hbar - prijs_onder) / (prijs_boven - prijs_onder) * 100
            )
        else:
            positie_in_range_pct = 50.0'''

nieuw = '''        on_chain = position_manager.functions.positions(positie["token_id"]).call()
        liquidity = on_chain[5]
        # KRITIEKE BUGFIX (6 sep 2026, ontdekt bij de EERSTE echte positie):
        # canonieke token0/token1-decimalen ÉÉN keer bepalen, VOOR gebruik --
        # ticks in de database zijn ALTIJD canoniek opgeslagen (zelfde
        # detectie als _setup_lp_manager() in regime_orchestrator.py).
        _hbar_is_token0 = int(base.whbar_token, 16) < int(base.usdc, 16)
        if _hbar_is_token0:
            _t0_dec, _t1_dec = 8, base.usdc_decimals
        else:
            _t0_dec, _t1_dec = base.usdc_decimals, 8
        # Canonieke prijs: pool_price_sauce_per_hbar is SEMANTISCH (USDC
        # per HBAR) -- moet omgekeerd worden als HBAR niet canoniek
        # token0 is (mainnet), om consistent te zijn met de canonieke
        # ticks/decimalen hierboven.
        _prijs_canoniek = pool_price_sauce_per_hbar if _hbar_is_token0 else (
            1.0 / pool_price_sauce_per_hbar if pool_price_sauce_per_hbar > 0 else 0.0
        )
        positie_hbar, positie_sauce = compute_position_amounts(
            liquidity, positie["tick_lower"], positie["tick_upper"],
            _prijs_canoniek, token0_decimals=_t0_dec, token1_decimals=_t1_dec,
        )
        # compute_position_amounts() geeft (amount0, amount1) terug in de
        # CANONIEKE token0/token1-volgorde -- HBAR kan dus amount0 OF
        # amount1 zijn, afhankelijk van het netwerk.
        if not _hbar_is_token0:
            positie_hbar, positie_sauce = positie_sauce, positie_hbar
        positie_waarde_usd = positie_hbar * hbar_price_usd + positie_sauce * sauce_price_usd
        UINT128_MAX = (2 ** 128) - 1
        try:
            fee_amount0_raw, fee_amount1_raw = position_manager.functions.collect(
                (positie["token_id"], client.address, UINT128_MAX, UINT128_MAX)
            ).call({"from": client.address})
            if _hbar_is_token0:
                fee_hbar = fee_amount0_raw / (10 ** 8)
                fee_sauce = fee_amount1_raw / (10 ** base.usdc_decimals)
            else:
                fee_sauce = fee_amount0_raw / (10 ** base.usdc_decimals)
                fee_hbar = fee_amount1_raw / (10 ** 8)
        except Exception as e:
            print(f"[waarschuwing] Kon opgebouwde fees niet opvragen: {e}")
            fee_hbar, fee_sauce = 0.0, 0.0
        fee_waarde_usd = fee_hbar * hbar_price_usd + fee_sauce * sauce_price_usd
        # Canonieke prijsgrenzen berekenen (consistent met de canonieke
        # ticks), DAN pas terugrekenen naar de mensvriendelijke,
        # semantische schaal voor weergave -- en let op: omkeren wisselt
        # ook welke grens "onder" en welke "boven" is.
        _prijs_onder_canoniek = tick_to_price(positie["tick_lower"], _t0_dec, _t1_dec)
        _prijs_boven_canoniek = tick_to_price(positie["tick_upper"], _t0_dec, _t1_dec)
        if _prijs_boven_canoniek > _prijs_onder_canoniek:
            positie_in_range_pct = (
                (_prijs_canoniek - _prijs_onder_canoniek) / (_prijs_boven_canoniek - _prijs_onder_canoniek) * 100
            )
        else:
            positie_in_range_pct = 50.0
        if _hbar_is_token0:
            prijs_onder, prijs_boven = _prijs_onder_canoniek, _prijs_boven_canoniek
        else:
            prijs_onder = 1.0 / _prijs_boven_canoniek if _prijs_boven_canoniek > 0 else 0.0
            prijs_boven = 1.0 / _prijs_onder_canoniek if _prijs_onder_canoniek > 0 else 0.0'''

aantal = inhoud.count(oud)
print(f"Aantal gevonden: {aantal} (verwacht: 1)")
if aantal == 1:
    inhoud = inhoud.replace(oud, nieuw)
    with open("/root/hbar_bot/bot_data.py", "w") as f:
        f.write(inhoud)
    print("Gecorrigeerd.")
else:
    print("WAARSCHUWING: geen unieke match -- NIET aangepast.")
