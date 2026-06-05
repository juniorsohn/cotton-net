"""
Coletor de métricas de desempenho do COTTONTRUST.

Registra em memória as métricas de cada transação blockchain
e as exporta para CSV ao final da execução.

Colunas do CSV:
    pool:                 Nome do pool/supernodo (hostname do genesis URL).
    operation:            Tipo da operação (create_uba, create_bale, etc.).
    mode:                 Modo de operação ("coordinator" ou "direct").
    entity_num:           Número de sequência global da transação (1, 2, 3...).
    tx_time_sec:          Tempo total da transação (E2E do cliente).
    setup_time_sec:       Fase local: criação da wallet + geração do DID.
    coordinator_time_sec: Fase de rede+RAFT: HTTP POST até resposta do Coordinator.
                          Zero no modo "direct".
    tx_size_bytes:        Tamanho do payload NYM (zero no modo coordinator).
    timestamp:            Data e hora ISO 8601 da transação.
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

    HEADERS = [
        "pool", "operation", "mode", "entity_num",
        "tx_time_sec", "setup_time_sec", "coordinator_time_sec",
        "tx_size_bytes", "timestamp",
    ]

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
        mode: str = "direct",
        setup_time_sec: float = 0.0,
        coordinator_time_sec: float = 0.0,
    ) -> None:
        """
        Registra uma métrica de transação em memória.

        Args:
            operation:            Nome da operação (ex: 'create_uba').
            tx_time_sec:          Duração E2E da transação em segundos.
            tx_size_bytes:        Tamanho do payload NYM em bytes.
            mode:                 "coordinator" ou "direct".
            setup_time_sec:       Tempo das operações locais (wallet + DID).
            coordinator_time_sec: Tempo do POST HTTP ao Coordinator (RAFT).
        """
        entry = {
            "pool":                 self.pool_name,
            "operation":            operation,
            "mode":                 mode,
            "entity_num":           len(self.records) + 1,
            "tx_time_sec":          round(tx_time_sec, 6),
            "setup_time_sec":       round(setup_time_sec, 6),
            "coordinator_time_sec": round(coordinator_time_sec, 6),
            "tx_size_bytes":        tx_size_bytes,
            "timestamp":            datetime.now().isoformat(),
        }
        self.records.append(entry)
        logger.debug(
            f"Métrica | pool={self.pool_name} op={operation} mode={mode} "
            f"seq={entry['entity_num']} total={tx_time_sec:.3f}s "
            f"setup={setup_time_sec:.3f}s coord={coordinator_time_sec:.3f}s "
            f"size={tx_size_bytes}B"
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