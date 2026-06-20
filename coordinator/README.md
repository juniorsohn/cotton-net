# COTTON-NET Coordinator

Árbitro da camada externa de consenso do COTTON-NET.

Cada instância coordena um supernodo Indy (VON Network) via RAFT.
No modo distribuído (`cn-*`), o coordinator pode rodar em qualquer
baia com acesso de rede ao genesis do seu supernodo.

## Responsabilidades

```
┌─────────────────────────────────────────────┐
│              COORDINATOR                     │
│                                             │
│  FastAPI ──→ RAFT (raftify) ──→ FSM ──→ Indy│
│                                             │
│  /register   propõe NymLogEntry  submit_nym │
│  /status     replica p/ peers   (indy-vdr)  │
│  /health     quórum             PendingQueue│
└─────────────────────────────────────────────┘
```

## Camadas de consenso

| Camada | Componente | Algoritmo |
|---|---|---|
| Externa (entre Sn) | raftify | RAFT (tikv/raft-rs) |
| Interna (dentro de Sn) | Indy Plenum | RBFT |

## Configuração

| Variável | Descrição | Exemplo |
|---|---|---|
| `NODE_ID` | Identificador único deste nó | `node-1` |
| `NODE_NUM` | ID numérico inteiro (raftify) | `1` |
| `RAFT_ADDR` | Endereço RAFT deste nó | `0.0.0.0:60061` |
| `RAFT_PEERS` | Endereços dos outros nós | `node-2:60061,node-3:60061` |
| `GENESIS_URL` | Genesis do supernodo Indy associado | `http://10.10.20.151:9000/genesis` |
| `TRUSTEE_SEED` | Seed do trustee | `000000000000000000000000Trustee1` |
| `TRUSTEE_DID` | DID do trustee | `V4SGRU86Z58d6TV7PBUe6f` |
| `WALLET_KEY` | Chave das wallets | `changeme` |
| `API_PORT` | Porta da API HTTP | `8000` |

No modo distribuído (`make cn-config`), todos esses valores são injetados
automaticamente no `docker-stack-cottonnet.yml` gerado.

## Execução local (desenvolvimento)

```bash
pip install -e ../packages/cottontrust-core
pip install -r requirements.txt

# Nó único sem peers — suficiente para desenvolvimento
NODE_ID=node-1 \
NODE_NUM=1 \
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
| `/status` | GET | Status do nó (RAFT, supernodo, fila FSM) |
| `/health` | GET | Health check para Swarm |
| `/metrics` | GET | Métricas Prometheus (nym_applied, pending_queue) |

### Exemplo de registro

```bash
curl -X POST http://coordinator:8000/register \
  -H "Content-Type: application/json" \
  -d '{
    "entity_id":   "ARM-001",
    "entity_type": "armazem",
    "did":         "Bxq9jsrjFzaWKYJs84HLGU",
    "verkey":      "AtZGhUzqCBHHxqyQWJfcMH7CfRn3..."
  }'
```

### Exemplo de status

```json
{
  "node_id":     "node-1",
  "raft_leader": true,
  "supernodo":   "http://10.10.20.151:9000/genesis",
  "alive":       true,
  "pending":     0
}
```

## Estrutura

```
coordinator/
├── main.py         # FastAPI + ciclo de vida (raftify, trustee, pending)
├── fsm.py          # CoordinatorFSM: RAFT commit → submit_nym no Indy local
├── log_entry.py    # NymLogEntry (encode/decode para o log RAFT)
├── supernodes.py   # SupernodeRegistry — conexão com o Indy do supernodo
└── pending.py      # PendingQueue — retry com backoff (consistência eventual)
```

## .gitignore recomendado

```
coordinator/raft-data/
coordinator/wallets/
```
