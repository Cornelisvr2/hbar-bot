from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS
from swap_executor import ERC20_ABI
from hedera_address_utils import hedera_id_to_evm_address
from config import resolve_testnet_addresses
import os

private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
settings = NETWORK_SETTINGS["testnet"]
network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
client = HederaRpcClient(network, private_key)
sauce_address = hedera_id_to_evm_address("0.0.1183558")
base = resolve_testnet_addresses()

hbar_balance = client.get_hbar_balance()
sauce_contract = client.w3.eth.contract(address=sauce_address, abi=ERC20_ABI)
sauce_balance = sauce_contract.functions.balanceOf(client.address).call() / (10**6)

# WHBAR-controle toegevoegd (28 aug 2026) -- eerder ontbrak dit, waardoor
# 109.52 vastzittende, niet-unwrapped WHBAR een tijd onopgemerkt bleef.
whbar_contract = client.w3.eth.contract(address=base.whbar_token, abi=ERC20_ABI)
whbar_balance = whbar_contract.functions.balanceOf(client.address).call() / (10**8)

print(f"HBAR (native): {hbar_balance}")
print(f"SAUCE: {sauce_balance}")
print(f"WHBAR (ERC20, niet-native): {whbar_balance}")
if whbar_balance > 0:
    print("LET OP: er staat WHBAR die niet is omgezet naar native HBAR!")
