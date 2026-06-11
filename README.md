# COTTONTRUST / COTTON-NET

Arquitetura descentralizada para rastreabilidade, confiabilidade e
auditabilidade na cadeia produtiva do algodão, baseada em
Self-Sovereign Identity (SSI) e Hyperledger Indy.

Desenvolvida no Laboratório de Processamento Paralelo e Distribuído
(LabP2D) — UDESC Joinville.

---

## Contexto

A cadeia produtiva do algodão é geograficamente distribuída e
internacionalmente fragmentada. A ausência de uma entidade
certificadora neutra e universalmente reconhecida gera retrabalho,
custos e perda de rastreabilidade.

O **COTTONTRUST** resolve isso usando DIDs (Decentralized Identifiers)
registrados em um ledger Hyperledger Indy: cada participante da cadeia
é identificado por um DID único, imutável e auditável, sem depender
de nenhuma autoridade central.

O **COTTON-NET** estende o COTTONTRUST com duas contribuições:

1. **Hierarquia de supernodos** (RAFT externo + RBFT interno) reduzindo
   o impacto do consenso em redes de grande escala.
2. **Cadeia SSI de endorsers** — cada entidade assina seu próprio DID
   (author), e a entidade-pai countersigns (endorser), tornando a
   rastreabilidade auditável ponta-a-ponta via assinaturas encadeadas.

---

## Arquitetura

```
                        ┌─────────────────────────┐
                        │     COTTONCLIENT         │
                        │  (aplicação Python)      │
                        └────────────┬─────────────┘
                                     │ HTTP (modo coordinator)
                                     │ ou direto ao Indy (modo direto)
                        ┌────────────▼─────────────┐
                        │      COORDINATOR          │
                        │  (árbitro COTTON-NET)     │
                        │  RAFT (raftify)           │
                        └──────┬──────────┬─────────┘
                               │          │
                ┌──────────────▼──┐   ┌───▼──────────────┐
                │  Supernodo S1   │   │  Supernodo S2     │
                │  VON Network    │   │  VON Network      │
                │  RBFT (4+ nós)  │   │  RBFT (4+ nós)   │
                └─────────────────┘   └──────────────────┘

                ┌──────────────────────────────────────────┐
                │           MONITORAMENTO                   │
                │   cAdvisor · Prometheus · Grafana         │
                └──────────────────────────────────────────┘
```

### Camadas de consenso

| Camada | Onde | Algoritmo | Responsabilidade |
|---|---|---|---|
| Interna | Dentro de cada Sn | RBFT (Indy Plenum) | Tolerância a falhas bizantinas |
| Externa | Entre supernodos | RAFT (raftify) | Eleição de líder e quórum de commit |

### Cadeia de endorsers SSI

```
Entidade  ←── trustee endossa
  └── Fazenda  ←── trustee endossa
        └── Setor  ←── Fazenda endossa
              └── Talhão  ←── Setor endossa
Armazém  ←── trustee endossa
  └── Lote MP  ←── Armazém endossa
Fardinho  ←── trustee endossa
```

Cada par NYM + ATTRIB transaction registra a identidade e os
atributos públicos da entidade. Dados sensíveis (CPF, CNPJ,
geolocalização) nunca vão ao ledger.

---

## Estrutura do repositório

```
cottonnet/
├── .env.example              # Variáveis de ambiente (copie para .env)
├── docker-compose.yml        # Stack completo (Docker Swarm)
├── Makefile                  # Workflow de experimentos
├── README.md                 # Este arquivo
│
├── client/                   # Cottonclient — aplicação Python
│   ├── main.py               # Orquestrador (7 níveis, concorrência por nível)
│   ├── config.py             # Configuração via .env
│   ├── coordinator.py        # Cliente HTTP do Coordinator (register + wait_for_drain)
│   ├── dockerfile
│   ├── requirements.txt
│   ├── entities/             # Modelo COTTON-CELL
│   │   ├── base.py           # CottonCell — setup NYM + ATTRIB + endorser
│   │   ├── entidade.py       # Empresa/cooperativa produtora
│   │   ├── fazenda.py        # Propriedade rural
│   │   ├── setor.py          # Subdivisão da fazenda
│   │   ├── talhao.py         # Parcela agrícola (unidade de cultivo)
│   │   ├── armazem.py        # Unidade de Beneficiamento de Algodão
│   │   ├── lote_mp.py        # Lote de matéria-prima
│   │   └── fardinho.py       # Fardo individual de pluma
│   ├── metrics/              # Coleta de métricas
│   │   └── collector.py
│   └── models/               # Amostras reais extraídas do PostgreSQL
│       ├── entidades.json    (1 entidade)
│       ├── fazendas.json     (3 fazendas)
│       ├── setores.json      (todos os setores)
│       ├── talhoes.json      (500 talhões)
│       ├── armazens.json     (202 armazéns)
│       ├── lotes_mp.json     (5.000 lotes)
│       └── fardinhos.json    (10.000 fardinhos)
│
├── coordinator/              # Árbitro da camada externa (RAFT)
│   ├── main.py               # FastAPI + raftify
│   ├── fsm.py                # Máquina de estados: RAFT commit → submit_nym
│   ├── log_entry.py          # NymLogEntry (serializado pelo RAFT)
│   ├── supernodes.py         # Conexão com o Indy local
│   └── pending.py            # Fila de retry (consistência eventual)
│
├── packages/
│   └── cottontrust-core/     # Pacote compartilhado (indy-vdr + aries-askar)
│       └── cottontrust_core/
│           ├── ledger.py     # submit_nym, submit_nym_endorsed, submit_attrib
│           ├── wallet.py     # create_wallet, store_metadata
│           └── identity.py  # create_and_store_did, create_seed
│
└── monitoring/               # Stack de monitoramento
    ├── prometheus.yml
    └── provisioning/
```

