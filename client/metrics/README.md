# metrics — Coleta de métricas de desempenho

Registra e exporta métricas de cada transação blockchain,
compatíveis com o formato dos experimentos do TCC.

## Uso

```python
from metrics.collector import MetricsCollector

metrics = MetricsCollector(pool_name="sandbox", output_path="/app/output/metrics.csv")

# Registra uma métrica
metrics.record(operation="create_uba", tx_time_sec=3.01, tx_size_bytes=412)

# Exibe resumo
print(metrics.summary)
# {'pool': 'sandbox', 'total_transactions': 1, 'avg_time_sec': 3.01, ...}

# Salva CSV
metrics.save()
```

## Formato do CSV

```
pool,operation,tx_time_sec,tx_size_bytes,timestamp
sandbox,create_uba,3.012345,412,2025-06-01T10:00:00.123456
sandbox,create_bale,3.008123,398,2025-06-01T10:00:03.135802
```

## Análise com pandas

```python
import pandas as pd

df = pd.read_csv("raw_tx_metrics.csv")
print(df.groupby("operation")["tx_time_sec"].describe())
```

## Extensão para múltiplos pools

Para o COTTON-NET com múltiplos supernodos, instancie um
`MetricsCollector` por pool e combine os CSVs na análise:

```python
metrics_s1 = MetricsCollector("supernodo_1", "/app/output/s1.csv")
metrics_s2 = MetricsCollector("supernodo_2", "/app/output/s2.csv")
```