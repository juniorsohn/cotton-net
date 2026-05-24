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
(usinas, fazendas, traders, fardinhos) é identificado por um DID único,
imutável e auditável, sem depender de nenhuma autoridade central.

O **COTTON-NET** estende o COTTONTRUST com uma hierarquia de supernodos,
reduzindo o impacto do algoritmo de consenso RBFT em redes de grande
escala.

---

## Arquitetura

```
                        ┌─────────────────────────┐
                        │     COTTONCLIENT         │
                        │  (aplicação Python)      │
                        └────────────┬─────────────┘
                                     │ HTTP
                        ┌────────────▼─────────────┐
                        │      COORDINATOR          │
                        │  (árbitro COTTON-NET)     │
                        │  RAFT + prepare/commit    │
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
| Externa | Entre supernodos | RAFT (Coordinator) | Eleição de líder e quórum de commit |

### Fluxo de uma transação (REG_ENTITY)

```
1. Cliente envia DID ao Coordinator
2. Coordinator verifica disponibilidade de todos os Sn (prepare)
3. Coordinator submete ao líder S1 → RBFT interno → confirmado
4. Coordinator replica para S2...Sn → RBFT interno → confirmados
5. Coordinator avalia quórum → responde ao cliente
6. Falhas parciais → fila de consistência eventual (retry)
```

---

## Estrutura do repositório

```
cottontrust/
├── .env.example              # Variáveis de ambiente (copie para .env)
├── docker-compose.yml        # Stack completo (Swarm)
├── README.md                 # Este arquivo
│
├── client/                   # Cottonclient — aplicação Python
│   ├── README.md
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py               # Orquestrador
│   ├── config.py             # Configuração via .env
│   ├── core/                 # Primitivas blockchain
│   │   ├── wallet.py         # aries-askar
│   │   ├── identity.py       # DID Ed25519
│   │   └── ledger.py         # indy-vdr
│   ├── entities/             # Modelo COTTON-CELL
│   │   ├── base.py           # CottonCell (classe base)
│   │   ├── uba.py            # Unidade de Beneficiamento de Algodão
│   │   └── bale.py           # Fardinho de algodão
│   ├── metrics/              # Coleta de métricas
│   │   └── collector.py
│   └── models/               # Dados JSON de entrada
│       ├── ubas.json
│       └── bales.json
│
├── coordinator/              # Árbitro da camada externa (próxima etapa)
│   ├── README.md
│   ├── Dockerfile
│   ├── main.py               # FastAPI app
│   ├── raft.py               # Eleição de líder
│   ├── consensus.py          # Prepare / commit / retry
│   └── supernodes.py         # Registry dos supernodos
│
└── monitoring/               # Stack de monitoramento
    ├── prometheus.yml
    └── grafana/
        └── dashboards/
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

```bash
# 1. Configure o ambiente
cp .env.example .env

# 2. Inicializa Swarm + registry (uma vez só)
make swarm-init
make registry-start

# 3. Inicia os supernodos Indy e faz o deploy
make experiment NODES=32   # von-start + deploy

# 4. Acompanha a execução
make logs-client
```

Para o fluxo completo de experimento, distribuição entre máquinas,
monitoramento e solução de problemas, consulte o **[Guia de Utilização](USAGE.md)**.

---

## Dependências principais

| Biblioteca | Versão | Substitui |
|---|---|---|
| `indy-vdr` | ≥ 0.3.4 | `indy.pool` + `indy.ledger` |
| `aries-askar` | ≥ 0.3.2 | `indy.wallet` + `indy.did` |
| `base58` | ≥ 2.1.1 | derivação de DID (interno ao indy-sdk) |
| `loguru` | ≥ 0.7.0 | logging estruturado |
| `python-dotenv` | ≥ 1.0.0 | carregamento do `.env` |

---

## Referências

- Duarte, J. F. B. et al. **COTTONTRUST: Reliability and Traceability in
  Cotton Supply Chain Using Self-Sovereign Identity**.
  AINA 2024, Springer.

- Sohn Junior, G. et al. **COTTON-NET: Distribuindo e Escalando**.
  TCC, UDESC Joinville, 2025.

- Hyperledger Indy VDR: https://github.com/hyperledger/indy-vdr
- Aries Askar: https://github.com/hyperledger/aries-askar
- VON Network: https://github.com/bcgov/von-network