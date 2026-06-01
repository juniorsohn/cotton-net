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
    A FSM deve implementar AbstractStateMachine com os métodos:
        apply(entry)     → aplica uma entrada confirmada
        snapshot()       → serializa estado atual (para log compaction)
        restore(data)    → restaura estado a partir de snapshot
"""
import json
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

    async def apply(self, data: bytes) -> bytes:
        """
        Aplica uma entrada confirmada pelo RAFT.

        Chamado pelo raftify após quórum atingido.
        Entradas no-op (vazias ou não-JSON) são ignoradas — o RAFT as emite
        internamente quando um novo líder é eleito.
        """
        if not data:
            return b""
        try:
            entry = NymLogEntry.decode(data)
        except Exception:
            logger.debug(f"FSM recebeu entrada não-NYM (no-op ou config), ignorando | bytes={len(data)}")
            return b""
        logger.info(
            f"FSM aplicando | entity_id={entry.entity_id} did={entry.did}"
        )

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
                f"NYM aplicado pelo FSM | "
                f"entity_id={entry.entity_id} "
                f"did={entry.did} "
                f"size={tx_size}B "
                f"total_aplicados={self.applied}"
            )
        except Exception as e:
            logger.error(
                f"FSM falhou ao submeter NYM | "
                f"entity_id={entry.entity_id} erro={e}"
            )
            await self.pending.enqueue(entry, error=str(e))

        return b""

    def encode(self) -> bytes:
        return json.dumps({"applied": self.applied}).encode()

    @classmethod
    def decode(cls, packed: bytes) -> "CoordinatorFSM":
        return cls.__new__(cls)

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