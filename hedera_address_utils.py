"""
hedera_address_utils.py

Zet Hedera entity-ID's (shard.realm.num, bv. 0.0.3045981) om naar hun
standaard EVM 'long-zero' adres. Dit werkt voor alle Hedera accounts,
contracts en tokens die geen custom EVM-alias hebben ingesteld (dat is
voor system-contracts zoals SaucerSwap's Router en voor de meeste
bestaande HTS-tokens vrijwel altijd het geval).

Zie: https://docs.hedera.com/hedera/core-concepts/accounts/account-properties#account-id-alias
"""


from eth_utils import to_checksum_address


def hedera_id_to_evm_address(hedera_id: str) -> str:
    """
    hedera_id: string in 'shard.realm.num' formaat, bv. '0.0.3045981'
    Geeft het checksummed 0x-adres terug (vereist door web3.py).
    """
    parts = hedera_id.split(".")
    if len(parts) != 3:
        raise ValueError(f"Ongeldig Hedera ID formaat: {hedera_id}")

    shard, realm, num = (int(p) for p in parts)
    addr_bytes = shard.to_bytes(4, "big") + realm.to_bytes(8, "big") + num.to_bytes(8, "big")
    raw_address = "0x" + addr_bytes.hex()
    return to_checksum_address(raw_address)


def evm_address_to_hedera_id(evm_address: str) -> str:
    """Omgekeerde conversie, handig voor logging/debugging."""
    addr = evm_address.replace("0x", "")
    addr_bytes = bytes.fromhex(addr)
    shard = int.from_bytes(addr_bytes[0:4], "big")
    realm = int.from_bytes(addr_bytes[4:12], "big")
    num = int.from_bytes(addr_bytes[12:20], "big")
    return f"{shard}.{realm}.{num}"


if __name__ == "__main__":
    # Bekende SaucerSwap V1-contracten, ter referentie
    known_contracts = {
        "SaucerSwapV1Factory": "0.0.1062784",
        "SaucerSwapV1RouterV3": "0.0.3045981",
        "SaucerSwapRouterWithFee": "0.0.6755814",
    }
    for name, hedera_id in known_contracts.items():
        print(f"{name}: {hedera_id} -> {hedera_id_to_evm_address(hedera_id)}")
