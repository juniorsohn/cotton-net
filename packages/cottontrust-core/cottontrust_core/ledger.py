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
import asyncio
import urllib.request
from loguru import logger
from aries_askar import Store
import indy_vdr
from indy_vdr import Pool


# Erros transitórios de propagação read-after-write: num pool RBFT grande, um
# NYM já comitado pode ainda não estar visível no nó que atende a próxima
# transação dependente (ATTRIB do próprio DID, ou NYM assinado pelo endorser).
# A verkey aparece assim que a escrita propaga — basta reenviar com backoff.
_TRANSIENT_MARKERS = ("cannot be found", "could not authenticate")


async def _submit_resilient(pool, build, *, label, attempts=6, base_delay=0.5):
    """
    Submete uma request ao pool tolerando a janela read-after-write.

    `build` é uma corrotina sem argumentos que constrói E assina a request
    (reconstruída a cada tentativa para não reutilizar o objeto FFI já consumido).
    Faz retry com backoff exponencial apenas em erros de propagação transitórios;
    qualquer outra falha é propagada imediatamente. Devolve (response, tx_size).

    Importante: `request.body` é lido ANTES do submit — o indy-vdr libera o
    handle da request ao submeter, então acessá-lo depois daria "no request handle".
    """
    last_exc = None
    for i in range(attempts):
        request = await build()
        tx_size = len(request.body.encode("utf-8"))
        try:
            return await pool.submit_request(request), tx_size
        except Exception as e:
            last_exc = e
            transient = any(m in str(e) for m in _TRANSIENT_MARKERS)
            if transient and i < attempts - 1:
                delay = base_delay * (2 ** i)
                logger.warning(
                    f"Propagação pendente — {label} | tentativa {i + 1}/{attempts}, "
                    f"retry em {delay:.1f}s | {e}"
                )
                await asyncio.sleep(delay)
                continue
            raise
    raise last_exc


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


async def submit_nym_endorsed(
    pool: Pool,
    author_store: Store,
    author_did: str,
    endorser_store: Store,
    endorser_did: str,
    target_did: str,
    verkey: str,
    alias: str | None = None,
    role: str | None = None,
) -> tuple[dict, int]:
    """
    Constrói, assina e submete um NYM com padrão author+endorser (Aries RFC 0028).

    AVISO — limitação arquitetural do indy-node (verificado em 1.12.6 e 1.13.2):
    Este padrão (dual-assinatura: author=novo DID + endorser=ENDORSER registrado)
    NAO funciona para registrar novos DIDs via NYM. O RolesAuthorizer do indy-node
    (authorizer.py, passo 2) rejeita a transação com "sender's DID not found in the
    Ledger" antes de avaliar as assinaturas, porque o autor ainda nao existe no
    ledger. O flag off_ledger_signature que suprimiria esse check nao pode ser
    aplicado a constraints de role especifico (restricao em auth_constraints.py).

    Este metodo funciona corretamente para transacoes onde o AUTHOR JA EXISTE no
    ledger e precisa de endosso de um ENDORSER para publicar SCHEMA, CRED_DEF ou
    ATTRIB — o caso de uso original do RFC 0028.

    Para registro de novos DIDs via NYM na cadeia hierarquica do COTTONTRUST,
    use submit_nym() com endorser_store/endorser_did como submitter (padrao
    endorser-submits implementado em entities/base.py).
    """
    request = indy_vdr.ledger.build_nym_request(
        submitter_did=author_did,
        dest=target_did,
        verkey=verkey,
        alias=alias,
        role=role,
    )

    request.set_endorser(endorser_did)
    tx_size = len(request.body.encode("utf-8"))

    async with author_store.session() as session:
        entry = await session.fetch_key(author_did)
        if not entry:
            raise RuntimeError(f"Chave do author nao encontrada na wallet | did={author_did}")
        sig = entry.key.sign_message(request.signature_input)
    request.set_multi_signature(author_did, sig)

    async with endorser_store.session() as session:
        entry = await session.fetch_key(endorser_did)
        if not entry:
            raise RuntimeError(
                f"Chave do endorser nao encontrada na wallet | did={endorser_did}"
            )
        sig = entry.key.sign_message(request.signature_input)
    request.set_multi_signature(endorser_did, sig)

    response = await pool.submit_request(request)

    if response.get("op") in ("REQNACK", "REJECT"):
        reason = response.get("reason", "sem detalhes")
        raise RuntimeError(
            f"Transacao rejeitada | did={target_did} motivo={reason}"
        )

    txn_id = (
        response.get("result", {}).get("txnMetadata", {}).get("txnId", "unknown")
    )
    logger.debug(
        f"NYM endorsado | did={target_did} txnId={txn_id} size={tx_size}B"
    )
    return response, tx_size


async def submit_attrib(
    pool: Pool,
    store: Store,
    submitter_did: str,
    raw_attrs: dict,
) -> int:
    """
    Escreve atributos publicos de um DID no ledger via ATTRIB transaction.

    Apenas dados nao-sensiveis devem ser passados em raw_attrs.
    O submitter_did deve ser o proprio DID alvo (auto-ATTRIB).
    Retorna o tamanho em bytes da transacao.
    """
    import json as _json
    raw = _json.dumps(raw_attrs, ensure_ascii=False)

    async def _build():
        request = indy_vdr.ledger.build_attrib_request(
            submitter_did=submitter_did,
            target_did=submitter_did,
            raw=raw,
            xhash=None,
            enc=None,
        )
        await _sign_request(store, submitter_did, request)
        return request

    response, tx_size = await _submit_resilient(
        pool, _build, label=f"ATTRIB did={submitter_did}"
    )

    if response.get("op") in ("REQNACK", "REJECT"):
        reason = response.get("reason", "sem detalhes")
        raise RuntimeError(f"ATTRIB rejeitado | did={submitter_did} motivo={reason}")

    logger.debug(f"ATTRIB registrado | did={submitter_did} size={tx_size}B")
    return tx_size


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
    async def _build():
        request = indy_vdr.ledger.build_nym_request(
            submitter_did=submitter_did,
            dest=target_did,
            verkey=verkey,
            alias=alias,
            role=role,
        )
        await _sign_request(store, submitter_did, request)
        return request

    try:
        response, tx_size = await _submit_resilient(
            pool, _build, label=f"NYM did={target_did}"
        )
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