"""
FSM — Finite State Machine do Coordinator COTTON-NET.

No raftify, a FSM é o coração da aplicação: é ela que define
o que acontece quando o RAFT confirma um commit. Cada nó do
cluster executa a FSM de forma independente, garantindo que
todos apliquem as mesmas entradas na mesma ordem.

No COTTON-NET:
    - O commit RAFT representa consenso externo entre supernodos
    - A FSM.apply() executa o consenso interno: submit_nym no Indy local
    - Se o Indy local falhar, a transação vai para a PendingQueue

Referência raftify:
    A FSM deve implementar os métodos (duck typing, sem herança):
        apply(entry)     → aplica uma entrada confirmada
        snapshot()       → serializa estado atual (para log compaction)
        restore(data)    → restaura estado a partir de snapshot
"""
import asyncio
import json
import os
import queue
import time
from loguru import logger
from prometheus_client import Counter, Histogram

from log_entry import NymLogEntry
from pending import PendingQueue
from cottontrust_core.ledger import submit_nym

_NODE_ID = os.environ["NODE_ID"]

# Latência da submissão NYM ao ledger Indy local (consenso interno Hyperledger)
INDY_WRITE_LATENCY = Histogram(
    "cotton_indy_write_duration_seconds",
    "Latência da submissão NYM ao supernodo Indy local",
    ["node_id"],
    buckets=[.1, .25, .5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0],
)

# Tempo que uma entrada aguarda na fila do FSM antes de ser processada
FSM_QUEUE_WAIT = Histogram(
    "cotton_fsm_queue_wait_seconds",
    "Tempo de espera na fila do FSM entre apply() e processamento efetivo",
    ["node_id"],
    buckets=[.001, .005, .01, .025, .05, .1, .25, .5, 1.0],
)

# Counters de throughput e taxa de sucesso por nó
NYM_ATTEMPTED = Counter(
    "cotton_nym_attempted_total",
    "NYMs tentados pelo FSM neste nó (todas as tentativas iniciais via RAFT)",
    ["node_id"],
)
NYM_APPLIED = Counter(
    "cotton_nym_applied_total",
    "NYMs confirmados com sucesso no ledger Indy local — use rate() para throughput",
    ["node_id"],
)
NYM_FAILED = Counter(
    "cotton_nym_failed_total",
    "NYMs que falharam na submissão ao Indy e foram para a fila de retry",
    ["node_id"],
)


class CoordinatorFSM:
    """
    Máquina de estados do Coordinator.

    Aplica entradas de log confirmadas pelo RAFT submetendo
    a transação NYM ao supernodo Indy local.

    Attributes:
        pool:    Conexão com o pool Indy local (supernodo desta máquina).
        store:   Wallet do trustee (para assinar transações).
        trustee_did: DID do trustee endossador.
        pending: Fila de retry para falhas de submissão.
        applied: Contador de entradas aplicadas com sucesso.
    """

    def __init__(self, pool, store, trustee_did: str, pending: PendingQueue):
        self._loop       = asyncio.get_event_loop()  # exigido pelo pyo3_asyncio do raftify
        self.pool        = pool
        self.store       = store
        self.trustee_did = trustee_did
        self.pending     = pending
        self.applied       = 0
        self.bytes_written = 0
        self._entity_timing: dict = {}   # entity_id → {queue_wait_sec, indy_time_sec, tx_size_bytes}
        self._queue: queue.Queue = queue.Queue()

    async def apply(self, data: bytes) -> bytes:
        """
        Aplica entrada confirmada pelo RAFT.

        Raftify espera async def (retorna corrotina). O trabalho real
        é enfileirado numa queue.Queue thread-safe e processado pelo
        task _drain_queue() que roda no event loop do asyncio.
        Assim evitamos chamar asyncio de dentro do thread Tokio.
        """
        if not data:
            return b""
        try:
            entry = NymLogEntry.decode(data)
        except Exception:
            logger.debug(f"FSM: entrada não-NYM ignorada | bytes={len(data)}")
            return b""

        logger.info(f"FSM enfileirando | entity_id={entry.entity_id} did={entry.did}")
        self._queue.put_nowait((entry, time.monotonic()))
        return b""

    async def drain_queue(self) -> None:
        """Task permanente que drena a fila de entradas confirmadas pelo RAFT."""
        while True:
            while not self._queue.empty():
                entry, t_enqueue = self._queue.get_nowait()
                queue_wait = time.monotonic() - t_enqueue
                FSM_QUEUE_WAIT.labels(node_id=_NODE_ID).observe(queue_wait)
                await self._submit_nym(entry, queue_wait)
            await asyncio.sleep(0.05)

    async def _submit_nym(self, entry: "NymLogEntry", queue_wait: float = 0.0) -> None:
        NYM_ATTEMPTED.labels(node_id=_NODE_ID).inc()
        try:
            t_indy_start = time.monotonic()
            _, tx_size = await submit_nym(
                pool          = self.pool,
                store         = self.store,
                submitter_did = self.trustee_did,
                target_did    = entry.did,
                verkey        = entry.verkey,
            )
            indy_time = time.monotonic() - t_indy_start
            INDY_WRITE_LATENCY.labels(node_id=_NODE_ID).observe(indy_time)
            NYM_APPLIED.labels(node_id=_NODE_ID).inc()
            self.applied += 1
            self.bytes_written += tx_size
            self._entity_timing[entry.entity_id] = {
                "queue_wait_sec": round(queue_wait, 6),
                "indy_time_sec":  round(indy_time, 6),
                "tx_size_bytes":  tx_size,
            }
            logger.info(
                f"NYM aplicado | entity_id={entry.entity_id} "
                f"did={entry.did} size={tx_size}B "
                f"queue={queue_wait:.3f}s indy={indy_time:.3f}s total={self.applied}"
            )
        except Exception as e:
            NYM_FAILED.labels(node_id=_NODE_ID).inc()
            logger.error(f"FSM: falha ao submeter NYM | entity_id={entry.entity_id} erro={e}")
            await self.pending.enqueue(entry, error=str(e))

    async def snapshot(self) -> bytes:
        """
        Serializa o estado atual para log compaction do RAFT.

        Por ora, persiste apenas o contador de entradas aplicadas
        e as transações pendentes de retry.
        """
        state = {
            "applied": self.applied,
            "pending": await self.pending.snapshot_data(),
        }
        return json.dumps(state).encode("utf-8")

    async def restore(self, snapshot: bytes) -> None:
        """
        Restaura estado a partir de um snapshot do RAFT.

        Reconstrói a fila de pendências para que o retry
        continue após uma reinicialização do nó.
        """
        state = json.loads(snapshot.decode("utf-8"))
        self.applied = state.get("applied", 0)

        for item in state.get("pending", []):
            entry = NymLogEntry(
                entity_id   = item["entity_id"],
                entity_type = item["entity_type"],
                did         = item["did"],
                verkey      = item["verkey"],
            )
            await self.pending.enqueue(entry)

        logger.info(
            f"FSM restaurada | "
            f"aplicados={self.applied} "
            f"pendentes={self.pending.size}"
        )