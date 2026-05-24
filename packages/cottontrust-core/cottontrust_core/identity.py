"""
Gerenciamento de identidades descentralizadas (DIDs).

Substitui indy.did integralmente, implementando a mesma derivação
de DID/verkey do Hyperledger Indy usando aries-askar e base58.

No Hyperledger Indy, um DID Ed25519 é derivado assim:
    seed (32 bytes) → chave privada Ed25519
    DID     = base58( chave_pública[:16] )   ← primeiros 16 bytes
    verkey  = base58( chave_pública[32] )    ← chave pública completa

Referência de migração:
    indy.did.create_and_store_my_did()  → create_and_store_did()
"""
import base58
from loguru import logger
from aries_askar import Key, KeyAlg, Store


def create_seed(counter: int, name: str | int) -> str:
    """
    Gera um seed determinístico de 32 caracteres.

    Mantém compatibilidade com o comportamento original do projeto:
    o seed é derivado de um contador e um nome, garantindo que a
    mesma entidade sempre gere o mesmo DID entre execuções.

    Args:
        counter: Número sequencial da entidade.
        name:    Nome ou código identificador da entidade.

    Returns:
        String de exatamente 32 caracteres usada como seed Ed25519.
    """
    raw = f"{name}{counter}A0000000000000000000000000000000000"
    return raw[:32]


def _key_from_seed(seed: str) -> tuple[Key, str, str]:
    """
    Deriva uma chave Ed25519 a partir de um seed e calcula DID e verkey.

    Args:
        seed: String de 32 caracteres usada como seed.

    Returns:
        Tupla (key, did, verkey).
    """
    seed_bytes = seed.encode("utf-8")[:32].ljust(32, b"\x00")
    key = Key.from_secret_bytes(KeyAlg.Ed25519, seed_bytes)
    pub = key.get_public_bytes()

    did    = base58.b58encode(pub[:16]).decode()
    verkey = base58.b58encode(pub).decode()

    return key, did, verkey


async def create_and_store_did(
    store: Store,
    seed: str | None = None,
) -> tuple[str, str]:
    """
    Cria um par DID/verkey e armazena a chave privada na wallet.

    Se um seed for fornecido, a geração é determinística — o mesmo
    seed sempre produz o mesmo DID. Caso contrário, uma chave
    aleatória é gerada.

    Args:
        store: Wallet onde a chave privada será armazenada.
        seed:  Seed de 32 caracteres (opcional).

    Returns:
        Tupla (did, verkey) como strings base58.
    """
    if seed:
        key, did, verkey = _key_from_seed(seed)
    else:
        key    = Key.generate(KeyAlg.Ed25519)
        pub    = key.get_public_bytes()
        did    = base58.b58encode(pub[:16]).decode()
        verkey = base58.b58encode(pub).decode()

    # Armazena usando o DID como nome, permitindo recuperação pelo DID
    async with store.session() as session:
        await session.insert_key(did, key)

    logger.debug(f"DID criada | did={did}")
    return did, verkey