"""
hedera_rpc_client.py

Verbinding met Hedera's EVM-compatible laag via JSON-RPC, waarmee we
SaucerSwap's Router-contract kunnen aanspreken alsof het een normaal
Ethereum-achtig contract is (web3.py).

Belangrijk:
- Dit vereist een ECDSA/EVM-enabled account (bv. via MetaMask aangemaakt).
- Publieke relay: https://mainnet.hashio.io/api (gratis, rate-limited).
  Voor productiegebruik met een trading bot is een eigen/betaalde RPC-node
  (bv. via Hedera-erkende providers) aan te raden i.v.m. betrouwbaarheid.
- Hedera mainnet chain ID = 295, testnet = 296.

SaucerSwap contract-adressen (mainnet) moet je verifiëren op
https://docs.saucerswap.finance/ voordat je hiermee live gaat -- adressen
kunnen wijzigen en ik wil hier geen adres hardcoden dat mogelijk verouderd
of onjuist is.
"""

import os
import time
from dataclasses import dataclass
from typing import Optional
from web3 import Web3
from retry_utils import retry_with_backoff

try:
    # web3.py >= 7.x
    from web3.middleware import ExtraDataToPOAMiddleware as PoaMiddleware
except ImportError:
    # web3.py 6.x
    from web3.middleware import geth_poa_middleware as PoaMiddleware


HEDERA_MAINNET_CHAIN_ID = 295
HEDERA_TESTNET_CHAIN_ID = 296

DEFAULT_MAINNET_RPC = "https://mainnet.hashio.io/api"
DEFAULT_TESTNET_RPC = "https://testnet.hashio.io/api"


@dataclass
class NetworkConfig:
    rpc_url: str
    chain_id: int


