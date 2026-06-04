"""
COTTON-NET Coordinator — Ponto de entrada.

Cada instância deste serviço representa um nó no cluster RAFT
do COTTON-NET. Junto com o supernodo Indy local, forma a unidade
física de um supernodo Sn da arquitetura COTTON-NET.

Responsabilidades:
    1. Manter conexão com o supernodo Indy local (VON Network)
    2. Participar do cluster RAFT via raftify (eleição + replicação)
    3. Expor API HTTP para o cottonclient (FastAPI)
    4. Aplicar commits RAFT ao ledger Indy local (FSM)
    5. Gerenciar retry de transações falhas (PendingQueue)

Topologia (exemplo com 3 nós):
    Máquina 1: coordinator (líder RAFT) + Supernodo S1
    Máquina 2: coordinator (seguidor)   + Supernodo S2
    Máquina 3: coordinator (seguidor)   + Supernodo S3

Configuração via variáveis de ambiente (.env):
    NODE_ID:         Identificador único deste nó (ex: "node-1") — usado em logs
    NODE_NUM:        ID numérico inteiro deste nó no raftify (ex: 1, 2, 3, 4)
    RAFT_ADDR:       Endereço RAFT deste nó (ex: "0.0.0.0:60061")
    RAFT_PEERS:      Endereços dos outros nós RAFT (ex: "coordinator-2:60061,coordinator-3:60061")
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

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from loguru import logger
from raftify import Raft, RaftConfig, Config, Peers, Peer, Slogger, InitialRole
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import REGISTRY
from prometheus_client.core import GaugeMetricFamily

from supernodes import SupernodeRegistry
from pending import PendingQueue
from fsm import CoordinatorFSM
from log_entry import NymLogEntry
from cottontrust_core.wallet import create_wallet
from cottontrust_core.identity import create_and_store_did


# ── Configuração ──────────────────────────────────────────────────────────────

NODE_ID      = os.environ["NODE_ID"]
NODE_NUM     = int(os.environ["NODE_NUM"])   # ID inteiro exigido pelo raftify
RAFT_ADDR    = os.environ["RAFT_ADDR"]
RAFT_PEERS   = os.environ.get("RAFT_PEERS", "")
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
raft:           Raft | None               = None
raft_node                                 = None
_background_tasks: list[asyncio.Task]    = []


# ── Ciclo de vida da aplicação ────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa e encerra os componentes do Coordinator."""
    global registry, pending, fsm, raft, raft_node, _background_tasks

    logger.info(f"=== Coordinator iniciando | node={NODE_ID} raft={RAFT_ADDR} ===")

    # 1. Conecta ao supernodo Indy local
    registry = SupernodeRegistry(NODE_ID, GENESIS_URL)
    await registry.setup()

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

    # 5. Inicializa cluster RAFT
    raft, raft_node = await _init_raft(fsm)

    # 6. Drena fila de entradas confirmadas pelo RAFT
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
        logger.info(
            f"Retry NYM aplicado | entity_id={entry.entity_id} "
            f"did={entry.did} size={tx_size}B"
        )

    pending.start(_submit_retry)

    logger.info(f"Coordinator pronto | node={NODE_ID}")
    yield

    # Encerramento
    logger.info("Coordinator encerrando...")
    for task in _background_tasks:
        task.cancel()
    await asyncio.gather(*_background_tasks, return_exceptions=True)
    _background_tasks.clear()
    pending.stop()
    await registry.teardown()


async def _init_trustee():
    """Inicializa wallet e DID do trustee local."""
    store = await create_wallet(f"wallet_trustee_{NODE_ID}", WALLET_KEY)
    did, verkey = await create_and_store_did(store, seed=TRUSTEE_SEED)
    logger.info(f"Trustee inicializado | did={did}")
    return store, did


async def _wait_dns(host: str, timeout: int = 60) -> None:
    """Aguarda até o hostname ser resolvível pelo DNS do Swarm overlay."""
    import socket
    for elapsed in range(0, timeout, 2):
        try:
            socket.getaddrinfo(host, None)
            logger.debug(f"DNS resolvido | host={host} ({elapsed}s)")
            return
        except socket.gaierror:
            await asyncio.sleep(2)
    logger.warning(f"DNS não resolvido após {timeout}s | host={host}")


def _get_container_ip() -> str:
    """
    Retorna o IP real do container no overlay Docker.

    Raftify precisa de um IP bindável (não a VIP do serviço Swarm).
    A VIP é roteável externamente mas não pode ser usada como bind address.
    O IP do container é tanto bindável quanto roteável dentro do overlay.
    """
    import socket
    import subprocess
    try:
        result = subprocess.run(["hostname", "-i"], capture_output=True, text=True)
        for ip in result.stdout.strip().split():
            if not ip.startswith("127.") and "." in ip:
                return ip
    except Exception:
        pass
    return socket.gethostbyname(socket.gethostname())


