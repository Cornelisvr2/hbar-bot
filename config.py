"""
config.py

Centrale configuratie voor het HBAR-trading bot project.
Alle adressen hier zijn omgezet van Hedera-formaat (0.0.x) naar EVM-formaat
via hedera_address_utils.hedera_id_to_evm_address(), en zijn NIET uit
geheugen gehaald -- ze komen direct van de door jou aangeleverde,
geverifieerde contract-tabellen.

STATUS: TESTNET. Pas HEDERA_NETWORK aan naar 'mainnet' pas nadat alles
end-to-end getest is en je de mainnet-equivalenten van deze adressen hebt
geverifieerd op HashScan.
"""

from dataclasses import dataclass
from hedera_address_utils import hedera_id_to_evm_address


HEDERA_NETWORK = "mainnet"  # 'testnet' of 'mainnet'

NETWORK_SETTINGS = {
    "testnet": {
        "rpc_url": "https://testnet.hashio.io/api",
        "chain_id": 296,
        "mirror_node_url": "https://testnet.mirrornode.hedera.com",
    },
    "mainnet": {
        "rpc_url": "https://mainnet.hashio.io/api",
        "chain_id": 295,
        "mirror_node_url": "https://mainnet-public.mirrornode.hedera.com",
    },
}

# --- Testnet contract-ID's (Hedera-formaat), zoals aangeleverd ---
TESTNET_IDS = {
    "router": "0.0.19264",          # SaucerSwapV1RouterV3 (huidige, niet gedeprecieerd)
    "factory": "0.0.9959",          # SaucerSwapV1Factory
    "whbar_token": "0.0.15058",     # WHBAR HTS-token (voor path/routing)
    "whbar_contract": "0.0.15057",  # WHBAR wrap/unwrap contract
    "whbar_helper": "0.0.5286055",  # WhbarHelper -- DE JUISTE unwrap-route (24 aug 2026
                                      # empirisch bevestigd; de SwapRouter's eigen
                                      # unwrapWHBAR unwrapt NIET wat al in de wallet zit)
    # KRITIEK (26 aug 2026): dit wijst BEWUST naar SAUCE, niet naar het
    # echte testnet-USDC-testtoken. Reden: dat testtoken heeft GEEN
    # testnet-liquiditeit (geen enkele pool, V1 of V2 -- bevestigd
    # 23 aug 2026), terwijl de WHBAR/SAUCE-pool wel actief en liquide is.
    # De naam "usdc" in de rest van de codebase (swap_hbar_to_usdc(),
    # SwapConfigV2.usdc_address, enz.) is dus MISLEIDEND op testnet --
    # bewust zo gehouden i.p.v. een grote, risicovolle hernoem-operatie
    # door meerdere bestanden heen. Op MAINNET wijst dit gewoon naar
    # echte USDC (zie MAINNET_IDS hieronder), waar dit wel klopt.
    "usdc": "0.0.1183558",          # SAUCE (bewust, zie toelichting hierboven)
}
TESTNET_USDC_DECIMALS = 6  # SAUCE-decimalen (was 18, de echte testnet-USDC-testtoken-waarde)

# --- Mainnet contract-ID's (Hedera-formaat), zoals aangeleverd ---
MAINNET_IDS = {
    "router": "0.0.3045981",        # SaucerSwapV1RouterV3 (huidige, niet gedeprecieerd)
    "factory": "0.0.1062784",       # SaucerSwapV1Factory
    "whbar_token": "0.0.1456986",   # WHBAR HTS-token (voor path/routing)
    "whbar_contract": None,         # NOG IN TE VULLEN indien nodig (wrap/unwrap contract)
    "whbar_helper": "0.0.5808826",  # WhbarHelper, bevestigd via officiele docs
    "usdc": "0.0.456858",           # Circle USDC op Hedera mainnet
}
# Circle's echte USDC volgt de standaard van 6 decimalen.
MAINNET_USDC_DECIMALS = 6

# --- V2 (CLMM) testnet contract-ID's, zoals aangeleverd ---
TESTNET_V2_IDS = {
    "factory": "0.0.1197038",                    # SaucerSwapV2Factory
    "swap_router": "0.0.1414040",                 # SaucerSwapV2SwapRouter
    "quoter_v2": "0.0.1390002",                    # SaucerSwapV2QuoterV2
    "position_manager": "0.0.1308184",             # NonfungiblePositionManager
}

# --- V2 (CLMM) mainnet contract-ID's -- bevestigd via officiële SaucerSwap-docs (23 aug 2026) ---
MAINNET_V2_IDS = {
    "factory": "0.0.3946833",
    "swap_router": "0.0.3949434",
    "quoter_v2": "0.0.3949424",
    "position_manager": "0.0.4053945",  # V2-manager, niet de gedeprecieerde 0.0.3949448
}

