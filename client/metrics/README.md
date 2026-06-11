# metrics — Coleta de métricas de desempenho

Registra e exporta métricas de cada transação blockchain com
decomposição de tempo por fase, permitindo separar o custo local
(wallet + DID) do custo de rede (ledger + RAFT).

## Uso

```python
from metrics.collector import MetricsCollector

metrics = MetricsCollector(pool_name="sandbox", output_path="/app/output/metrics.csv")

# Registra uma métrica
metrics.record(
    operation="create_fardinho",
    tx_time_sec=3.01,
    tx_size_bytes=412,
    mode="direto",           # "direto", "endorsed" ou "coordinator"
    setup_time_sec=0.05,     # wallet + DID (local)
    coordinator_time_sec=0.0,  # HTTP POST até resposta RAFT (zero no modo direto)
)

# Resumo
print(metrics.summary)
# {'pool': 'sandbox', 'total_transactions': 1, 'avg_time_sec': 3.01, ...}

# Salva CSV
metrics.save()
```

## Formato do CSV

```
pool,operation,mode,entity_num,tx_time_sec,setup_time_sec,coordinator_time_sec,tx_size_bytes,timestamp
sandbox,create_armazem,endorsed,1,0.312,0.048,0.000,856,2026-06-11T10:00:00.123456
sandbox,create_fardinho,direto,2,0.289,0.051,0.000,712,2026-06-11T10:00:00.435802
sandbox,create_lote_mp,coordinator,3,1.203,0.047,1.151,0,2026-06-11T10:00:01.639104
```

### Colunas

| Coluna | Descrição |
|---|---|
| `pool` | Hostname do genesis URL (identifica o supernodo) |
| `operation` | `create_<entity_type>` |
| `mode` | `direto`, `endorsed` ou `coordinator` |
| `entity_num` | Número de sequência global da transação |
| `tx_time_sec` | Tempo total E2E (cliente) |
| `setup_time_sec` | Fase local: criação da wallet + geração do DID |
| `coordinator_time_sec` | Fase de rede: HTTP POST até resposta RAFT (zero nos outros modos) |
| `tx_size_bytes` | Soma NYM + ATTRIB em bytes (zero no modo coordinator) |
| `timestamp` | ISO 8601 |

## Análise com pandas

```python
import pandas as pd

df = pd.read_csv("raw_tx_metrics.csv")

# Tempo médio por tipo de entidade e modo
print(df.groupby(["operation", "mode"])["tx_time_sec"].describe())

# Comparação direto vs coordinator
print(df.groupby("mode")[["tx_time_sec", "coordinator_time_sec"]].mean())

# Overhead do setup local
print(df["setup_time_sec"].describe())
```
