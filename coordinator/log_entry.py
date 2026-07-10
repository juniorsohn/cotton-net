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


@dataclass
class NymLogEntry:
    """
    Entrada de log representando o registro de uma ENTIDADE no ledger Indy.

    Attributes:
        entity_id:   Identificador único da entidade.
        entity_type: Tipo da entidade ('uba', 'bale', etc.).
        did:         DID a ser registrado no ledger.
        verkey:      Chave pública Ed25519 associada ao DID.
        role:        Role de ledger a conceder após o NYM (ex.: 'ENDORSER');
                     "" = sem role. Usado só com WORKLOAD_PARITY=1 no FSM.
        raw_attrs:   Atributos públicos para o ATTRIB (espelha o passo 4 do
                     CT em client/entities/base.py); None = sem ATTRIB.
                     Usado só com WORKLOAD_PARITY=1 no FSM.

    Campos novos têm default → entradas antigas (JSON sem os campos)
    continuam decodificáveis.
    """
    entity_id:   str
    entity_type: str
    did:         str
    verkey:      str
    role:        str = ""
    raw_attrs:   dict | None = None

    def encode(self) -> bytes:
        """
        Serializa a entrada para bytes (JSON). Chamado pelo raftify.

        Campos vazios (role=""/raw_attrs=None) são OMITIDOS: com paridade
        desligada a entrada fica byte-idêntica ao formato legado de 4 campos
        — nenhum byte extra viaja pelo RAFT dentro de coordinator_time_sec.
        """
        d = asdict(self)
        if not d.get("role"):
            d.pop("role", None)
        if d.get("raw_attrs") is None:
            d.pop("raw_attrs", None)
        return json.dumps(d).encode("utf-8")

    @classmethod
    def decode(cls, data: bytes) -> "NymLogEntry":
        """Desserializa bytes para NymLogEntry. Chamado pelo raftify."""
        return cls(**json.loads(data.decode("utf-8")))