# Specifiek, geverifieerd WHBAR/USDC V2-poolcontract op mainnet, bevestigd
# via GeckoTerminal (22 aug 2026): $3.2M TVL, $2.7M 24u-volume -- een
# actieve, liquide pool. Fee-tier nog te bevestigen door de pool zelf te
# bevragen (fee() call) i.p.v. de aanname van 3000 in swap_executor_v2.py.
MAINNET_V2_WHBAR_USDC_POOL_ADDRESS = "0xc5b707348da504e9be1bd4e21525459830e7b11d"


@dataclass
class ResolvedAddresses:
    router: str
    factory: str
    whbar_token: str
    whbar_contract: str
    whbar_helper: str
    usdc: str
    usdc_decimals: int


def resolve_testnet_addresses() -> ResolvedAddresses:
    if TESTNET_IDS["usdc"] is None:
        raise ValueError(
            "USDC token-ID nog niet ingevuld in TESTNET_IDS['usdc']. "
            "Vul dit aan voordat je de swap_executor gebruikt."
        )

    return ResolvedAddresses(
        router=hedera_id_to_evm_address(TESTNET_IDS["router"]),
        factory=hedera_id_to_evm_address(TESTNET_IDS["factory"]),
        whbar_token=hedera_id_to_evm_address(TESTNET_IDS["whbar_token"]),
        whbar_contract=hedera_id_to_evm_address(TESTNET_IDS["whbar_contract"]),
        whbar_helper=hedera_id_to_evm_address(TESTNET_IDS["whbar_helper"]),
        usdc=hedera_id_to_evm_address(TESTNET_IDS["usdc"]),
        usdc_decimals=TESTNET_USDC_DECIMALS,
    )


def resolve_mainnet_addresses() -> ResolvedAddresses:
    if MAINNET_IDS["usdc"] is None:
        raise ValueError("USDC token-ID nog niet ingevuld in MAINNET_IDS['usdc'].")

    # whbar_contract is niet strikt nodig voor swap_executor.py -- de Router
    # roept WHBAR's deposit/withdraw intern aan, wij hebben in de path-array
    # alleen het whbar_token-adres nodig. Laat leeg als je hem niet hebt.
    whbar_contract_id = MAINNET_IDS["whbar_contract"]

    return ResolvedAddresses(
        router=hedera_id_to_evm_address(MAINNET_IDS["router"]),
        factory=hedera_id_to_evm_address(MAINNET_IDS["factory"]),
        whbar_token=hedera_id_to_evm_address(MAINNET_IDS["whbar_token"]),
        whbar_contract=hedera_id_to_evm_address(whbar_contract_id) if whbar_contract_id else "",
        whbar_helper=hedera_id_to_evm_address(MAINNET_IDS["whbar_helper"]),
        usdc=hedera_id_to_evm_address(MAINNET_IDS["usdc"]),
        usdc_decimals=MAINNET_USDC_DECIMALS,
    )


@dataclass
class ResolvedV2Addresses:
    factory: str
    swap_router: str
    quoter_v2: str
    position_manager: str


def resolve_testnet_v2_addresses() -> ResolvedV2Addresses:
    return ResolvedV2Addresses(
        factory=hedera_id_to_evm_address(TESTNET_V2_IDS["factory"]),
        swap_router=hedera_id_to_evm_address(TESTNET_V2_IDS["swap_router"]),
        quoter_v2=hedera_id_to_evm_address(TESTNET_V2_IDS["quoter_v2"]),
        position_manager=hedera_id_to_evm_address(TESTNET_V2_IDS["position_manager"]),
    )


def resolve_mainnet_v2_addresses() -> ResolvedV2Addresses:
    missing = [k for k, v in MAINNET_V2_IDS.items() if v is None]
    if missing:
        raise ValueError(
            f"Mainnet V2-adressen nog niet ingevuld: {missing}. "
            f"Haal deze op van docs.saucerswap.finance voordat je V2 op mainnet gebruikt."
        )
    return ResolvedV2Addresses(
        factory=hedera_id_to_evm_address(MAINNET_V2_IDS["factory"]),
        swap_router=hedera_id_to_evm_address(MAINNET_V2_IDS["swap_router"]),
        quoter_v2=hedera_id_to_evm_address(MAINNET_V2_IDS["quoter_v2"]),
        position_manager=hedera_id_to_evm_address(MAINNET_V2_IDS["position_manager"]),
    )


if __name__ == "__main__":
    print(f"Actief netwerk: {HEDERA_NETWORK}")
    print(f"RPC: {NETWORK_SETTINGS[HEDERA_NETWORK]}")

    print("\n--- Testnet ---")
    try:
        print(resolve_testnet_addresses())
    except ValueError as e:
        print(f"Nog niet compleet: {e}")

    print("\n--- Mainnet ---")
    try:
        print(resolve_mainnet_addresses())
    except ValueError as e:
        print(f"Nog niet compleet: {e}")
