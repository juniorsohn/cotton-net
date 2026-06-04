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
import queue
from loguru import logger

from log_entry import NymLogEntry
from pending import PendingQueue
from cottontrust_core.ledger import submit_nym


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
        self.pool        = pool
        self.store       = store
        self.trustee_did = trustee_did
        self.pending     = pending
        self.applied     = 0
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
        self._queue.put_nowait(entry)
        return b""

    async def drain_queue(self) -> None:
        """Task permanente que drena a fila de entradas confirmadas pelo RAFT."""
        while True:
            while not self._queue.empty():
                entry = self._queue.get_nowait()
                await self._submit_nym(entry)
            await asyncio.sleep(0.05)

    async def _submit_nym(self, entry: "NymLogEntry") -> None:
        try:
            _, tx_size = await submit_nym(
                pool          = self.pool,
                store         = self.store,
                submitter_did = self.trustee_did,
                target_did    = entry.did,
                verkey        = entry.verkey,
            )
            self.applied += 1
            logger.info(
                f"NYM aplicado | entity_id={entry.entity_id} "
                f"did={entry.did} size={tx_size}B total={self.applied}"
            )
        except Exception as e:
            logger.error(f"FSM: falha ao submeter NYM | entity_id={entry.entity_id} erro={e}")
            await self.pending.enqueue(entry, error=str(e))

    def encode(self) -> bytes:
        return json.dumps({"applied": self.applied}).encode()

    @classmethod
    def decode(cls, packed: bytes) -> "CoordinatorFSM":
        obj = cls.__new__(cls)
        obj._queue = queue.Queue()
        obj.applied = 0
        obj.pool = None
        obj.store = None
        obj.trustee_did = ""
        obj.pending = None
        if packed:
            try:
                state = json.loads(packed.decode("utf-8"))
                obj.applied = state.get("applied", 0)
            except Exception:
                pass
        return obj

    async def snapshot(self) -> bytes:
        """
        Serializa o estado atual para log compaction do RAFT.

        Por ora, persiste apenas o contador de entradas aplicadas
        e as transações pendentes de retry.
        """
        state = {
            "applied":  self.applied,
            "pending":  [
                {
                    "entity_id":   p.entry.entity_id,
                    "entity_type": p.entry.entity_type,
                    "did":         p.entry.did,
                    "verkey":      p.entry.verkey,
                    "attempts":    p.attempts,
                }
                for p in self.pending._queue.values()
            ],
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