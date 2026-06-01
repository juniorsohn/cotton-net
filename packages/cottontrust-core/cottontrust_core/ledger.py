"""
Operações no ledger Hyperledger Indy usando indy-vdr.

Substitui indy.pool e indy.ledger integralmente. O pool é
aberto a partir de uma URL genesis (VON Network) ou de um
arquivo local. A assinatura de transações é feita com as
chaves armazenadas no aries-askar.

No indy-vdr, assinar e submeter são operações separadas:
    1. build_nym_request()  → PreparedRequest
    2. sign_request()       → assina in-place
    3. pool.submit_request() → envia ao ledger, retorna dict

Referência de migração:
    indy.pool.set_protocol_version()         → removido (padrão no indy-vdr)
    indy.pool.create_pool_ledger_config()    → removido (sem estado persistente)
    indy.pool.open_pool_ledger()             → open_pool()
    indy.ledger.build_nym_request()          → indy_vdr.ledger.build_nym_request()
    indy.ledger.sign_and_submit_request()    → sign_and_submit_nym()
"""
import urllib.request
from loguru import logger
from aries_askar import Store
import indy_vdr
from indy_vdr import Pool


async def open_pool(genesis_source: str) -> Pool:
    """
    Abre conexão com o pool Indy.

    Aceita tanto uma URL HTTP (VON Network) quanto um caminho
    local para o arquivo genesis (.txn).

    Args:
        genesis_source: URL 'http://...' ou caminho '/path/to/genesis.txn'.

    Returns:
        Pool: Conexão ativa com o ledger Indy.

    Raises:
        Exception: Se não conseguir conectar ao pool.
    """
    logger.info(f"Conectando ao pool | source={genesis_source}")

    if genesis_source.startswith("http"):
        with urllib.request.urlopen(genesis_source) as resp:
            genesis_txns = resp.read().decode("utf-8")
        pool = await indy_vdr.open_pool(transactions=genesis_txns)
    else:
        pool = await indy_vdr.open_pool(transactions_path=genesis_source)

    logger.info("Pool conectado com sucesso.")
    return pool


async def _sign_request(store: Store, submitter_did: str, request) -> None:
    """
    Assina uma requisição indy-vdr com a chave armazenada na wallet.

    A chave é buscada pelo DID (usado como nome no insert_key).
    A assinatura é aplicada diretamente no objeto request (in-place).

    Args:
        store:         Wallet que contém a chave do submitter.
        submitter_did: DID cuja chave privada será usada para assinar.
        request:       PreparedRequest do indy-vdr a ser assinado.

    Raises:
        RuntimeError: Se a chave para o DID não for encontrada na wallet.
    """
    async with store.session() as session:
        entry = await session.fetch_key(submitter_did)
        if not entry:
            raise RuntimeError(
                f"Chave não encontrada na wallet | did={submitter_did}"
            )
        signature = entry.key.sign_message(request.signature_input)

    request.set_signature(signature)


async def submit_nym(
    pool: Pool,
    store: Store,
    submitter_did: str,
    target_did: str,
    verkey: str,
    alias: str | None = None,
    role: str | None = None,
) -> tuple[dict, int]:
    """
    Constrói, assina e submete um NYM request ao ledger.

    Registra um DID no ledger Indy. No COTTONTRUST, essa é a
    operação REG_ENTITY — a transação central dos experimentos.

    Args:
        pool:          Conexão com o pool Indy.
        store:         Wallet do submitter (geralmente o trustee).
        submitter_did: DID de quem assina a transação (trustee).
        target_did:    DID da entidade sendo registrada.
        verkey:        Chave pública da entidade sendo registrada.
        alias:         Alias opcional para o DID.
        role:          Role no ledger (ex: 'TRUSTEE', None para entidade comum).

    Returns:
        Tupla (response_dict, tx_size_bytes).

    Raises:
        RuntimeError: Se a transação for rejeitada pelo ledger.
    """
    request = indy_vdr.ledger.build_nym_request(
        submitter_did=submitter_did,
        dest=target_did,
        verkey=verkey,
        alias=alias,
        role=role,
    )

    tx_size = len(request.body.encode("utf-8"))

    await _sign_request(store, submitter_did, request)
    try:
        response = await pool.submit_request(request)
    except Exception as e:
        raise RuntimeError(
            f"Transação rejeitada pelo ledger | did={target_did} motivo={e}"
        ) from e

    if response.get("op") == "REQNACK" or response.get("op") == "REJECT":
        reason = response.get("reason", "sem detalhes")
        raise RuntimeError(
            f"Transação rejeitada pelo ledger | did={target_did} motivo={reason}"
        )

    txn_id = (
        response
        .get("result", {})
        .get("txnMetadata", {})
        .get("txnId", "unknown")
    )

    logger.debug(
        f"NYM confirmado | did={target_did} txnId={txn_id} size={tx_size}B"
    )

    return response, tx_size