async def _init_raft(fsm: CoordinatorFSM):
    """
    Inicializa o nó RAFT via raftify 0.1.67 usando padrão leader-first.

    Coordinator-1 inicia sozinho como líder.
    Coordinators 2-4 obtêm ticket via request_id e entram com join_cluster.

    Usa o IP real do container como addr (não a VIP do serviço Swarm nem
    0.0.0.0), pois raftify tenta bind no addr fornecido.
    Para conectar ao coordinator-1, usa a VIP via nome do serviço —
    Docker roteia corretamente para o container.
    """
    import os
    os.makedirs("./raft-data", exist_ok=True)

    raft_config = RaftConfig(election_tick=10, heartbeat_tick=3)
    config = Config(raft_config=raft_config, log_dir="./raft-data")
    slogger = Slogger.default()

    raft_port = RAFT_ADDR.split(":")[-1]
    container_ip = _get_container_ip()
    bind_addr = f"{container_ip}:{raft_port}"
    logger.info(f"RAFT addr | container_ip={container_ip} bind={bind_addr}")

    # Cada coordinator é um líder de cluster de 1 nó (sem cluster distribuído por enquanto)
    # Quando request_id/join_cluster funcionar, ativamos a lógica de clustering distribuído
    raft_inst = Raft.bootstrap(
        node_id=NODE_NUM,
        addr=bind_addr,
        fsm=fsm,
        config=config,
        logger=slogger,
    )

    async def _run_raft():
        try:
            await raft_inst.run()
        except Exception as exc:
            logger.error(f"RAFT run() encerrou com erro | node={NODE_ID} erro={exc}")

    _background_tasks.append(asyncio.create_task(_run_raft(), name="raft_run"))

    # Aguarda o nó eleger-se líder antes de aceitar propostas
    node = raft_inst.get_raft_node()
    for _ in range(30):
        try:
            if await node.is_leader():
                break
        except Exception:
            pass
        await asyncio.sleep(0.2)
    else:
        logger.warning(f"RAFT ainda não é líder após 6s | node={NODE_ID}")

    logger.info(f"RAFT iniciado | node={NODE_ID} addr={bind_addr}")
    return raft_inst, node


# ── Métricas Prometheus ───────────────────────────────────────────────────────

class _CottonNetCollector:
    """
    Collector Prometheus para métricas de negócio do COTTON-NET.

    Lê os valores atuais de `fsm` e `pending` a cada scrape,
    sem necessidade de background tasks ou modificação do FSM.
    """

    def collect(self):
        if fsm is not None:
            g = GaugeMetricFamily(
                "cotton_nym_applied_total",
                "Total de transações NYM aplicadas pelo FSM RAFT neste nó",
                labels=["node_id"],
            )
            g.add_metric([NODE_ID], float(fsm.applied))
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


class RegisterResponse(BaseModel):
    success: bool
    txn_id:  str = ""
    error:   str = ""


class StatusResponse(BaseModel):
    node_id:     str
    raft_leader: bool
    supernodo:   str
    alive:       bool
    pending:     int


@app.post("/register", response_model=RegisterResponse)
async def register(req: RegisterRequest):
    """
    Registra uma entidade no ledger via consenso RAFT + Indy.

    O líder RAFT propõe a entrada ao cluster. Após quórum,
    cada nó aplica via FSM (submit_nym no Indy local).
    """
    if not registry.local.alive:
        raise HTTPException(
            status_code=503,
            detail=f"Supernodo local indisponível | node={NODE_ID}",
        )

    entry = NymLogEntry(
        entity_id   = req.entity_id,
        entity_type = req.entity_type,
        did         = req.did,
        verkey      = req.verkey,
    )

    try:
        # Propõe ao cluster RAFT — bloqueia até quórum ou timeout
        await raft_node.propose(entry.encode())
        logger.info(
            f"Entrada proposta ao RAFT | "
            f"entity_id={req.entity_id} did={req.did}"
        )
        return RegisterResponse(success=True)

    except Exception as e:
        logger.error(f"Falha ao propor ao RAFT | entity_id={req.entity_id} erro={e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status", response_model=StatusResponse)
async def status():
    """Retorna o status deste nó: RAFT, supernodo e pendências."""
    return StatusResponse(
        node_id     = NODE_ID,
        raft_leader = (await raft_node.is_leader()) if raft_node else False,
        supernodo   = registry.local.genesis_url,
        alive       = registry.local.alive,
        pending     = pending.size,
    )


@app.get("/health")
async def health():
    """Health check para Docker Swarm e load balancers."""
    return {"status": "ok", "node": NODE_ID}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)