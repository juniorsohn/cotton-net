"""
Coletor de métricas de desempenho do COTTONTRUST.

No modo direto (CT) cada linha do CSV é UMA transação no ledger — entidades
fazem números diferentes de escritas (setor=3: nym_create+nym_role+attrib;
demais=2), então medir por-fluxo misturava unidades desiguais. O total por
entidade é reconstruível agrupando por entity_id. No modo coordinator (CN)
há uma linha por entidade (o timing por-escrita vive no FSM do coordinator).

Colunas do CSV:
    pool:                 Nome do pool/supernodo (hostname do genesis URL).
    operation:            nym_create | nym_role | attrib | setup_local
                          (ou create_<tipo> no modo coordinator).
    mode:                 "direto" | "endorsed" | "coordinator".
    entity_num:           Número de sequência global da linha (1, 2, 3...).
    entity_type:          Nível da entidade (setor, talhao, fardinho, ...).
    entity_id:            ID da entidade dona desta transação (para group-by).
    tx_time_sec:          Round-trip da transação (modo direto: só o submit,
                          sem os sleeps de retry).
    setup_time_sec:       Fase local: criação da wallet + geração do DID.
    coordinator_time_sec: Fase de rede+RAFT: HTTP POST até resposta do Coordinator.
    queue_wait_sec:       Espera na fila do FSM (modo coordinator).
    indy_time_sec:        Escrita efetiva no Indy do supernodo (modo coordinator).
    tx_size_bytes:        Tamanho do payload da transação em bytes.
    retries:              Retentativas read-after-write antes do sucesso.
    timestamp:            Data e hora ISO 8601 da transação.
"""
import csv
import re
from datetime import datetime
from pathlib import Path
from loguru import logger


def next_run_path(base: str | Path) -> Path:
    """
    Resolve o caminho final da run anexando o próximo sufixo `_runN` livre.

    A partir de uma base como `/app/output/ct_n64.csv`, varre o diretório
    procurando `ct_n64_run*.csv` e devolve `ct_n64_run{maior+1}.csv`. Assim
    cada execução do client gera um arquivo distinto (RUN_1, RUN_2, ...) sem
    sobrescrever as anteriores e sem precisar gerenciar variáveis de ambiente.
    """
    base = Path(base)
    stem, suffix = base.stem, (base.suffix or ".csv")
    base.parent.mkdir(parents=True, exist_ok=True)
    pat = re.compile(rf"^{re.escape(stem)}_run(\d+){re.escape(suffix)}$")
    used = [int(m.group(1)) for p in base.parent.glob(f"{stem}_run*{suffix}")
            if (m := pat.match(p.name))]
    n = (max(used) + 1) if used else 1
    return base.parent / f"{stem}_run{n}{suffix}"


class MetricsCollector:
    """
    Coleta e exporta métricas de transações blockchain.

    Attributes:
        pool_name:  Nome do pool associado a este coletor.
        output:     Caminho do arquivo CSV de saída.
        records:    Métricas coletadas em memória.
    """

    HEADERS = [
        "pool", "operation", "mode", "entity_num", "entity_type", "entity_id",
        "tx_time_sec", "setup_time_sec", "coordinator_time_sec",
        "queue_wait_sec", "indy_time_sec", "tx_size_bytes", "retries", "timestamp",
    ]

    def __init__(self, pool_name: str, output_path: str) -> None:
        self.pool_name = pool_name
        # Resolve para o próximo arquivo `_runN` livre — cada execução é
        # registrada separadamente (RUN_1, RUN_2, ...), sem clobber.
        self.output = next_run_path(output_path)
        self.records: list[dict] = []
        logger.info(f"Métricas desta run → {self.output}")

    def record(
        self,
        operation: str,
        tx_time_sec: float,
        tx_size_bytes: int,
        mode: str = "direct",
        setup_time_sec: float = 0.0,
        coordinator_time_sec: float = 0.0,
        entity_id: str = "",
        entity_type: str = "",
        queue_wait_sec: float = 0.0,
        indy_time_sec: float = 0.0,
        retries: int = 0,
    ) -> None:
        """
        Registra uma métrica em memória.

        No modo direto (CT) cada linha é UMA transação no ledger
        (operation = nym_create / nym_role / attrib / setup_local), o que
        permite analisar a latência por-transação — entidades fazem números
        diferentes de escritas (setor=3, demais=2). O total por entidade é
        reconstruível agrupando por entity_id.

        Args:
            operation:    Operação (nym_create, nym_role, attrib, setup_local,
                          ou create_<tipo> no modo coordinator).
            tx_time_sec:  Round-trip da transação (no modo direto, só o submit).
            tx_size_bytes:Tamanho do payload em bytes.
            mode:         "direto" | "endorsed" | "coordinator".
            entity_type:  Nível da entidade (setor, talhao, fardinho, ...).
            retries:      Tentativas de retry antes do sucesso (read-after-write).
        """
        entry = {
            "pool":                 self.pool_name,
            "operation":            operation,
            "mode":                 mode,
            "entity_num":           len(self.records) + 1,
            "entity_type":          entity_type,
            "entity_id":            entity_id,
            "tx_time_sec":          round(tx_time_sec, 6),
            "setup_time_sec":       round(setup_time_sec, 6),
            "coordinator_time_sec": round(coordinator_time_sec, 6),
            "queue_wait_sec":       round(queue_wait_sec, 6),
            "indy_time_sec":        round(indy_time_sec, 6),
            "tx_size_bytes":        tx_size_bytes,
            "retries":              retries,
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