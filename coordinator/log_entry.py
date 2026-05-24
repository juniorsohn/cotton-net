"""
LogEntry — estrutura de dados replicada pelo RAFT entre os Coordinators.

No raftify, o LogEntry representa uma entrada no log de consenso:
cada transação NYM que precisa ser aplicada a todos os supernodos
é serializada como um LogEntry e replicada via RAFT antes de ser
submetida ao ledger Indy local de cada nó.

Fluxo:
    1. Cliente envia RegisterRequest ao líder
    2. Líder cria NymLogEntry e propõe ao cluster RAFT
    3. RAFT replica para maioria → quórum atingido
    4. Cada nó chama FSM.apply(entry) → submit_nym no Indy local
    5. Líder responde ao cliente com confirmação

Referência:
    raftify requer que LogEntry implemente AbstractLogEntry,
    com métodos encode() e decode() para serialização binária.
"""
import json
from dataclasses import dataclass, asdict
from raftify import AbstractLogEntry


@dataclass
class NymLogEntry(AbstractLogEntry):
    """
    Entrada de log representando um registro NYM no ledger Indy.

    Attributes:
        entity_id:   Identificador único da entidade.
        entity_type: Tipo da entidade ('uba', 'bale', etc.).
        did:         DID a ser registrado no ledger.
        verkey:      Chave pública Ed25519 associada ao DID.
    """
    entity_id:   str
    entity_type: str
    did:         str
    verkey:      str

    def encode(self) -> bytes:
        """Serializa a entrada para bytes (JSON). Chamado pelo raftify."""
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def decode(cls, data: bytes) -> "NymLogEntry":
        """Desserializa bytes para NymLogEntry. Chamado pelo raftify."""
        return cls(**json.loads(data.decode("utf-8")))