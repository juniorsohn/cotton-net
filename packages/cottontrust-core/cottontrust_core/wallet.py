"""
Gerenciamento de wallets digitais usando aries-askar.

Substitui indy.wallet integralmente. Cada entidade da rede
COTTONTRUST possui sua própria wallet SQLite, identificada
por um ID único e protegida por uma chave de acesso.

Além das chaves criptográficas, a wallet também armazena
metadados das entidades (peso, localização, etc.) usando
o sistema de registros genéricos do aries-askar.

Referência de migração:
    indy.wallet.create_wallet()  → create_wallet()
    indy.wallet.open_wallet()    → create_wallet()  (retorna Store aberto)
    indy.wallet.delete_wallet()  → delete_wallet()
"""
import json
import os
from pathlib import Path
from loguru import logger
from aries_askar import Store


# Diretório base onde os arquivos SQLite das wallets serão criados.
# Configurável via variável de ambiente WALLET_DIR para facilitar
# execução local (fora do container).
WALLET_DIR = Path(os.environ.get("WALLET_DIR", "/app/wallets"))

# Categoria usada para armazenar metadados de entidades no aries-askar.
METADATA_CATEGORY = "entity_metadata"


def _wallet_uri(wallet_id: str) -> str:
    """
    Constrói a URI SQLite para uma wallet.

    Args:
        wallet_id: Identificador único da wallet.

    Returns:
        URI no formato 'sqlite:///app/wallets/<wallet_id>.db'
    """
    WALLET_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite://{WALLET_DIR / wallet_id}.db"


async def create_wallet(wallet_id: str, wallet_key: str) -> Store:
    """
    Cria e abre uma wallet para uma entidade.

    Se a wallet já existir no disco, ela é removida e recriada.
    Esse comportamento é intencional para os experimentos do COTTONTRUST,
    onde cada execução parte de um estado limpo.

    Args:
        wallet_id:  Identificador único da wallet (usado como nome do arquivo).
        wallet_key: Chave de acesso (método de wrap 'raw' do aries-askar).

    Returns:
        Store: Conexão aberta com a wallet.
    """
    uri = _wallet_uri(wallet_id)

    try:
        await Store.remove(uri)
        logger.debug(f"Wallet anterior removida | id={wallet_id}")
    except Exception:
        pass  # Wallet não existia — comportamento esperado na primeira execução

    store = await Store.provision(uri, "raw", wallet_key, recreate=True)
    logger.debug(f"Wallet criada | id={wallet_id}")
    return store


async def delete_wallet(wallet_id: str) -> None:
    """
    Remove permanentemente uma wallet do disco.

    Args:
        wallet_id: Identificador da wallet a ser removida.
    """
    uri = _wallet_uri(wallet_id)
    try:
        await Store.remove(uri)
        logger.debug(f"Wallet removida | id={wallet_id}")
    except Exception as e:
        logger.warning(f"Wallet não encontrada para remoção | id={wallet_id} erro={e}")


async def store_metadata(store: Store, entity_id: str, metadata: dict) -> None:
    """
    Armazena metadados de uma entidade na wallet.

    Usa o sistema de registros genéricos do aries-askar (separado
    do armazenamento de chaves). Os metadados são serializados como JSON.

    Args:
        store:     Wallet da entidade.
        entity_id: Identificador único da entidade (chave do registro).
        metadata:  Dicionário com os atributos da entidade.
    """
    async with store.session() as session:
        await session.insert(
            METADATA_CATEGORY,
            entity_id,
            json.dumps(metadata, ensure_ascii=False).encode(),
            tags={"entity_id": entity_id},
        )
    logger.debug(f"Metadados armazenados | entity_id={entity_id}")


async def fetch_metadata(store: Store, entity_id: str) -> dict | None:
    """
    Recupera metadados de uma entidade da wallet.

    Args:
        store:     Wallet da entidade.
        entity_id: Identificador único da entidade.

    Returns:
        Dicionário com os metadados, ou None se não encontrado.
    """
    async with store.session() as session:
        record = await session.fetch(METADATA_CATEGORY, entity_id)
        if record:
            return json.loads(record.value)
    return None