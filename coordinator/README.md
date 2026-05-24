# COTTON-NET Coordinator

Árbitro da camada externa de consenso do COTTON-NET.

Cada instância do Coordinator roda em uma máquina física junto
com um Supernodo Indy (VON Network). O conjunto forma um nó Sn
da arquitetura COTTON-NET.

## Responsabilidades

```
┌─────────────────────────────────────────────┐
│              COORDINATOR                     │
│                                             │
│  FastAPI ──→ RAFT (raftify) ──→ FSM ──→ Indy│
│                                             │
│  /register   propõe entrada   submit_nym    │
│  /status     replica p/ peers  (indy-vdr)   │
│  /health     quórum           PendingQueue  │
└─────────────────────────────────────────────┘
```

## Camadas de consenso

| Camada | Componente | Algoritmo |
|---|---|---|
| Externa (entre Sn) | raftify | RAFT (tikv/raft-rs) |
| Interna (dentro de Sn) | Indy Plenum | RBFT |

## Configuração

Variáveis de ambiente obrigatórias:

| Variável | Descrição | Exemplo |
|---|---|---|
| `NODE_ID` | Identificador único deste nó | `node-1` |
| `RAFT_ADDR` | Endereço RAFT deste nó | `0.0.0.0:60061` |
| `RAFT_PEERS` | Endereços dos outros nós | `node-2:60061,node-3:60061` |
| `GENESIS_URL` | Genesis do supernodo Indy local | `http://s1:9000/genesis` |
| `TRUSTEE_SEED` | Seed do trustee | `000000000000000000000000Trustee1` |
| `TRUSTEE_DID` | DID do trustee | `V4SGRU86Z58d6TV7PBUe6f` |
| `WALLET_KEY` | Chave das wallets | `changeme` |

## Execução local (desenvolvimento)

```bash
pip install -r requirements.txt
pip install grpcio-tools

# Gera stubs protobuf
python -m grpc_tools.protoc \
    -I proto \
    --python_out=generated \
    --grpc_python_out=generated \
    proto/coordinator.proto

# Sobe um nó único (sem peers — modo desenvolvimento)
NODE_ID=node-1 \
RAFT_ADDR=0.0.0.0:60061 \
GENESIS_URL=http://localhost:9000/genesis \
TRUSTEE_SEED=000000000000000000000000Trustee1 \
TRUSTEE_DID=V4SGRU86Z58d6TV7PBUe6f \
uvicorn main:app --host 0.0.0.0 --port 8000
```

## API HTTP

| Endpoint | Método | Descrição |
|---|---|---|
| `/register` | POST | Registra entidade via RAFT + Indy |
| `/status` | GET | Status do nó (RAFT, supernodo, pendências) |
| `/health` | GET | Health check para Swarm |

### Exemplo de registro

```bash
curl -X POST http://coordinator:8000/register \
  -H "Content-Type: application/json" \
  -d '{
    "entity_id":   "UBA-001",
    "entity_type": "uba",
    "did":         "Bxq9jsrjFzaWKYJs84HLGU",
    "verkey":      "AtZGhUzqCBHHxqyQWJfcMH7CfRn3..."
  }'
```

## Estrutura

```
coordinator/
├── main.py         # FastAPI + ciclo de vida
├── fsm.py          # Máquina de estados RAFT → Indy
├── log_entry.py    # Estrutura de dados replicada
├── supernodes.py   # Conexão com o Indy local
├── pending.py      # Fila de retry (consistência eventual)
├── proto/          # Definição da API (protobuf)
│   └── coordinator.proto
└── generated/      # Gerado em build — não commitar
    ├── coordinator_pb2.py
    └── coordinator_pb2_grpc.py
```

## .gitignore recomendado

```
coordinator/generated/
coordinator/raft-data/
coordinator/wallets/
```