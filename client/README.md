# COTTONTRUST — Cliente

Módulo cliente do COTTON-NET. Registra as 7 entidades da cadeia
produtiva do algodão no ledger Hyperledger Indy com cadeia SSI
de endorsers e atributos públicos on-chain (ATTRIB).

## Estrutura

```
client/
├── main.py              # Orquestrador — 7 níveis, asyncio.gather por nível
├── config.py            # Configuração via variáveis de ambiente
├── coordinator.py       # Cliente HTTP do Coordinator (register, wait_for_drain)
├── dockerfile
├── requirements.txt
│
├── entities/            # Modelo COTTON-CELL (ver entities/README.md)
├── metrics/             # Coleta e exportação de métricas CSV
└── models/              # Amostras reais extraídas do PostgreSQL
    ├── entidades.json
    ├── fazendas.json
    ├── setores.json
    ├── talhoes.json
    ├── armazens.json
    ├── lotes_mp.json
    └── fardinhos.json
```

## Configuração

Copie `.env.example` para `.env` na raiz do projeto:

```bash
cp ../.env.example ../.env
```

| Variável | Obrigatória | Descrição |
|---|---|---|
| `GENESIS_URL` | ✓ | URL do genesis do VON Network |
| `TRUSTEE_SEED` | ✓ | Seed do trustee |
| `TRUSTEE_DID` | ✓ | DID do trustee já no ledger |
| `WALLET_KEY` | ✓ | Chave de acesso às wallets |
| `MODELS_DIR` | — | Diretório dos JSON (padrão: `/app/models`) |
| `CONCURRENCY` | — | Registros paralelos por nível (padrão: `1`) |
| `COORDINATOR_URL` | — | Vazio = modo direto; URL = modo COTTON-NET |

## Execução via Docker

O contexto de build é a **raiz do repositório**:

```bash
# A partir da raiz do projeto (cottonnet/)
docker build -t cottontrust-client:local -f client/dockerfile .

docker run --rm \
  --add-host host.docker.internal:host-gateway \
  --env-file .env \
  -v "$(pwd)/output:/app/output" \
  cottontrust-client:local
```

## Dados de entrada

Os 7 arquivos JSON estão embutidos na imagem em `/app/models`
(copiados de `client/models/` no build). São amostras reais
extraídas do PostgreSQL de produção:

| Arquivo | Entidade | Quantidade |
|---|---|---|
| `entidades.json` | Empresa/cooperativa | 1 |
| `fazendas.json` | Propriedade rural | 3 |
| `setores.json` | Subdivisão da fazenda | todos |
| `talhoes.json` | Parcela agrícola | 500 |
| `armazens.json` | Unidade de beneficiamento | 202 |
| `lotes_mp.json` | Lote de matéria-prima | 5.000 |
| `fardinhos.json` | Fardo individual de pluma | 10.000 |

## Saída

- **Métricas CSV**: `/app/output/raw_tx_metrics.csv`
- **Log estruturado**: stdout + `/app/output/cottontrust.log`

O CSV inclui colunas de decomposição de tempo por fase:
`tx_time_sec`, `setup_time_sec`, `coordinator_time_sec`, `mode`.
Ver `metrics/README.md`.

## Modos de operação

| Modo | `COORDINATOR_URL` | Quem submete o NYM |
|---|---|---|
| Direto | vazio | Trustee local via `submit_nym()` |
| Endorsed | vazio | Entidade assina + pai countersigns via `submit_nym_endorsed()` |
| Coordinator | URL preenchida | Coordinator via RAFT → FSM → `submit_nym()` |
