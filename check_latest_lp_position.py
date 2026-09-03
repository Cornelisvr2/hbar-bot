from hedera_rpc_client import HederaRpcClient, NetworkConfig
from config import NETWORK_SETTINGS, resolve_testnet_v2_addresses
from lp_manager import POSITION_MANAGER_ABI
import os

private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
settings = NETWORK_SETTINGS["testnet"]
network = NetworkConfig(rpc_url=settings["rpc_url"], chain_id=settings["chain_id"])
client = HederaRpcClient(network, private_key)
v2 = resolve_testnet_v2_addresses()
position_manager = client.w3.eth.contract(address=v2.position_manager, abi=POSITION_MANAGER_ABI)

balance = position_manager.functions.balanceOf(client.address).call()
print(f"Aantal LP-NFT's in bezit: {balance}")

if balance > 0:
    token_id = position_manager.functions.tokenOfOwnerByIndex(client.address, balance - 1).call()
    position = position_manager.functions.positions(token_id).call()
    print(f"Meest recente tokenSN={token_id}")
    print(f"  liquidity={position[5]}, tickLower={position[3]}, tickUpper={position[4]}")
