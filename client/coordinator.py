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
import asyncio
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


async def get_entity_timing(
    coordinator_url: str,
    timeout: float = 10.0,
) -> dict:
    """
    Consulta o timing real de cada NYM aplicado pelo FSM.

    Retorna dict {entity_id: {queue_wait_sec, indy_time_sec, tx_size_bytes}}.
    Chamar após wait_for_drain() garante que todos os dados estão presentes.
    """
    url = f"{coordinator_url.rstrip('/')}/entity_timing"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


async def wait_for_drain(
    coordinator_url: str,
    poll_interval: float = 5.0,
    timeout: float = 30.0,
) -> int:
    """
    Aguarda o FSM do coordinator esvaziar a fila de aplicação ao Indy.

    Retorna o total de bytes escritos no ledger pelo FSM (soma dos tx_size
    de todos os NYMs aplicados), útil para preencher tx_size_bytes nas métricas.

    Args:
        coordinator_url: URL base do coordinator líder.
        poll_interval:   Intervalo entre polls em segundos.
        timeout:         Timeout máximo por requisição HTTP.

    Returns:
        Total de bytes escritos no ledger Indy pelo FSM deste nó.
    """
    url = f"{coordinator_url.rstrip('/')}/status"
    logger.info("Aguardando drenagem da fila FSM do coordinator...")
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        while True:
            try:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
                fsm_queue   = data.get("fsm_queue", 0)
                fsm_applied = data.get("fsm_applied", 0)
                fsm_bytes   = data.get("fsm_bytes", 0)
                if fsm_queue == 0:
                    logger.info(
                        f"Fila FSM drenada | aplicados={fsm_applied} bytes={fsm_bytes}"
                    )
                    return fsm_bytes
                logger.debug(
                    f"Fila FSM | pendentes={fsm_queue} aplicados={fsm_applied}"
                )
            except Exception as e:
                logger.warning(f"Erro ao consultar status do coordinator: {e}")
            await asyncio.sleep(poll_interval)
