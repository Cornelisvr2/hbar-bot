from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, resolve_testnet_v2_addresses, resolve_testnet_addresses
from hedera_address_utils import hedera_id_to_evm_address
from lp_manager import get_live_pool_price
from swap_executor import ERC20_ABI
import os

private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
settings = NETWORK_SETTINGS["testnet"]
network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
client = HederaRpcClient(network, private_key)
base = resolve_testnet_addresses()
v2 = resolve_testnet_v2_addresses()
sauce_address = hedera_id_to_evm_address("0.0.1183558")

live_price = get_live_pool_price(client, v2.factory, base.whbar_token, sauce_address, 3000, 8, 6)
print(f"Live pool-prijs: {live_price}")

hbar_balance = float(client.get_hbar_balance())
sauce_contract = client.w3.eth.contract(address=sauce_address, abi=ERC20_ABI)
sauce_balance = sauce_contract.functions.balanceOf(client.address).call() / (10**6)
print(f"HBAR: {hbar_balance}")
print(f"SAUCE: {sauce_balance}")

total_hbar_equiv = hbar_balance + (sauce_balance / live_price)
target_hbar_equiv_per_side = total_hbar_equiv / 2
print(f"\nTotale waarde (HBAR-equivalent): {total_hbar_equiv:.4f}")
print(f"Doel per kant (50/50): {target_hbar_equiv_per_side:.4f}")

hbar_to_swap = hbar_balance - target_hbar_equiv_per_side
print(f"\nTe swappen HBAR -> SAUCE: {hbar_to_swap:.4f}")
