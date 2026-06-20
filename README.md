# COTTONTRUST / COTTON-NET

Arquitetura descentralizada para rastreabilidade, confiabilidade e
auditabilidade na cadeia produtiva do algodão, baseada em
Self-Sovereign Identity (SSI) e Hyperledger Indy.

Desenvolvida no Laboratório de Processamento Paralelo e Distribuído
(LabP2D) — UDESC Joinville.

> **Experimentos:** COTTONTRUST distribuído (`ct-*`) como baseline e
> COTTON-NET distribuído (`cn-*`) como contribuição principal.
> Ver [USAGE.md](USAGE.md) para o guia operacional completo.

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
                │  Kn nós Indy   │   │  Kn nós Indy     │
                │  distribuídos  │   │  distribuídos    │
                │  RBFT           │   │  RBFT             │
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

### Distribuição dos nós Indy

Cada supernodo possui `Kn = NODES / Sn` nós Indy com genesis independente,
distribuídos igualmente pelas 4 baias físicas. Para `Kn=8, Sn=4`:

```
flores       corisco      baiacu       pernambuco
S1n1,S2n1    S1n2,S2n2    S1n3,S2n3    S1n4,S2n4
S3n1,S4n1    S3n2,S4n2    S3n3,S4n3    S3n4,S4n4
```

Cada supernodo gera seu genesis independentemente (sem compartilhamento entre
pools). Conflitos de porta são evitados por `PORT_OFFSET = (s-1) × Kn × 2`.

### Cadeia de endorsers SSI

```
trustee
├── Entidade  ←── trustee endossa
├── Fazenda   ←── trustee endossa  (*)
│     └── Setor   ←── Fazenda endossa
│           └── Talhão  ←── Setor endossa
└── Armazém   ←── trustee endossa
      ├── Lote MP   ←── Armazém endossa
      └── Fardinho  ←── Armazém endossa
```

(*) Fazenda é endossada pelo trustee pois tem personalidade jurídica independente.

---

## Modos de experimento

| Modo | Stack | Comando | Descrição |
|---|---|---|---|
| COTTONTRUST Distribuído | `ct` | `make ct-config ct-deploy` | Baseline: Indy RBFT flat, N nós distribuídos em 4 baias |
| COTTON-NET Distribuído | `cn` | `make cn-config cn-deploy` | Principal: Sn supernodos × Kn nós + RAFT entre supernodos |
| COTTON-NET Local | `cottontrust` | `make deploy` | Legacy: VON Networks locais por baia |

---

## Estrutura do repositório

```
cottonnet/
├── .env.example              # Variáveis de ambiente (copie para .env)
├── docker-compose.yml        # Stack COTTON-NET local (legacy)
├── Makefile                  # Workflow de todos os modos de experimento
├── README.md                 # Este arquivo
├── USAGE.md                  # Guia operacional detalhado
│
├── scripts/
│   ├── swarm_init.sh                 # Inicializa Docker Swarm
│   ├── start_von.sh                  # Configura VON no NFS (modo local)
│   ├── stop_von.sh                   # Para VON Networks
│   ├── patch_von_image.sh            # Patch indy-plenum: limite 100 → 10000 nós
│   ├── gen_cottontrust_stack.sh      # Gera docker-stack-cottontrust.yml
│   └── gen_cottonnet_stack.sh        # Gera docker-stack-cottonnet.yml
│
├── client/                   # Cottonclient — aplicação Python
│   ├── main.py               # Orquestrador (7 níveis, concorrência por nível)
│   ├── config.py             # Configuração via .env
│   ├── coordinator.py        # Cliente HTTP do Coordinator
│   ├── dockerfile
│   ├── requirements.txt
│   ├── entities/             # Modelo COTTON-CELL
│   │   ├── base.py           # CottonCell — setup NYM + ATTRIB + endorser
│   │   ├── entidade.py       # Empresa/cooperativa produtora
│   │   ├── fazenda.py        # Propriedade rural
│   │   ├── setor.py          # Subdivisão da fazenda
│   │   ├── talhao.py         # Parcela agrícola
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

Arquivos gerados pelo Makefile (não commitados):

```
docker-stack-cottontrust.yml   # gerado por: make ct-config NODES=N
docker-stack-cottonnet.yml     # gerado por: make cn-config NODES=N SUPERNODOS=S
```

---

## Topologia do cluster

| Hostname | IP | Função |
|---|---|---|
| flores | 10.10.20.151 | Worker Swarm — nós Indy baia 1 |
| corisco | 10.10.20.152 | Worker Swarm — nós Indy baia 2 |
| baiacu | 10.10.20.153 | Worker Swarm — nós Indy baia 3 |
| pernambuco | 10.10.20.154 | Worker Swarm — nós Indy baia 4 |
| cacao | 10.10.20.155 | Manager Swarm — cliente, monitoramento |

NFS compartilhado em todas as baias:
`/mnt/prj/g11718038933/cotton-net_2026/von-network`

---

## Início rápido

### Setup único (uma vez por cluster)

```bash
make swarm-init        # inicializa o Swarm
make registry-start    # registry local em flores:5000
make push              # build + push das imagens
```

### Experimento COTTONTRUST Distribuído (baseline)

```bash
make ct-config NODES=16      # gera docker-stack-cottontrust.yml
make ct-deploy               # sobe N nós Indy em 4 baias
make ct-client-start         # inicia o experimento
make ct-logs-client          # acompanha
make ct-stop                 # teardown completo
```

### Experimento COTTON-NET Distribuído (principal)

```bash
# Pré-requisito: von-network-base disponível e patcheada em cada baia
make cn-config NODES=16 SUPERNODOS=4   # gera docker-stack-cottonnet.yml
make cn-deploy                          # sobe Sn supernodos + coordinators
make cn-client-start                    # inicia o experimento
make cn-logs-client                     # acompanha
make cn-stop                            # teardown completo
```

`NODES` é o total de nós Indy; `Kn = NODES / SUPERNODOS`.
Mínimo: `Kn = 4` (quórum RBFT). Sugerido: `NODES = 16, 32, 64`.

---

## Patch do limite de nós Indy Plenum

O Hyperledger Indy Plenum possui um limite artificial de 100 nós em
`plenum/common/test_network_setup.py`. Esse limite é um placeholder de
governança, não uma restrição do protocolo RBFT.

```bash
# Em cada baia, após ./manage build:
make von-patch
```

O patch substitui `if n > 100:` por `if n > 10000:` dentro da imagem
`von-network-base` e é idempotente. Para `Kn ≤ 100`, o patch é inócuo.

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

- Sohn Junior, G. et al. **COTTON-NET: Scalable SSI Ledger with
  Hierarchical Supernode Consensus**.
  CloudCom 2026 (submetido).

- Hyperledger Indy VDR: https://github.com/hyperledger/indy-vdr
- Aries Askar: https://github.com/hyperledger/aries-askar
- VON Network: https://github.com/bcgov/von-network
- raftify: https://github.com/lablup/raftify
