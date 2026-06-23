# COTTON-NET — Guia de Utilização

Guia operacional completo: setup de ambiente, fluxos de experimento e
monitoramento para os três modos suportados.

---

## Índice

1. [Topologia física](#1-topologia-física)
2. [Pré-requisitos](#2-pré-requisitos)
3. [Setup único](#3-setup-único)
4. [Configuração do ambiente](#4-configuração-do-ambiente)
5. [Modo A — COTTONTRUST Distribuído (baseline)](#5-modo-a--cottontrust-distribuído-baseline)
6. [Modo B — COTTON-NET Distribuído (principal)](#6-modo-b--cotton-net-distribuído-principal)
7. [Monitoramento](#7-monitoramento)
8. [Referência de comandos](#8-referência-de-comandos)
9. [Variáveis de ambiente](#9-variáveis-de-ambiente)
10. [Solução de problemas](#10-solução-de-problemas)

---

## 1. Topologia física

```
┌─────────────────────────────────────────────────────────────────┐
│  flores (10.10.20.151)   — Worker Swarm                         │
│  corisco (10.10.20.152)  — Worker Swarm                         │
│  baiacu (10.10.20.153)   — Worker Swarm                         │
│  pernambuco (10.10.20.154) — Worker Swarm                       │
│                                                                  │
│  Cada baia recebe NPM = Kn / 4 nós Indy por supernodo           │
│  (Kn = NODES / SUPERNODOS; mínimo Kn=4 pelo quórum RBFT)        │
├─────────────────────────────────────────────────────────────────┤
│  cacao (10.10.20.155)    — Manager Swarm                        │
│                                                                  │
│  coordinator-1..4  :8001-8004  (COTTON-NET)                     │
│  cottonclient                                                    │
│  prometheus        :9090                                         │
│  grafana           :3000                                         │
│  cadvisor          :8080   (mode: global — roda em todas)       │
└─────────────────────────────────────────────────────────────────┘
```

NFS compartilhado em todas as baias:
`/mnt/prj/g11718038933/cotton-net_2026/von-network`

---

## 2. Pré-requisitos

### Em todas as baias

```bash
docker --version          # >= 24
```

### Em flores (manager / registry)

```bash
# Repositório clonado
ls /mnt/prj/g11718038933/cotton-net_2026/cottonnet/

# von-network disponível no NFS
ls /mnt/prj/g11718038933/cotton-net_2026/von-network/manage
```

### Imagem von-network-base (todas as baias)

A imagem `von-network-base` deve estar disponível localmente em cada baia
que executará nós Indy. Construa uma vez (o build usa o NFS, portanto pode
ser executado de qualquer baia):

```bash
cd /mnt/prj/g11718038933/cotton-net_2026/von-network
DOCKER_API_VERSION=1.41 ./manage build
```

Para experimentos com `Kn > 100`, aplique o patch do Indy Plenum após o build:

```bash
# A partir do diretório do repositório cottonnet/:
make von-patch
```

O patch substitui o limite artificial de 100 nós por 10000 na imagem local.
É idempotente e inócuo para `Kn ≤ 100`.

---

## 3. Setup único

Execute uma única vez, de qualquer nó com acesso ao cluster:

```bash
cd /mnt/prj/g11718038933/cotton-net_2026/cottonnet/

# 1. Inicializa Docker Swarm (flores = manager, demais = workers)
make swarm-init

# Verifica os nós:
docker node ls

# 2. Sobe o registry Docker local em flores:5000
make registry-start

# 3. Constrói e envia as imagens do projeto
make push
```

---

## 4. Configuração do ambiente

```bash
cp .env.example .env
```

```env
TRUSTEE_SEED=000000000000000000000000Trustee1
TRUSTEE_DID=V4SGRU86Z58d6TV7PBUe6f
WALLET_KEY=changeme_em_producao
LOG_LEVEL=INFO
```

`GENESIS_URL` e `COORDINATOR_URL` são injetados automaticamente no
docker-stack gerado — não é necessário defini-los no `.env` para
experimentos via Swarm.

---

## 5. Modo A — COTTONTRUST Distribuído (baseline)

Pool Indy RBFT único com N nós distribuídos pelas 4 baias via Docker Swarm.
Sem camada RAFT. Serve como baseline de comparação para o COTTON-NET.

### 5.1 Gerar o stack

```bash
# NODES = total de nós Indy (mínimo 4, deve ser múltiplo de 4)
make ct-config NODES=16
```

O comando gera `docker-stack-cottontrust.yml` e injeta uma Docker Config
com o script `von_generate_transactions` customizado para N nós.

### 5.2 Deploy

```bash
make ct-deploy
```

Sobe os serviços:
- `webserver`: em cacao, porta 9000 — serve o genesis
- `node-1` .. `node-N`: distribuídos pelas 4 baias, `mode: host` (portas 9701+)
- `cottonclient`: em cacao, réplicas=0 (aguarda `ct-client-start`)

Aguarde os nós ficarem Running:

```bash
make ct-status
```

Verifique o genesis:

```bash
make ct-genesis
#   ✅ Genesis disponível: http://10.10.20.155:9000/genesis
```

### 5.3 Executar o experimento

```bash
make ct-client-start        # escala cottonclient para 1 réplica
make ct-logs-client         # acompanha em tempo real
```

### 5.4 Coletar métricas

```bash
SVC=$(docker ps --filter name=ct_cottonclient -q)
docker cp $SVC:/app/output/raw_tx_metrics.csv ./results/ct_n16.csv
```

### 5.5 Teardown

```bash
make ct-client-stop         # para o client (opcional se já terminou)
make ct-stop                # remove stack, configs e volumes
```

---

## 6. Modo B — COTTON-NET Distribuído (principal)

`Sn` supernodos, cada um com `Kn = NODES / Sn` nós Indy distribuídos pelas
4 baias. Genesis independente por supernodo. Coordinator com RAFT entre
supernodos. Mesma distribuição física do Modo A — comparação justa.

### 6.1 Pré-requisito: imagem patcheada

Para `Kn > 100`, o patch deve estar aplicado em todas as baias antes do deploy:

```bash
# Executar em cada baia (ou via SSH):
make von-patch
```

### 6.2 Gerar o stack

```bash
# NODES = total de nós Indy, SUPERNODOS = número de supernodos
make cn-config NODES=16 SUPERNODOS=4
# Kn = 16/4 = 4 nós por supernodo
```

O comando gera `docker-stack-cottonnet.yml` e cria Docker Configs no Swarm:
- `cn-gen-tx-sn${s}-kn${Kn}`: script `von_generate_transactions` customizado
  para gerar genesis de Kn nós com PORT_OFFSET por supernodo
- `cn-start-node-sn${s}-kn${Kn}`: script `start_node.sh` com offset de porta

### 6.3 Deploy

Use o deploy sequencial — é o fluxo recomendado:

```bash
make cn-deploy-seq NODES=16 SUPERNODOS=4
```

O deploy sequencial sobe um supernodo por vez, aguardando o genesis
responder antes de avançar para o próximo. Isso evita a condição de
corrida onde todos os nós tentam inicializar o ledger simultaneamente
(contenda no NFS + timeout de genesis nos coordinators).

Saída esperada:

```
=== Deploy sequencial COTTON-NET: 4 SN × 4 nós ===
SN2-SN4 pausados. Iniciando sequência...

--- SN1: escalando 4 nós Indy + webserver ---
Aguardando genesis SN1 em http://10.10.20.151:9000 ....... ✅ SN1 OK

--- SN2: escalando 4 nós Indy + webserver ---
Aguardando genesis SN2 em http://10.10.20.152:9000 ....... ✅ SN2 OK
...
✅ Todos os 4 supernodos com genesis OK
```

`make cn-deploy` (sem `-seq`) ainda está disponível para subir tudo de
uma vez, mas pode falhar com Kn alto devido à condição de corrida.

O cluster RAFT precisa de ~10–30s para eleger o líder após todos os
coordinators subirem.

### 6.4 Executar o experimento

```bash
make cn-client-start        # escala cottonclient para 1 réplica
make cn-logs-client         # acompanha em tempo real
make cn-logs-coord NODE=1   # logs do coordinator-1
```

### 6.5 Portas por supernodo (Kn=4, Sn=4)

| Baia | S1 | S2 | S3 | S4 |
|---|---|---|---|---|
| flores | 9701/9702 | 9709/9710 | 9717/9718 | 9725/9726 |
| corisco | 9703/9704 | 9711/9712 | 9719/9720 | 9727/9728 |
| baiacu | 9705/9706 | 9713/9714 | 9721/9722 | 9729/9730 |
| pernambuco | 9707/9708 | 9715/9716 | 9723/9724 | 9731/9732 |

`PORT_OFFSET = (s-1) × Kn × 2`. Para Kn=8: offsets 0, 16, 32, 48.

### 6.6 Coletar métricas

```bash
SVC=$(docker ps --filter name=cn_cottonclient -q)
docker cp $SVC:/app/output/raw_tx_metrics.csv ./results/cn_n16_s4.csv
```

### 6.7 Teardown

```bash
make cn-client-stop
make cn-stop NODES=16 SUPERNODOS=4   # remove stack, configs e volumes
```

---

## 7. Monitoramento

### Grafana — `http://10.10.20.155:3000`

Credenciais padrão: `admin` / `cottontrust`
(altere via `GRAFANA_PASSWORD` no `.env`).

### Prometheus — `http://10.10.20.155:9090`

Queries úteis:

```promql
# NYMs confirmados por nó do RAFT
cotton_nym_applied_total

# Fila de retry
cotton_pending_queue_size

# Latência p95 do /register
histogram_quantile(0.95,
  rate(http_request_duration_seconds_bucket{handler="/register"}[5m]))

# Taxa de registros por segundo
rate(http_requests_total{handler="/register", status="2xx"}[1m])

# CPU por container
rate(container_cpu_usage_seconds_total{name=~"cn_.*|ct_.*"}[1m])
```

### Status direto do coordinator

```bash
for n in 1 2 3 4; do
  echo "=== coordinator-$n ==="
  curl -sf http://10.10.20.155:$((8000 + n))/status | python3 -m json.tool
done
```

---

## 8. Referência de comandos

```
── Setup ─────────────────────────────────────────────────────────
make swarm-init              Inicializa Docker Swarm
make registry-start          Sobe registry local em flores:5000
make build                   Constrói imagens Docker
make push                    build + push para flores:5000

── Imagem von-network-base ──────────────────────────────────────
make von-patch               Patch indy-plenum: limite 100 → 10000 nós
make von-local-build         Build + patch na baia atual (sem iniciar rede)

── COTTONTRUST Distribuído (baseline) ───────────────────────────
make ct-config   NODES=N     Gera stack + docker config
make ct-deploy               Deploy do stack
make ct-stop                 Remove stack, config e volumes
make ct-status               Lista serviços e estados
make ct-genesis              Verifica genesis (cacao:9000)
make ct-client-start         Inicia cottonclient (0 → 1)
make ct-client-stop          Para cottonclient (1 → 0)
make ct-logs-client          Logs do cottonclient
make ct-logs-web             Logs do webserver

── COTTON-NET Distribuído (principal) ───────────────────────────
make cn-config   NODES=N SUPERNODOS=S  Gera stack + docker configs
make cn-deploy               Deploy simultâneo (todos os SN de uma vez)
make cn-deploy-seq           Deploy sequencial: um SN por vez (recomendado)
make cn-stop                 Remove stack, configs e volumes
make cn-status               Lista serviços e estados
make cn-genesis              Verifica genesis das 4 baias (:9000)
make cn-client-start         Inicia cottonclient (0 → 1)
make cn-client-stop          Para cottonclient (1 → 0)
make cn-logs-client          Logs do cottonclient
make cn-logs-coord NODE=N    Logs do coordinator-N
```

---

## 9. Variáveis de ambiente

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

## 10. Solução de problemas

### Genesis não responde

```bash
# Ver logs do webserver (modo CT)
docker service logs ct_webserver

# Ver logs do webserver de um supernodo (modo CN, supernodo 1)
docker service logs cn_webserver-sn1

# Verificar se os nós Indy estão Running
make ct-status   # ou: make cn-status
```

### RAFT não elege líder (modo CN)

O cluster RAFT precisa de quórum (3 de 4 coordinators). Causas comuns:

```bash
make cn-status        # identifica qual coordinator está falhando
make cn-logs-coord NODE=2

# Causas:
# - Genesis ainda não disponível quando o coordinator subiu
#   → aumente o delay de inicialização ou faça cn-stop + cn-deploy
# - Porta 60061 bloqueada entre baias
# - Volumes de raft-data de experimento anterior → make cn-stop limpa
```

### Coordinator retorna 503

O supernodo Indy local do coordinator está indisponível (`alive=false`).

```bash
curl http://10.10.20.155:8001/status | python3 -m json.tool
# "alive": false  ← problema no Indy do coordinator-1

make cn-genesis    # verifica todos os genesis
```

### Transações ficando na fila de retry (`pending > 0`)

O coordinator aceitou via RAFT mas falhou ao submeter ao Indy.
Retry automático com backoff exponencial (máx. 5 min).

```bash
curl http://10.10.20.155:8001/status | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('pending:', d['pending'])"

make cn-logs-coord NODE=1 | grep "Retry"
```

### Conflito de portas entre supernodos

Cada supernodo usa `PORT_OFFSET = (s-1) × Kn × 2`. Se o stack anterior
não foi removido corretamente, portas podem estar ocupadas.

```bash
make cn-stop NODES=<anterior> SUPERNODOS=<anterior>
```

### Patch do indy-plenum não persistiu

O patch é aplicado na imagem local `von-network-base`. Se a imagem foi
reconstruída (e.g., `./manage build` novamente), o patch precisa ser
reaplicado:

```bash
make von-patch
```

### Executar o client localmente (fora do Docker)

```bash
cd client
pip install -e ../packages/cottontrust-core
pip install -r requirements.txt

# Modo direto (sem coordinator)
export GENESIS_URL=http://10.10.20.155:9000/genesis
export TRUSTEE_SEED=000000000000000000000000Trustee1
export TRUSTEE_DID=V4SGRU86Z58d6TV7PBUe6f
export WALLET_DIR=./wallets

python main.py

# Modo COTTON-NET (coordinator já rodando no Swarm)
export COORDINATOR_URL=http://10.10.20.155:8001
python main.py
```
