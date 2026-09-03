from hedera_rpc_client import HederaRpcClient, NetworkConfig
from hedera_address_utils import hedera_id_to_evm_address
from config import NETWORK_SETTINGS, resolve_testnet_addresses, resolve_testnet_v2_addresses
from lp_manager import LpManager, LpPositionConfig
import os
import requests

private_key = os.environ.get('HEDERA_BOT_PRIVATE_KEY')
settings = NETWORK_SETTINGS['testnet']
network = NetworkConfig(rpc_url=settings['rpc_url'], chain_id=settings['chain_id'])
client = HederaRpcClient(network, private_key)
base = resolve_testnet_addresses()
v2 = resolve_testnet_v2_addresses()
sauce_address = hedera_id_to_evm_address('0.0.1183558')

config = LpPositionConfig(
    position_manager_address=v2.position_manager,
    token0=base.whbar_token, token1=sauce_address,
    whbar_address=base.whbar_token,
    whbar_helper_address=base.whbar_helper,
    fee_tier=3000,
)
manager = LpManager(client, config)

print('Positie 338 sluiten...')
try:
    close_tx = manager.close_position(338)
    print(f'Sluit-status: {"GELUKT" if close_tx else "MISLUKT"}, tx={close_tx}')
except requests.exceptions.HTTPError as e:
    print(f'HTTP-statuscode: {e.response.status_code}')
    print(f'Ruwe responstekst:\n{e.response.text}')