---

## Pré-requisitos

- Docker >= 28.0 e Docker Compose v2
- Docker Swarm inicializado (`docker swarm init`)
- VON Network rodando (local ou remoto)

### Subindo o VON Network localmente

```bash
git clone https://github.com/bcgov/von-network
cd von-network
./manage build
./manage start --logs
```

O genesis ficará disponível em `http://localhost:9000/genesis`.

---

## Início rápido

### Smoke test local (modo direto, sem Swarm)

```bash
# 1. Configure o ambiente
cp .env.example .env
# Edite GENESIS_URL=http://host.docker.internal:9000/genesis

# 2. Build da imagem do client
docker build -t cottontrust-client:local -f client/dockerfile .

# 3. Execute
docker run --rm \
  --add-host host.docker.internal:host-gateway \
  --env-file .env \
  -v "$(pwd)/output:/app/output" \
  cottontrust-client:local
```

### Experimento no cluster (modo COTTON-NET)

```bash
# 1. Inicializa Swarm + registry (uma vez só)
make swarm-init
make registry-start

# 2. Inicia supernodos e faz o deploy
make experiment NODES=32   # von-start + deploy coordinators + monitoring

# 3. Dispara o experimento
export COORDINATOR_URL=http://coordinator-1:8000
export CONCURRENCY=10
make client-start

# 4. Acompanha
make logs-client
```

---

## Variáveis de ambiente principais

| Variável | Descrição | Padrão |
|---|---|---|
| `GENESIS_URL` | URL do genesis do VON Network | — |
| `TRUSTEE_SEED` | Seed do trustee | `000...Trustee1` |
| `TRUSTEE_DID` | DID do trustee | `V4SGRU86Z58d6TV7PBUe6f` |
| `WALLET_KEY` | Chave das wallets (aries-askar) | — |
| `MODELS_DIR` | Diretório dos JSON de amostras | `/app/models` |
| `CONCURRENCY` | Registros paralelos por nível | `1` |
| `COORDINATOR_URL` | URL do Coordinator RAFT (vazio = modo direto) | `""` |
| `METRICS_OUTPUT` | Caminho do CSV de saída | `/app/output/raw_tx_metrics.csv` |

---

## Dependências principais

| Biblioteca | Versão | Papel |
|---|---|---|
| `indy-vdr` | ≥ 0.3.4 | Transações NYM e ATTRIB no ledger Indy |
| `aries-askar` | ≥ 0.3.2 | Wallets digitais e chaves Ed25519 |
| `raftify` | — | Consenso RAFT entre coordinators |
| `base58` | ≥ 2.1.1 | Derivação de DID |
| `loguru` | ≥ 0.7.0 | Logging estruturado |
| `httpx` | ≥ 0.27.0 | Cliente HTTP (coordinator + wait_for_drain) |

---

## Referências

- Duarte, J. F. B. et al. **COTTONTRUST: Reliability and Traceability in
  Cotton Supply Chain Using Self-Sovereign Identity**.
  AINA 2024, Springer.

- Sohn Junior, G. et al. **COTTON-NET**.
  Trabalho técnico-científico, LabP2D — UDESC Joinville, 2026.

- Hyperledger Indy VDR: https://github.com/hyperledger/indy-vdr
- Aries Askar: https://github.com/hyperledger/aries-askar
- VON Network: https://github.com/bcgov/von-network
- raftify: https://github.com/lablup/raftify
