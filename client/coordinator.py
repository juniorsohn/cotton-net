"""
Cliente HTTP para o Coordinator do COTTON-NET.

Quando COORDINATOR_URL está configurado, o cottonclient delega
o registro de entidades ao cluster RAFT em vez de submeter
transações NYM diretamente ao ledger Indy. O Coordinator
garante o consenso externo entre supernodos antes de
aplicar o NYM localmente em cada nó.

Fluxo com Coordinator:
    client → POST /register → Coordinator (líder RAFT)
                            → RAFT propose → quórum
                            → FSM.apply() em cada nó
                            → submit_nym() em cada supernodo
"""
import httpx
from loguru import logger


async def register_entity(
    coordinator_url: str,
    entity_id: str,
    entity_type: str,
    did: str,
    verkey: str,
    timeout: float = 30.0,
) -> None:
    """
    Registra uma entidade via API HTTP do Coordinator.

    POSTa em /register e aguarda a confirmação do consenso RAFT.
    O timeout padrão de 30s acomoda a latência de eleição e
    replicação em clusters com 4 nós.

    Args:
        coordinator_url: URL base do Coordinator (ex: "http://coordinator-1:8000").
        entity_id:       Identificador único da entidade.
        entity_type:     Tipo da entidade ('uba', 'bale', etc.).
        did:             DID gerado localmente pela entidade.
        verkey:          Chave pública correspondente ao DID.
        timeout:         Timeout em segundos para aguardar o RAFT (padrão: 30s).

    Raises:
        httpx.HTTPStatusError: Se o Coordinator retornar HTTP 4xx/5xx.
        httpx.RequestError:    Se houver falha de conexão com o Coordinator.
        RuntimeError:          Se o Coordinator retornar success=False.
    """
    payload = {
        "entity_id":   entity_id,
        "entity_type": entity_type,
        "did":         did,
        "verkey":      verkey,
    }

    logger.debug(
        f"Enviando ao Coordinator | "
        f"url={coordinator_url} entity_id={entity_id} did={did}"
    )

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.post(
            f"{coordinator_url.rstrip('/')}/register",
            json=payload,
        )
        response.raise_for_status()
        result = response.json()

    if not result.get("success"):
        raise RuntimeError(
            f"Coordinator recusou o registro | "
            f"entity_id={entity_id} erro={result.get('error', 'desconhecido')}"
        )

    logger.info(
        f"Registrado via Coordinator (RAFT) | "
        f"entity_id={entity_id} entity_type={entity_type} did={did}"
    )
