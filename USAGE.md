# COTTON-NET — Guia de Utilização

Guia operacional completo: setup de ambiente, distribuição entre
máquinas, fluxo de experimento e monitoramento.

---

## Índice

1. [Topologia física](#1-topologia-física)
2. [Pré-requisitos](#2-pré-requisitos)
3. [Setup único (primeira execução)](#3-setup-único-primeira-execução)
4. [Configuração do ambiente](#4-configuração-do-ambiente)
5. [Fluxo de experimento](#5-fluxo-de-experimento)
6. [Monitoramento](#6-monitoramento)
7. [Referência de comandos](#7-referência-de-comandos)
8. [Variáveis de ambiente](#8-variáveis-de-ambiente)
9. [Solução de problemas](#9-solução-de-problemas)

---

## 1. Topologia física

```
┌──────────────────────────────────────────────────────────────────────┐
│  baia1              baia2              baia3              baia4       │
│                                                                       │
│  coordinator-1      coordinator-2      coordinator-3      coordinator-4│
│  :8001 (API HTTP)   :8002              :8003              :8004       │
│  :60061 (RAFT)      :60061             :60061             :60061      │
│                                                                       │
│  VON Network S1     VON Network S2     VON Network S3     VON Network S4│
│  :9000 (genesis)    :9000              :9000              :9000       │
│  Kn nós Indy/RBFT   Kn nós Indy/RBFT   Kn nós Indy/RBFT  Kn nós Indy/RBFT│
│                                                                       │
│  ◄──────────────── RAFT cluster (overlay Docker) ──────────────────► │
│                                                                       │
├──────────────────────────────────────────────────────────────────────┤
│  baia5                                                                │
│                                                                       │
│  cottonclient    → POST /register → coordinator-1 → RAFT → Indy×4   │
│  prometheus      :9090                                                │
│  grafana         :3000                                                │
│  cadvisor        :8080   (mode: global — roda em todas as baias)     │
└──────────────────────────────────────────────────────────────────────┘
```

**Kn** = número de nós Indy por supernodo = `NODES / 4`.
Mínimo: `Kn = 4` (exigência do PBFT do Hyperledger Indy), ou seja, `NODES ≥ 16`.

---

## 2. Pré-requisitos

### Em todas as baias (baia1–baia5)

```bash
# Docker Engine >= 24
docker --version

# Python 3.10+ (apenas em baia5 para execução local, opcional)
python3 --version
```

### Em baia1–baia4 (supernodos)

```bash
# von-network clonado e construído
git clone https://github.com/bcgov/von-network /home/indy/von-network
cd /home/indy/von-network
./manage build
```


---

## 3. Setup único (primeira execução)

Execute **uma única vez**, de baia1:

```bash
cd /path/to/cottonnet

# 1. Inicializa Docker Swarm
#    baia1 = manager | baia2, baia3, baia4, baia5 = workers
make swarm-init

# Verifica os nós
docker node ls
# ID         HOSTNAME  STATUS  AVAILABILITY  MANAGER STATUS
# xxx *      baia1     Ready   Active        Leader
# yyy        baia2     Ready   Active
# zzz        baia3     Ready   Active
# www        baia4     Ready   Active
# vvv        baia5     Ready   Active

# 2. Sobe registry Docker local em baia1:5000
#    Todos os nós do Swarm usam esse registry para puxar as imagens
make registry-start
```

---

## 4. Configuração do ambiente

```bash
cp .env.example .env
```

Edite `.env` com os valores do seu ambiente. Os valores abaixo
funcionam com o VON Network padrão (Trustee1):

```env
GENESIS_URL=http://baia1:9000/genesis    # usado apenas no modo direto
TRUSTEE_SEED=000000000000000000000000Trustee1
TRUSTEE_DID=V4SGRU86Z58d6TV7PBUe6f
WALLET_KEY=changeme_em_producao
LOG_LEVEL=INFO
# COORDINATOR_URL já definido no docker-compose para modo COTTON-NET
```

> `COORDINATOR_URL` já está configurado como `http://coordinator-1:8000`
> no `docker-compose.yml`. Não é necessário definir no `.env` para o deploy
> via Swarm — só para execução local do client.

---

## 5. Fluxo de experimento

O fluxo completo de um experimento é:

```
von-start → build → push → deploy → [observar] → teardown → von-stop
```

### 5.1 Iniciar os VON Networks (supernodos Indy)

```bash
# Kn = NODES / 4 nós Indy por supernodo
# Experimentos sugeridos: NODES = 16 (Kn=4), 32 (Kn=8), 64 (Kn=16)

make von-start NODES=32
```

O script conecta via SSH em paralelo para baia1–baia4, inicia os VON
Networks e aguarda cada genesis endpoint responder antes de continuar.
Saída esperada:

```
╔══════════════════════════════════════════════════════╗
║         COTTON-NET — VON Network Setup               ║
║  Total de nós:    32                                  ║
║  Supernodos (Sn): 4                                   ║
║  Nós por Sn (Kn): 8                                   ║
╚══════════════════════════════════════════════════════╝

⏳ Aguardando genesis endpoints...
   S1 (http://baia1:9000/genesis) ......... ✅
   S2 (http://baia2:9000/genesis) ......... ✅
   S3 (http://baia3:9000/genesis) ......... ✅
   S4 (http://baia4:9000/genesis) ......... ✅

✅ Todos os 4 supernodos prontos!
```

Verificação rápida após o início:

```bash
make von-status
#   ✅ http://baia1:9000/genesis
#   ✅ http://baia2:9000/genesis
#   ✅ http://baia3:9000/genesis
#   ✅ http://baia4:9000/genesis
```

### 5.2 Build e push das imagens

```bash
make push
# Constrói localmente e envia para baia1:5000
# (necessário apenas quando há alterações no código)
```

### 5.3 Deploy do stack

```bash
make deploy
# docker stack deploy -c docker-compose.yml cottontrust
```

Após o deploy, o RAFT precisa de ~10–30s para eleger o líder.
Acompanhe com:

```bash
make status
# ID    NAME                           NODE   STATE    PORTS
# ...   cottontrust_coordinator-1      baia1  Running  *:8001->8000/tcp
# ...   cottontrust_coordinator-2      baia2  Running  *:8002->8000/tcp
# ...   cottontrust_coordinator-3      baia3  Running  *:8003->8000/tcp
# ...   cottontrust_coordinator-4      baia4  Running  *:8004->8000/tcp
# ...   cottontrust_cottonclient       baia5  Running
# ...   cottontrust_prometheus         baia5  Running  *:9090->9090/tcp
# ...   cottontrust_grafana            baia5  Running  *:3000->3000/tcp
# ...   cottontrust_cadvisor           baia1  Running  *:8080->8080/tcp
# ...   (+ cadvisor em baia2, 3, 4, 5 — mode: global)
```

### 5.4 Acompanhar a execução

```bash
# Logs do cottonclient (experimento principal)
make logs-client

# Saída típica:
# 2025-05-24 10:00:01 | INFO | COTTONTRUST iniciando
# 2025-05-24 10:00:01 | INFO | Pool:    http://baia1:9000/genesis
# 2025-05-24 10:00:01 | INFO | Modo:    COORDINATOR — http://coordinator-1:8000
# 2025-05-24 10:00:02 | INFO | Registrando 4 UBA(s)...
# 2025-05-24 10:00:02 | INFO | UBA registrado [coordinator] | id=UBA-2025-001 did=... tempo=0.412s
# 2025-05-24 10:00:03 | INFO | UBA registrado [coordinator] | id=UBA-2025-002 did=... tempo=0.389s
# 2025-05-24 10:00:05 | INFO | Registrando 6 Bale(s)...
# 2025-05-24 10:00:09 | INFO | COTTONTRUST concluído
# 2025-05-24 10:00:09 | INFO | Transações:  10
# 2025-05-24 10:00:09 | INFO | Tempo total: 4.821s
# 2025-05-24 10:00:09 | INFO | Média/tx:    0.482s

# Logs de um coordinator específico
make logs-coord NODE=1
# 2025-05-24 10:00:02 | INFO | node-1 | FSM aplicando | entity_id=UBA-2025-001
# 2025-05-24 10:00:02 | INFO | node-1 | NYM aplicado pelo FSM | size=312B total_aplicados=1
```

### 5.5 Coletar métricas

O CSV de métricas é salvo em `/app/output/raw_tx_metrics.csv` no container
do cottonclient. Para extrair:

```bash
# ID do serviço
SVC=$(docker ps --filter name=cottontrust_cottonclient -q)

docker cp $SVC:/app/output/raw_tx_metrics.csv ./results/metrics_kn8.csv
```

Colunas do CSV:

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `pool` | string | Hostname do genesis URL (ex: `baia1`) |
| `operation` | string | `create_uba` ou `create_bale` |
| `tx_time_sec` | float | Tempo total da transação (s) |
| `tx_size_bytes` | int | Tamanho do payload NYM (0 no modo coordinator) |
| `timestamp` | ISO 8601 | Data e hora da transação |

### 5.6 Teardown e próximo experimento

```bash
make teardown    # Remove o stack (mantém VON Networks)
make von-stop    # Para os VON Networks em baia1..baia4

# Próximo experimento com Kn diferente:
make von-start NODES=16   # Kn=4 — mínimo PBFT
make deploy
```

**Atalho**: `make experiment NODES=32` combina `von-start` + `deploy`.

---

## 6. Monitoramento

### Grafana — `http://baia5:3000`

Credenciais padrão: `admin` / `cottontrust`
(altere via `GRAFANA_PASSWORD` no `.env`).

### Prometheus — `http://baia5:9090`

Queries úteis para os experimentos:

```promql
# NYMs confirmados por nó do RAFT
cotton_nym_applied_total

# Fila de retry (transações que falharam no Indy e aguardam re-submissão)
cotton_pending_queue_size

# Latência p50 / p95 / p99 do endpoint /register
histogram_quantile(0.50, rate(http_request_duration_seconds_bucket{handler="/register"}[5m]))
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{handler="/register"}[5m]))
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{handler="/register"}[5m]))

# Taxa de registros confirmados por segundo
rate(http_requests_total{handler="/register", status="2xx"}[1m])

# CPU por container (cAdvisor)
rate(container_cpu_usage_seconds_total{name=~"cottontrust.*"}[1m])

# Memória por container
container_memory_usage_bytes{name=~"cottontrust.*"}
```

### Status direto via API

Cada coordinator expõe `GET /status`:

```bash
curl http://baia1:8001/status | python3 -m json.tool
# {
#   "node_id": "node-1",
#   "raft_leader": true,
#   "supernodo": "http://baia1:9000/genesis",
#   "alive": true,
#   "pending": 0
# }

# Verificar todos:
for n in 1 2 3 4; do
  PORT=$((8000 + n))
  echo "=== coordinator-$n ==="
  curl -sf http://baia$n:$PORT/status | python3 -m json.tool
done
```

---

## 7. Referência de comandos

```
make swarm-init              Inicializa Docker Swarm (baia1=manager, baia2-5=workers)
make registry-start          Sobe registry local em baia1:5000

make von-start  NODES=N      Inicia VON Networks com N nós totais (padrão: 32)
make von-stop                Para todos os VON Networks
make von-status              Verifica genesis endpoints em baia1..baia4

make build                   Constrói imagens Docker localmente
make push                    build + push para baia1:5000
make deploy                  Deploy do stack completo no Swarm
make teardown                Remove o stack

make logs-client             Logs em tempo real do cottonclient
make logs-coord NODE=N       Logs em tempo real do coordinator-N (N=1..4)
make status                  Lista serviços e em qual nó estão rodando

make experiment NODES=N      von-start + deploy de uma vez
```

---

## 8. Variáveis de ambiente

| Variável | Obrigatória | Default | Onde é usada |
|----------|:-----------:|---------|--------------|
| `GENESIS_URL` | ✅ | — | client (modo direto) e coordinators |
| `TRUSTEE_SEED` | ✅ | — | client e coordinators |
| `TRUSTEE_DID` | ✅ | — | client e coordinators |
| `WALLET_KEY` | — | `changeme` | client e coordinators |
| `COORDINATOR_URL` | — | não definido | client — ativa modo COTTON-NET |
| `NODE_ID` | — | — | coordinator — label nos logs (ex: `node-1`) |
| `NODE_NUM` | — | — | coordinator — ID inteiro no raftify (1..4) |
| `RAFT_ADDR` | — | — | coordinator — endereço de escuta RAFT |
| `RAFT_PEERS` | — | — | coordinator — endereços dos outros nós |
| `API_PORT` | — | `8000` | coordinator — porta da API HTTP |
| `LOG_LEVEL` | — | `INFO` | todos — `DEBUG` para bytes e latências |
| `WALLET_DIR` | — | `/app/wallets` | todos — útil para execução local |
| `MODELS_DIR` | — | `/app/models` | client — diretório dos JSONs de entrada |
| `METRICS_OUTPUT` | — | `/app/output/raw_tx_metrics.csv` | client |
| `GRAFANA_PASSWORD` | — | `cottontrust` | grafana |

---

## 9. Solução de problemas

### Genesis não responde após `make von-start`

```bash
# Verificar logs do VON Network em uma baia específica
ssh indy@baia2 "cd /home/indy/von-network && ./manage logs"

# Reiniciar manualmente
ssh indy@baia2 "cd /home/indy/von-network && ./manage stop && ./manage start --nodes 8"
```

### RAFT não elege líder

O cluster RAFT precisa de quórum (3 de 4 nós). Se um coordinator
não subiu, os outros ficam presos na eleição.

```bash
# Ver qual coordinator está falhando
make status

# Logs do coordinator com falha
make logs-coord NODE=2

# Causas comuns:
# - GENESIS_URL errado (supernodo Indy não respondeu antes do coordinator subir)
# - PORT 60061 bloqueado entre as baias
# - NODE_NUM incorreto no docker-compose.yml
```

### Coordinator retorna 503 para o client

O supernodo Indy local está indisponível (`alive=false`). O coordinator
rejeita requisições quando seu Sn local não está respondendo.

```bash
curl http://baia1:8001/status
# "alive": false  ← problema no VON Network de baia1

make von-status  # verifica todos
```

### Transações ficando na fila de retry (`pending > 0`)

O coordinator aceitou a transação via RAFT mas falhou ao aplicar no Indy.
O retry acontece automaticamente com backoff exponencial (máx. 5 min).

```bash
# Monitorar a fila
curl http://baia1:8001/status | python3 -c "import sys,json; d=json.load(sys.stdin); print('pending:', d['pending'])"

# Ver erros no log
make logs-coord NODE=1 | grep "Retry falhou"
```

### Executar o client localmente (fora do Docker)

```bash
cd client
pip install -r requirements.txt

# Modo direto (sem coordinator)
export GENESIS_URL=http://baia1:9000/genesis
export TRUSTEE_SEED=000000000000000000000000Trustee1
export TRUSTEE_DID=V4SGRU86Z58d6TV7PBUe6f
export WALLET_DIR=./wallets   # evita /app/wallets hardcoded

python main.py

# Modo COTTON-NET (com coordinator rodando no Swarm)
export COORDINATOR_URL=http://baia1:8001
python main.py
```
