from web3 import Web3
from lp_manager import POOL_SLOT0_ABI_MINIMAL

MAINNET_RPC = "https://mainnet.hashio.io/api"
MAINNET_POOL_ADDRESS = "0xc5b707348da504e9be1bd4e21525459830e7b11d"

w3 = Web3(Web3.HTTPProvider(MAINNET_RPC))

pool = w3.eth.contract(
    address=MAINNET_POOL_ADDRESS,
    abi=POOL_SLOT0_ABI_MINIMAL + [{
        "inputs": [], "name": "fee",
        "outputs": [{"internalType": "uint24", "name": "", "type": "uint24"}],
        "stateMutability": "view", "type": "function"
    }]
)
fee = pool.functions.fee().call()
print(f"Fee-tier van de mainnet WHBAR/USDC-pool: {fee} ({fee/10000:.2f}%)")
print(f"Aanname in swap_executor_v2.py was: 3000 (0.30%)")
print(f"Komt overeen: {fee == 3000}")
