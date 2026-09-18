"""
COTTON-NET Coordinator — Ponto de entrada.

Cada instância deste serviço representa uma réplica do consenso externo
do COTTON-NET. Junto com o supernodo Indy local, forma a unidade física de
um supernodo Sn da arquitetura COTTON-NET.

O consenso externo é BFT (HotStuff), executado pelo daemon `cottonhs` — um
processo Go irmão, no MESMO container (ver hotstuff.py). O Python não fala
o protocolo: propõe e recebe commits por HTTP em 127.0.0.1.

Responsabilidades:
    1. Manter conexão com o supernodo Indy local (VON Network)
    2. Propor entradas ao consenso HotStuff local (hotstuff.py)
    3. Expor API HTTP para o cottonclient (FastAPI)
    4. Aplicar commits do consenso ao ledger Indy local (FSM)
    5. Gerenciar retry de transações falhas (PendingQueue)

Topologia (exemplo com 3 nós):
    Máquina 1: coordinator + cottonhs + Supernodo S1
    Máquina 2: coordinator + cottonhs + Supernodo S2
    Máquina 3: coordinator + cottonhs + Supernodo S3

Configuração via variáveis de ambiente (.env):
    NODE_ID:         Identificador único deste nó (ex: "node-1") — usado em logs
    NODE_NUM:        ID numérico inteiro desta réplica (ex: 1, 2, 3, 4)
    HOTSTUFF_URL:    URL do daemon cottonhs local (padrão: http://127.0.0.1:8080)
    GENESIS_URL:     URL genesis do supernodo Indy local
    TRUSTEE_SEED:    Seed do trustee
    TRUSTEE_DID:     DID do trustee
    WALLET_KEY:      Chave da wallet
    API_PORT:        Porta da API HTTP (padrão: 8000)
"""
import asyncio
import os
import sys
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import REGISTRY, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily

from supernodes import SupernodeRegistry
from pending import PendingQueue
from fsm import CoordinatorFSM
from hotstuff import HotStuffClient, HotStuffError
from log_entry import NymLogEntry
from cottontrust_core.wallet import create_wallet
from cottontrust_core.identity import create_and_store_did


# ── Configuração ──────────────────────────────────────────────────────────────

NODE_ID      = os.environ["NODE_ID"]
NODE_NUM     = int(os.environ["NODE_NUM"])   # ID desta réplica no cluster HotStuff
HOTSTUFF_URL = os.environ.get("HOTSTUFF_URL", "http://127.0.0.1:8080")
HOTSTUFF_READY_TIMEOUT = float(os.environ.get("HOTSTUFF_READY_TIMEOUT", "300"))
GENESIS_URL  = os.environ["GENESIS_URL"]
TRUSTEE_SEED = os.environ["TRUSTEE_SEED"]
TRUSTEE_DID  = os.environ["TRUSTEE_DID"]
WALLET_KEY   = os.environ.get("WALLET_KEY", "changeme")
API_PORT     = int(os.environ.get("API_PORT", "8000"))

# ── Logging ───────────────────────────────────────────────────────────────────

logger.remove()
logger.add(
    sys.stdout,
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        f"<blue>{NODE_ID}</blue> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> — "
        "<level>{message}</level>"
    ),
    colorize=True,
)

# ── Estado global do nó ───────────────────────────────────────────────────────

registry:       SupernodeRegistry | None  = None
pending:        PendingQueue | None       = None
fsm:            CoordinatorFSM | None     = None
consensus:      HotStuffClient | None     = None
# Último /status do daemon, atualizado em background. O collector do Prometheus
# é síncrono e não pode fazer HTTP no meio do scrape, então lê daqui.
_consensus_status: dict = {}
_background_tasks: list[asyncio.Task]    = []


