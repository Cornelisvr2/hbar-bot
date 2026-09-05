with open("/root/hbar_bot/bot_data.py", "r") as f:
    inhoud = f.read()

# --- Fix 1: import ook de mainnet-resolvers ---
oud1 = "from config import NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses"
nieuw1 = ("from config import (\n"
          "    NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses,\n"
          "    resolve_mainnet_addresses, resolve_mainnet_v2_addresses,\n"
          ")")
aantal1 = inhoud.count(oud1)
print(f"Fix 1 (imports) -- aantal matches: {aantal1}")
if aantal1 == 1:
    inhoud = inhoud.replace(oud1, nieuw1)
    print("Fix 1 toegepast.")

# --- Fix 2: netwerk-bewuste base/v2-resolutie, i.p.v. hardgecodeerd testnet ---
oud2 = """    base = resolve_testnet_addresses()
    v2 = resolve_testnet_v2_addresses()

    hbar_balance = float(client.get_hbar_balance())

    sauce_address = hedera_id_to_evm_address("0.0.1183558")
    sauce_contract = client.w3.eth.contract(address=sauce_address, abi=ERC20_ABI)
    sauce_balance = sauce_contract.functions.balanceOf(client.address).call() / (10 ** 6)

    whbar_contract = client.w3.eth.contract(address=base.whbar_token, abi=ERC20_ABI)
    whbar_stuck = whbar_contract.functions.balanceOf(client.address).call() / (10 ** 8)

    gecko = GeckoTerminalClient()
    hbar_price_usd = gecko.get_pool_snapshot().price_usd

    pool_price_sauce_per_hbar = get_live_pool_price(
        client, v2.factory, base.whbar_token, sauce_address, 3000, 8, 6,
    )
    sauce_price_usd = hbar_price_usd / pool_price_sauce_per_hbar if pool_price_sauce_per_hbar > 0 else 0.0"""

nieuw2 = """    # BUGFIX (4 sep 2026, gevonden tijdens de mainnet-migratie): dit hele
    # bestand was volledig hardgecodeerd naar testnet -- inclusief het
    # testnet-SAUCE-adres, een vaste fee_tier=3000, en decimalen zonder
    # canonieke-volgorde-bewustzijn (zelfde bug-klasse als eerder vandaag
    # al gevonden en gerepareerd in regime_orchestrator.py). Nu volledig
    # netwerk-bewust.
    if HEDERA_NETWORK == "mainnet":
        base = resolve_mainnet_addresses()
        v2 = resolve_mainnet_v2_addresses()
    else:
        base = resolve_testnet_addresses()
        v2 = resolve_testnet_v2_addresses()

    hbar_balance = float(client.get_hbar_balance())

    quote_address = base.usdc  # SAUCE op testnet, echte USDC op mainnet
    quote_contract = client.w3.eth.contract(address=quote_address, abi=ERC20_ABI)
    sauce_balance = quote_contract.functions.balanceOf(client.address).call() / (10 ** base.usdc_decimals)

    whbar_contract = client.w3.eth.contract(address=base.whbar_token, abi=ERC20_ABI)
    whbar_stuck = whbar_contract.functions.balanceOf(client.address).call() / (10 ** 8)

    gecko = GeckoTerminalClient()
    hbar_price_usd = gecko.get_pool_snapshot().price_usd

    fee_tier = int(os.environ.get("LP_FEE_TIER", "3000"))
    pool_price_sauce_per_hbar = get_live_pool_price(
        client, v2.factory, base.whbar_token, quote_address, fee_tier, 8, base.usdc_decimals,
    )
    sauce_price_usd = hbar_price_usd / pool_price_sauce_per_hbar if pool_price_sauce_per_hbar > 0 else 0.0"""

aantal2 = inhoud.count(oud2)
print(f"Fix 2 (netwerk-bewuste resolutie) -- aantal matches: {aantal2}")
if aantal2 == 1:
    inhoud = inhoud.replace(oud2, nieuw2)
    print("Fix 2 toegepast.")
else:
    print("WAARSCHUWING: geen unieke match voor fix 2 -- NIET aangepast.")

with open("/root/hbar_bot/bot_data.py", "w") as f:
    f.write(inhoud)
