from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, resolve_testnet_addresses
from swap_executor import ERC20_ABI
import os

private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
settings = NETWORK_SETTINGS["testnet"]
network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
client = HederaRpcClient(network, private_key)
base = resolve_testnet_addresses()

whbar_contract = client.w3.eth.contract(address=base.whbar_token, abi=ERC20_ABI)
whbar_balance_raw = whbar_contract.functions.balanceOf(client.address).call()
print(f"WHBAR-balans (ERC20, NIET native HBAR): {whbar_balance_raw} (ruw, 8 decimalen)")
print(f"WHBAR-balans omgerekend: {whbar_balance_raw / 10**8:.8f}")

if whbar_balance_raw > 0:
    print("\nLET OP: er staat WHBAR in de wallet die niet is omgezet naar native HBAR!")
else:
    print("\nGeen achtergebleven WHBAR gevonden -- dit specifieke risico speelt nu niet.")