# ── Ciclo de vida da aplicação ────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa e encerra os componentes do Coordinator."""
    global registry, pending, fsm, consensus, _background_tasks

    logger.info(f"=== Coordinator iniciando | node={NODE_ID} consenso={HOTSTUFF_URL} ===")

    # 1. Conecta ao supernodo Indy local — com RETRY.
    # No cn-deploy-seq os webservers dos SNs sobem escalonados; o coordinator
    # do último SN pode nascer minutos antes do seu genesis existir. Se ele
    # MORRER aqui (era exit não-tratado), o bootstrap do consenso dos demais
    # quebra em silêncio e o cluster não fecha quórum (visto em n=128 no RAFT).
    # Esperar em loop mantém o processo vivo e o bootstrap íntegro.
    registry = SupernodeRegistry(NODE_ID, GENESIS_URL)
    genesis_timeout = int(os.environ.get("GENESIS_RETRY_TIMEOUT", "900"))
    t0 = asyncio.get_event_loop().time()
    while True:
        try:
            await registry.setup()
            break
        except Exception as e:
            restante = genesis_timeout - (asyncio.get_event_loop().time() - t0)
            if restante <= 0:
                logger.error(
                    f"Genesis indisponível após {genesis_timeout}s | url={GENESIS_URL}"
                )
                raise
            logger.warning(
                f"Genesis ainda indisponível ({e.__class__.__name__}: {e}); "
                f"nova tentativa em 10s | url={GENESIS_URL} restante={int(restante)}s"
            )
            await asyncio.sleep(10)

    # 2. Inicializa wallet e DID do trustee
    trustee_store, _ = await _init_trustee()

    # 3. Inicializa fila de retry
    pending = PendingQueue()

    # 4. Inicializa FSM
    fsm = CoordinatorFSM(
        pool        = registry.local.pool,
        store       = trustee_store,
        trustee_did = TRUSTEE_DID,
        pending     = pending,
    )

    # 5. Conecta ao daemon de consenso local (processo irmão no container).
    # Quem sobe o cottonhs é o entrypoint da imagem, não o Python: aqui só
    # esperamos ele responder, o que já significa cluster HotStuff formado.
    consensus = HotStuffClient(HOTSTUFF_URL)
    await consensus.wait_ready(timeout=HOTSTUFF_READY_TIMEOUT)

    # 5b. Espelha o estado do daemon para o Prometheus (ver _CottonNetCollector)
    async def _poll_consensus():
        global _consensus_status
        while True:
            _consensus_status = await consensus.status()
            await asyncio.sleep(5)

    _background_tasks.append(asyncio.create_task(_poll_consensus(), name="poll_consensus"))

    # 6. Drena fila de entradas confirmadas pelo consenso
    _background_tasks.append(asyncio.create_task(fsm.drain_queue(), name="drain_queue"))

    # 7. Inicia worker de retry
    async def _submit_retry(entry: NymLogEntry):
        from cottontrust_core.ledger import submit_nym
        _, tx_size = await submit_nym(
            pool=registry.local.pool,
            store=trustee_store,
            submitter_did=TRUSTEE_DID,
            target_did=entry.did,
            verkey=entry.verkey,
        )
        RETRY_APPLIED.labels(node_id=NODE_ID).inc()
        logger.info(
            f"Retry NYM aplicado | entity_id={entry.entity_id} "
            f"did={entry.did} size={tx_size}B"
        )

    def _on_discard(entry: NymLogEntry):
        RETRY_DISCARDED.labels(node_id=NODE_ID).inc()

    pending.start(_submit_retry, on_discard=_on_discard)

    logger.info(f"Coordinator pronto | node={NODE_ID}")
    yield

    # Encerramento
    logger.info("Coordinator encerrando...")
    for task in _background_tasks:
        task.cancel()
    await asyncio.gather(*_background_tasks, return_exceptions=True)
    _background_tasks.clear()
    pending.stop()
    if consensus is not None:
        await consensus.aclose()
    await registry.teardown()


async def _init_trustee():
    """Inicializa wallet e DID do trustee local."""
    store = await create_wallet(f"wallet_trustee_{NODE_ID}", WALLET_KEY)
    did, verkey = await create_and_store_did(store, seed=TRUSTEE_SEED)
    logger.info(f"Trustee inicializado | did={did}")
    return store, did


