"""
Coletor de métricas de desempenho do COTTONTRUST.

Registra em memória as métricas de cada transação blockchain
(tempo de execução, tamanho do payload, operação) e as exporta
para CSV ao final da execução.

O formato do CSV é compatível com o utilizado nos experimentos
do TCC (raw_tx_metrics.csv), permitindo análise direta com
as ferramentas existentes (Grafana, R, Python/pandas).

Colunas do CSV:
    pool:          Nome do pool/supernodo.
    operation:     Tipo da operação (create_uba, create_bale, etc.).
    tx_time_sec:   Tempo total da transação em segundos.
    tx_size_bytes: Tamanho do payload NYM em bytes.
    timestamp:     Data e hora da transação (ISO 8601).
"""
import csv
from datetime import datetime
from pathlib import Path
from loguru import logger


class MetricsCollector:
    """
    Coleta e exporta métricas de transações blockchain.

    Attributes:
        pool_name:  Nome do pool associado a este coletor.
        output:     Caminho do arquivo CSV de saída.
        records:    Métricas coletadas em memória.
    """

    HEADERS = ["pool", "operation", "tx_time_sec", "tx_size_bytes", "timestamp"]

    def __init__(self, pool_name: str, output_path: str) -> None:
        self.pool_name = pool_name
        self.output = Path(output_path)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.records: list[dict] = []

    def record(
        self,
        operation: str,
        tx_time_sec: float,
        tx_size_bytes: int,
    ) -> None:
        """
        Registra uma métrica de transação em memória.

        Args:
            operation:     Nome da operação (ex: 'create_uba').
            tx_time_sec:   Duração total da transação em segundos.
            tx_size_bytes: Tamanho do payload NYM em bytes.
        """
        entry = {
            "pool":          self.pool_name,
            "operation":     operation,
            "tx_time_sec":   round(tx_time_sec, 6),
            "tx_size_bytes": tx_size_bytes,
            "timestamp":     datetime.now().isoformat(),
        }
        self.records.append(entry)
        logger.debug(
            f"Métrica | pool={self.pool_name} op={operation} "
            f"tempo={tx_time_sec:.3f}s size={tx_size_bytes}B"
        )

    def save(self) -> None:
        """
        Exporta todas as métricas coletadas para CSV.

        O arquivo é sobrescrito a cada chamada. Para acumular
        resultados de múltiplas execuções, use output_paths distintos.
        """
        if not self.records:
            logger.warning("Nenhuma métrica para salvar.")
            return

        with open(self.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.HEADERS)
            writer.writeheader()
            writer.writerows(self.records)

        logger.info(f"{len(self.records)} métricas salvas | arquivo={self.output}")

    @property
    def summary(self) -> dict:
        """
        Retorna um resumo estatístico das métricas coletadas.

        Returns:
            Dicionário com total, soma, média, mínimo e máximo
            dos tempos de transação. Retorna dict vazio se não
            houver registros.
        """
        if not self.records:
            return {}

        times = [r["tx_time_sec"] for r in self.records]
        return {
            "pool":               self.pool_name,
            "total_transactions": len(self.records),
            "total_time_sec":     round(sum(times), 3),
            "avg_time_sec":       round(sum(times) / len(times), 3),
            "min_time_sec":       round(min(times), 3),
            "max_time_sec":       round(max(times), 3),
        }