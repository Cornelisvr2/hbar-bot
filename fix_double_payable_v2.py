with open("/root/hbar_bot/lp_manager.py", "r") as f:
    inhoud = f.read()

WHBAR_SYMBOLIC_MSG_VALUE_TINYBAR = "10 ** 8"

# --- Fix 1: claim_and_compound() ---
oud1 = """        payable_value = 0
        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() == whbar_lower:
                payable_value = tokens_owed0_raw * (10 ** (18 - self.config.token0_decimals))
            elif self.config.token1.lower() == whbar_lower:
                payable_value = tokens_owed1_raw * (10 ** (18 - self.config.token1_decimals))
        mint_fee_tinybar = self._get_mint_fee_tinybar()
        if mint_fee_tinybar > 0:
            payable_value += mint_fee_tinybar * (10 ** 10)
        multicall_fn = self.position_manager.functions.multicall([increase_encoded, refund_eth_encoded])
        increase_tx = self.rpc_client.build_and_send_transaction(multicall_fn, value_wei=payable_value)
        increase_receipt = self.rpc_client.wait_for_receipt(increase_tx)
        return increase_tx if increase_receipt["status"] == "success" else None"""

nieuw1 = """        # BUGFIX (4 sep 2026, zelfde patroon als de eerder gevonden en
        # opgeloste dubbele-msg.value-bug in open_position()): payable_value
        # stuurde voorheen HETZELFDE bedrag dat net via collect() als WHBAR-
        # tokens is binnengekomen NOGMAALS als native msg.value -- dat
        # vereist evenveel EXTRA, apart beschikbare native HBAR, bovenop
        # wat al geclaimd is. Nu een klein, symbolisch bedrag i.p.v. het
        # volledige, al-geclaimde bedrag nogmaals.
        payable_value = 0
        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() == whbar_lower or self.config.token1.lower() == whbar_lower:
                payable_value = (WHBAR_SYMBOLIC_MSG_VALUE_TINYBAR_PLACEHOLDER) * (10 ** 10)
        mint_fee_tinybar = self._get_mint_fee_tinybar()
        if mint_fee_tinybar > 0:
            payable_value += mint_fee_tinybar * (10 ** 10)
        multicall_fn = self.position_manager.functions.multicall([increase_encoded, refund_eth_encoded])
        increase_tx = self.rpc_client.build_and_send_transaction(multicall_fn, value_wei=payable_value)
        increase_receipt = self.rpc_client.wait_for_receipt(increase_tx)
        return increase_tx if increase_receipt["status"] == "success" else None"""

nieuw1 = nieuw1.replace("WHBAR_SYMBOLIC_MSG_VALUE_TINYBAR_PLACEHOLDER", WHBAR_SYMBOLIC_MSG_VALUE_TINYBAR)

aantal1 = inhoud.count(oud1)
print(f"Fix 1 (claim_and_compound) -- aantal matches: {aantal1}")
if aantal1 == 1:
    inhoud = inhoud.replace(oud1, nieuw1)
    print("Fix 1 toegepast.")
else:
    print("WAARSCHUWING fix 1: geen unieke match.")

# --- Fix 2: deploy_additional_capital() ---
oud2 = """        payable_value = 0
        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() == whbar_lower:
                payable_value = amount0_desired * (10 ** (18 - self.config.token0_decimals))
            elif self.config.token1.lower() == whbar_lower:
                payable_value = amount1_desired * (10 ** (18 - self.config.token1_decimals))
        mint_fee_tinybar = self._get_mint_fee_tinybar()
        if mint_fee_tinybar > 0:
            payable_value += mint_fee_tinybar * (10 ** 10)
        increase_tx = self.rpc_client.build_and_send_transaction(multicall_fn, value_wei=payable_value)"""

nieuw2 = """        # BUGFIX (4 sep 2026, zelfde patroon als eerder gevonden en
        # opgeloste dubbele-msg.value-bug elders): payable_value stuurde
        # voorheen het volledige amount0_desired/amount1_desired NOGMAALS
        # als native msg.value. Nu een klein, symbolisch bedrag i.p.v. het
        # volledige bedrag nogmaals.
        payable_value = 0
        if self.config.whbar_address:
            whbar_lower = self.config.whbar_address.lower()
            if self.config.token0.lower() == whbar_lower or self.config.token1.lower() == whbar_lower:
                payable_value = (WHBAR_SYMBOLIC_MSG_VALUE_TINYBAR_PLACEHOLDER) * (10 ** 10)
        mint_fee_tinybar = self._get_mint_fee_tinybar()
        if mint_fee_tinybar > 0:
            payable_value += mint_fee_tinybar * (10 ** 10)
        increase_tx = self.rpc_client.build_and_send_transaction(multicall_fn, value_wei=payable_value)"""

nieuw2 = nieuw2.replace("WHBAR_SYMBOLIC_MSG_VALUE_TINYBAR_PLACEHOLDER", WHBAR_SYMBOLIC_MSG_VALUE_TINYBAR)

aantal2 = inhoud.count(oud2)
print(f"Fix 2 (deploy_additional_capital) -- aantal matches: {aantal2}")
if aantal2 == 1:
    inhoud = inhoud.replace(oud2, nieuw2)
    print("Fix 2 toegepast.")
else:
    print("WAARSCHUWING fix 2: geen unieke match.")

with open("/root/hbar_bot/lp_manager.py", "w") as f:
    f.write(inhoud)