# ── Métricas Prometheus ───────────────────────────────────────────────────────

class _CottonNetCollector:
    """
    Collector Prometheus para métricas de negócio do COTTON-NET.

    Lê os valores atuais de `fsm` e `pending` a cada scrape,
    sem necessidade de background tasks ou modificação do FSM.
    """

    def collect(self):
        if _consensus_status:
            g = GaugeMetricFamily(
                "cotton_consensus_applied",
                "Comandos executados pelo consenso externo nesta réplica",
                labels=["node_id", "engine"],
            )
            g.add_metric([NODE_ID, "hotstuff"], float(_consensus_status.get("applied", 0)))
            yield g

            # Comitado pelo consenso mas ainda não aceito pelo FSM. É o
            # backpressure que separa ORDENADO de DURÁVEL: o consenso ordena em
            # dezenas de ms, a escrita no Indy leva segundos.
            g = GaugeMetricFamily(
                "cotton_consensus_backlog",
                "Comandos comitados aguardando entrega ao FSM (ordenado, não durável)",
                labels=["node_id", "engine"],
            )
            g.add_metric([NODE_ID, "hotstuff"],
                         float(_consensus_status.get("applier_pending", 0)))
            yield g

        if pending is not None:
            g = GaugeMetricFamily(
                "cotton_pending_queue_size",
                "Transações pendentes de retry no ledger Indy local",
                labels=["node_id"],
            )
            g.add_metric([NODE_ID], float(pending.size))
            yield g


REGISTRY.register(_CottonNetCollector())

# Counters de retry — complementam NYM_ATTEMPTED/NYM_APPLIED/NYM_FAILED do fsm.py
RETRY_APPLIED = Counter(
    "cotton_nym_retry_applied_total",
    "NYMs que falharam na 1ª tentativa e foram aplicados com sucesso via retry",
    ["node_id"],
)
RETRY_DISCARDED = Counter(
    "cotton_nym_retry_discarded_total",
    "NYMs descartados após esgotar MAX_ATTEMPTS de retry (falha permanente)",
    ["node_id"],
)

# Histograma: latência do consenso externo (propose → confirmação do quórum).
# Nome neutro de propósito: o mesmo painel serve para comparar Raft (CFT, no
# master) e HotStuff (BFT, nesta branch) — o motor vai no label `engine`.
CONSENSUS_PROPOSE_LATENCY = Histogram(
    "cotton_consensus_propose_duration_seconds",
    "Latência do consenso externo: propose() até confirmação do quórum",
    ["node_id", "engine"],
    buckets=[.01, .025, .05, .1, .25, .5, 1.0, 2.5, 5.0, 10.0],
)


# ── FastAPI ───────────────────────────────────────────────────────────────────

app = FastAPI(
    title       = "COTTON-NET Coordinator",
    description = "Árbitro da camada externa de consenso do COTTON-NET",
    version     = "0.1.0",
    lifespan    = lifespan,
)

# Instrumentação automática: latência e throughput de cada endpoint.
# /health e /metrics excluídos por serem chamadas de infraestrutura.
Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/health", "/metrics"],
).instrument(app).expose(app, include_in_schema=False)


class RegisterRequest(BaseModel):
    entity_id:   str
    entity_type: str
    did:         str
    verkey:      str
    role:        str = ""
    raw_attrs:   dict | None = None


class RegisterResponse(BaseModel):
    success: bool
    txn_id:  str = ""
    error:   str = ""


class StatusResponse(BaseModel):
    node_id:           str
    consensus:         str
    consensus_ready:   bool
    consensus_applied: int
    consensus_backlog: int          # comitado mas ainda não entregue ao FSM
    supernodo:      str
    alive:          bool
    pending:        int
    fsm_queue:      int
    fsm_applied:    int
    fsm_bytes:      int


