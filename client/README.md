# COTTONTRUST — Cliente

Módulo cliente do COTTONTRUST. Responsável por registrar entidades
da cadeia produtiva do algodão no ledger Hyperledger Indy usando
as bibliotecas modernas `indy-vdr` e `aries-askar`.

## Estrutura

```
client/
├── main.py              # Orquestrador — ponto de entrada
├── config.py            # Configuração via variáveis de ambiente
├── Dockerfile
├── requirements.txt
│
├── core/                # Primitivas blockchain (pool, wallet, DID)
├── entities/            # Entidades da cadeia (UBA, Bale...)
├── metrics/             # Coleta e exportação de métricas
└── models/              # Dados JSON de entrada (ubas.json, bales.json)
```

## Configuração

Copie `.env.example` para `.env` na raiz do projeto e preencha:

```bash
cp ../.env.example ../.env
```

Variáveis obrigatórias:
| Variável | Descrição |
|---|---|
| `GENESIS_URL` | URL do genesis do VON Network |
| `TRUSTEE_SEED` | Seed do trustee (padrão VON Network) |
| `TRUSTEE_DID` | DID do trustee já no ledger |
| `WALLET_KEY` | Chave de acesso às wallets |

## Execução local

```bash
# Instala dependências
pip install -r requirements.txt

# Executa
python main.py
```

## Execução via Docker

```bash
docker build -t cottontrust-client .
docker run --env-file ../.env cottontrust-client
```

## Dados de entrada

Os arquivos JSON devem estar em `models/`. O cliente suporta
tanto arrays JSON quanto JSON Lines (um objeto por linha):

```bash
models/
├── ubas.json    # Unidades de Beneficiamento de Algodão
└── bales.json   # Fardinhos de algodão
```

Estrutura esperada → ver `entities/README.md`.

## Saída

- **Métricas CSV**: `/app/output/raw_tx_metrics.csv`
- **Log estruturado**: stdout + `/app/output/cottontrust.log`

## Dependências de migração

| Antes (indy-sdk) | Agora |
|---|---|
| `indy.pool.*` | `indy-vdr` via `core/ledger.py` |
| `indy.wallet.*` | `aries-askar` via `core/wallet.py` |
| `indy.did.*` | `aries-askar` + `base58` via `core/identity.py` |
| `indy.ledger.*` | `indy-vdr` via `core/ledger.py` |