class HederaRpcClient:
    def __init__(self, network: NetworkConfig, private_key: str):
        """
        private_key: de ECDSA private key van het bot-account (hex-string,
        met of zonder '0x' prefix). Laad deze ALTIJD uit een environment
        variable of secrets-manager, nooit hardcoded in code of git.
        """
        self.network = network
        self.w3 = Web3(Web3.HTTPProvider(network.rpc_url))
        # Hedera's relay gedraagt zich op sommige punten als een PoA-chain
        self.w3.middleware_onion.inject(PoaMiddleware, layer=0)

        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
        self.account = self.w3.eth.account.from_key(private_key)

    @property
    def address(self) -> str:
        return self.account.address

    def is_connected(self) -> bool:
        return self.w3.is_connected()

    @retry_with_backoff(max_retries=3, base_delay=2.0, exceptions=(Exception,))
    def get_hbar_balance(self) -> float:
        """HBAR balance in whole HBAR (niet tinybar/wei).
        Retry-met-backoff (28 aug 2026): vangt incidentele 502's/verbroken
        verbindingen van de RPC-relay op."""
        balance_wei = self.w3.eth.get_balance(self.account.address)
        return self.w3.from_wei(balance_wei, "ether")

    @retry_with_backoff(max_retries=3, base_delay=2.0, exceptions=(Exception,))
    def get_token_balance(self, token_contract_address: str, token_abi: list, decimals: int = 6) -> float:
        """
        USDC op Hedera heeft standaard 6 decimalen (HTS-token 0.0.456858).
        token_contract_address moet het EVM-adres zijn (0x...), niet het
        Hedera-formaat (0.0.xxxx) -- die kun je omzetten via de Mirror Node
        API indien nodig.
        Retry-met-backoff (28 aug 2026): zelfde reden als get_hbar_balance().
        """
        contract = self.w3.eth.contract(address=token_contract_address, abi=token_abi)
        raw_balance = contract.functions.balanceOf(self.account.address).call()
        return raw_balance / (10 ** decimals)

    def build_and_send_transaction(self, contract_function, gas_limit: Optional[int] = None,
                                     max_fee_per_gas_gwei: Optional[float] = None,
                                     value_wei: int = 0) -> str:
        """
        Bouwt, signeert en verstuurt een transactie voor een gegeven
        contract-function call (bv. router.functions.swapExactHBARForTokens(...)).
        Geeft de transactiehash terug.

        value_wei: native HBAR om mee te sturen (msg.value), nodig voor elke
        payable call waarbij WHBAR betrokken is -- zie de officiele
        SaucerSwap-docs (23 aug 2026): zonder dit ontvangt het contract
        nooit de HBAR die het intern moet wrappen, en faalt de call.

        max_fee_per_gas_gwei: als niet opgegeven, wordt de ACTUELE
        netwerk-gasprijs opgevraagd (w3.eth.gas_price) met een veiligheids-
        marge van 20% erbovenop.

        gas_limit: als niet opgegeven, wordt de benodigde gas GESCHAT via
        eth_estimateGas (werkt ook op Hedera's JSON-RPC-relay), met een
        veiligheidsmarge van 50% erbovenop -- Hedera's precompile-calls
        (bv. token-associatie) bleken 23 aug 2026 stelselmatig meer gas
        te kosten dan handmatige schattingen (2.000.000 was te weinig,
        5.000.000+ nodig), dus dynamisch schatten is betrouwbaarder dan
        blijven gokken met steeds hogere hardcoded getallen.
        """
        nonce = self.w3.eth.get_transaction_count(self.account.address)

        if max_fee_per_gas_gwei is None:
            current_gas_price_wei = self.w3.eth.gas_price
            max_fee_per_gas_wei = int(current_gas_price_wei * 1.2)  # 20% veiligheidsmarge
        else:
            max_fee_per_gas_wei = self.w3.to_wei(max_fee_per_gas_gwei, "gwei")

        if gas_limit is None:
            estimate_params = {"from": self.account.address}
            if value_wei > 0:
                estimate_params["value"] = value_wei
            estimated_gas = contract_function.estimate_gas(estimate_params)
            gas_limit = int(estimated_gas * 1.5)  # 50% veiligheidsmarge

        tx_params = {
            "chainId": self.network.chain_id,
            "gas": gas_limit,
            "maxFeePerGas": max_fee_per_gas_wei,
            "maxPriorityFeePerGas": self.w3.to_wei(1, "gwei"),
            "nonce": nonce,
        }
        if value_wei > 0:
            tx_params["value"] = value_wei

        tx = contract_function.build_transaction(tx_params)

        signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        return self.w3.to_hex(tx_hash)

    @retry_with_backoff(max_retries=2, base_delay=3.0, exceptions=(Exception,))
    def wait_for_receipt(self, tx_hash: str, timeout_seconds: int = 60) -> dict:
        """
        Retry-met-backoff (28 aug 2026, max_retries=2 i.p.v. de
        gebruikelijke 3): dit is een LEESOPERATIE (peilt de status van een
        AL VERSTUURDE transactie, verstuurt niets nieuws) -- veilig om te
        herhalen. Minder pogingen dan elders, omdat wait_for_transaction_
        receipt() zelf al tot timeout_seconds kan duren per poging.
        """
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout_seconds)
        # Korte pauze na elke bevestigde transactie: de RPC-relay's eigen
        # nonce-tracking loopt soms iets achter op de daadwerkelijke
        # bevestiging, wat tot herhaalde "Nonce too low"-fouten leidde bij
        # de daaropvolgende transactie (25-26 aug 2026, empirisch gevonden
        # op meerdere plekken). Centraal hier toegevoegd i.p.v. losse
        # sleep()-aanroepen na elke individuele aanroep van deze methode.
        time.sleep(2)
        return {
            "status": "success" if receipt.status == 1 else "failed",
            "block_number": receipt.blockNumber,
            "gas_used": receipt.gasUsed,
            "tx_hash": tx_hash,
        }


def load_mainnet_client_from_env() -> HederaRpcClient:
    """
    Verwacht env vars:
      HEDERA_BOT_PRIVATE_KEY  -- ECDSA private key van het bot-account
      HEDERA_RPC_URL          -- optioneel, valt terug op publieke Hashio-relay
    """
    private_key = os.environ.get("HEDERA_BOT_PRIVATE_KEY")
    if not private_key:
        raise EnvironmentError(
            "HEDERA_BOT_PRIVATE_KEY niet gezet. Zet deze als environment "
            "variable, laad hem nooit direct in code."
        )

    rpc_url = os.environ.get("HEDERA_RPC_URL", DEFAULT_MAINNET_RPC)
    network = NetworkConfig(rpc_url=rpc_url, chain_id=HEDERA_MAINNET_CHAIN_ID)

    return HederaRpcClient(network, private_key)


if __name__ == "__main__":
    # Handmatige connectiviteitstest (vereist HEDERA_BOT_PRIVATE_KEY env var)
    try:
        client = load_mainnet_client_from_env()
        print(f"Verbonden: {client.is_connected()}")
        print(f"Bot-adres: {client.address}")
        print(f"HBAR balance: {client.get_hbar_balance()}")
    except EnvironmentError as e:
        print(f"Skip test: {e}")