@app.post("/register", response_model=RegisterResponse)
async def register(req: RegisterRequest):
    """
    Registra uma entidade no ledger via consenso HotStuff + Indy.

    Qualquer coordinator aceita: o daemon local manda o comando a todas as
    réplicas por quorum call, então não há líder para onde redirecionar —
    diferente do RAFT, que funilava tudo por um nó só.
    """
    if not registry.local.alive:
        raise HTTPException(
            status_code=503,
            detail=f"Supernodo local indisponível | node={NODE_ID}",
        )

    # Com paridade OFF, zera role/raw_attrs ANTES do propose: mantém o payload
    # RAFT byte-idêntico ao legado (coordinator_time_sec é métrica medida —
    # nenhum byte extra deve viajar quando o FSM não vai usá-los).
    parity = os.environ.get("WORKLOAD_PARITY", "0") == "1"
    entry = NymLogEntry(
        entity_id   = req.entity_id,
        entity_type = req.entity_type,
        did         = req.did,
        verkey      = req.verkey,
        role        = req.role if parity else "",
        raw_attrs   = req.raw_attrs if parity else None,
    )

    try:
        # Propõe ao consenso — bloqueia até f+1 réplicas executarem o comando.
        # Como no RAFT, o retorno significa ORDENADO, não durável: a escrita no
        # Indy é assíncrona (fsm.apply enfileira, drain_queue aplica).
        with CONSENSUS_PROPOSE_LATENCY.labels(node_id=NODE_ID, engine="hotstuff").time():
            await consensus.propose(entry.encode())
        logger.info(
            f"Entrada proposta ao consenso | "
            f"entity_id={req.entity_id} did={req.did}"
        )
        return RegisterResponse(success=True)

    except HotStuffError as e:
        logger.error(f"Falha ao propor | entity_id={req.entity_id} erro={e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Falha ao propor | entity_id={req.entity_id} erro={e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/apply", include_in_schema=False)
async def apply(request: Request):
    """
    Entrega de commit vinda do daemon HotStuff local (gancho OnExec).

    É o sentido Go → Python da fronteira: o que o raftify fazia chamando
    fsm.apply() direto, o cottonhs faz por HTTP. O corpo são os bytes do
    NymLogEntry, na ordem decidida pelo consenso.

    Só aceita de 127.0.0.1: o daemon é processo irmão no mesmo container, e
    ninguém de fora deve conseguir injetar entrada no FSM pulando o consenso.
    Responde rápido porque fsm.apply só enfileira — quem escreve no Indy é o
    drain_queue.
    """
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1"):
        logger.warning(f"/apply recusado | origem={host} node={NODE_ID}")
        raise HTTPException(status_code=403, detail="somente o daemon local")

    data = await request.body()
    await fsm.apply(data)
    return Response(status_code=204)


@app.get("/status", response_model=StatusResponse)
async def status():
    """Retorna o status deste nó: consenso, supernodo e pendências."""
    hs = await consensus.status() if consensus else {}
    return StatusResponse(
        node_id           = NODE_ID,
        consensus         = "hotstuff",
        consensus_ready   = bool(hs),
        consensus_applied = int(hs.get("applied", 0)),
        consensus_backlog = int(hs.get("applier_pending", 0)),
        supernodo   = registry.local.genesis_url,
        alive       = registry.local.alive,
        pending     = pending.size,
        fsm_queue   = fsm._queue.qsize() if fsm else 0,
        fsm_applied = fsm.applied if fsm else 0,
        fsm_bytes   = fsm.bytes_written if fsm else 0,
    )


@app.get("/entity_timing")
async def entity_timing():
    """
    Retorna o timing real de cada NYM aplicado pelo FSM.

    Usado pelo cottonclient após wait_for_drain() para preencher
    tx_time_sec e tx_size_bytes com medições reais (não estimativas).
    """
    return fsm._entity_timing if fsm else {}


@app.get("/health")
async def health():
    """Health check para Docker Swarm e load balancers."""
    return {"status": "ok", "node": NODE_ID}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)