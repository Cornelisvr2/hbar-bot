from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, HEDERA_NETWORK, resolve_mainnet_v2_addresses
import os

settings = NETWORK_SETTINGS[HEDERA_NETWORK]
network_config = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
rpc_client = HederaRpcClient(network_config, os.environ["HEDERA_BOT_PRIVATE_KEY"])

v2 = resolve_mainnet_v2_addresses()

FACTORY_ABI = [{
    "inputs": [{"internalType": "uint24", "name": "fee", "type": "uint24"}],
    "name": "feeAmountTickSpacing",
    "outputs": [{"internalType": "int24", "name": "", "type": "int24"}],
    "stateMutability": "view", "type": "function",
}]

factory = rpc_client.w3.eth.contract(address=v2.factory, abi=FACTORY_ABI)

for fee in [100, 500, 1500, 3000, 10000]:
    try:
        spacing = factory.functions.feeAmountTickSpacing(fee).call()
        print(f"fee={fee}: tickSpacing={spacing}")
    except Exception as e:
        print(f"fee={fee}: FOUT -- {e}")
