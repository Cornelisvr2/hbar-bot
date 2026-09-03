from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, resolve_testnet_addresses
from swap_executor import ERC20_ABI
from lp_manager import WHBAR_HELPER_ABI
import os

private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
settings = NETWORK_SETTINGS["testnet"]
network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
client = HederaRpcClient(network, private_key)
base = resolve_testnet_addresses()

whbar_contract = client.w3.eth.contract(address=base.whbar_token, abi=ERC20_ABI)
whbar_balance_raw = whbar_contract.functions.balanceOf(client.address).call()
print(f"Vastzittende WHBAR: {whbar_balance_raw / 10**8:.8f}")

if whbar_balance_raw == 0:
    print("Niets te unwrappen.")
    exit(0)

whbar_helper_contract = client.w3.eth.contract(address=base.whbar_helper, abi=WHBAR_HELPER_ABI)

print("Stap 1: approve() richting WhbarHelper...")
approve_fn = whbar_contract.functions.approve(base.whbar_helper, whbar_balance_raw)
approve_tx = client.build_and_send_transaction(approve_fn)
approve_receipt = client.wait_for_receipt(approve_tx)
print(f"  Approve-status: {approve_receipt['status']}, tx={approve_tx}")

import time
time.sleep(2)

print("Stap 2: unwrapWhbar()...")
unwrap_fn = whbar_helper_contract.functions.unwrapWhbar(whbar_balance_raw)
unwrap_tx = client.build_and_send_transaction(unwrap_fn, gas_limit=1_000_000)
unwrap_receipt = client.wait_for_receipt(unwrap_tx)
print(f"  Unwrap-status: {unwrap_receipt['status']}, tx={unwrap_tx}")

new_whbar_balance = whbar_contract.functions.balanceOf(client.address).call()
new_hbar_balance = client.get_hbar_balance()
print(f"\nNa unwrap -- WHBAR: {new_whbar_balance / 10**8:.8f}, native HBAR: {new_hbar_balance}")
