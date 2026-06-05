"""
Fila de consistência eventual do COTTON-NET.

Quando um commit RAFT é confirmado mas a submissão ao ledger Indy
local falha (ex: supernodo temporariamente indisponível), a transação
é enfileirada aqui para retry automático.

Isso garante que todos os supernodos eventualmente convergem para
o mesmo estado, mesmo que não simultaneamente — consistência eventual.

Importante: a fila é em memória. Em caso de queda do Coordinator,
as entradas pendentes são perdidas. O log do RAFT pode ser usado
para reconstrução (trabalho futuro).
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from loguru import logger

from log_entry import NymLogEntry


@dataclass
class PendingEntry:
    """
    Transação pendente de retry no ledger Indy local.

    Attributes:
        entry:          LogEntry original a ser re-submetido.
        attempts:       Número de tentativas já realizadas.
        last_tried:     Timestamp da última tentativa.
        error:          Último erro registrado.
        next_retry_sec: Segundos a aguardar após last_tried antes do próximo
                        retry (calculado com backoff exponencial).
    """
    entry:          NymLogEntry
    attempts:       int   = 0
    last_tried:     datetime = field(default_factory=datetime.now)
    error:          str   = ""
    next_retry_sec: float = 0.0


class PendingQueue:
    """
    Gerencia retries de transações que falharam no ledger Indy.

    O worker assíncrono tenta re-submeter periodicamente.
    Após MAX_ATTEMPTS, a transação é descartada com alerta.
    """

    MAX_ATTEMPTS    = 10
    RETRY_INTERVAL  = 30   # segundos entre tentativas
    BACKOFF_FACTOR  = 1.5  # aumenta intervalo a cada falha

    def __init__(self) -> None:
        self._queue: dict[str, PendingEntry] = {}
        self._lock  = asyncio.Lock()
        self._task: asyncio.Task | None = None

    async def enqueue(self, entry: NymLogEntry, error: str = "") -> None:
        """Adiciona uma transação à fila de retry."""
        async with self._lock:
            self._queue[entry.entity_id] = PendingEntry(
                entry=entry, error=error
            )
        logger.warning(
            f"Transação enfileirada para retry | "
            f"entity_id={entry.entity_id} did={entry.did}"
        )

    async def remove(self, entity_id: str) -> None:
        """Remove uma transação da fila (após sucesso no retry)."""
        async with self._lock:
            self._queue.pop(entity_id, None)

    def start(self, submit_fn, on_discard=None) -> None:
        """
        Inicia o worker de retry em background.

        Args:
            submit_fn:  Coroutine async que recebe um NymLogEntry
                        e tenta submetê-lo ao ledger Indy.
            on_discard: Callback síncrono chamado quando uma entrada
                        é descartada após esgotar MAX_ATTEMPTS.
                        Recebe o NymLogEntry descartado.
        """
        self._task = asyncio.create_task(self._worker(submit_fn, on_discard))

    async def _worker(self, submit_fn, on_discard=None) -> None:
        """Loop de retry com backoff exponencial."""
        while True:
            await asyncio.sleep(self.RETRY_INTERVAL)

            async with self._lock:
                pending = list(self._queue.values())

            now = datetime.now()
            for item in pending:
                # Verifica backoff: aguarda next_retry_sec após last_tried
                if item.attempts > 0:
                    due = item.last_tried + timedelta(seconds=item.next_retry_sec)
                    if now < due:
                        continue  # ainda dentro do intervalo de backoff

                try:
                    await submit_fn(item.entry)
                    await self.remove(item.entry.entity_id)
                    logger.info(
                        f"Retry bem-sucedido | "
                        f"entity_id={item.entry.entity_id} "
                        f"tentativa={item.attempts + 1}"
                    )
                except Exception as e:
                    item.attempts   += 1
                    item.last_tried  = datetime.now()
                    item.error       = str(e)
                    # Backoff exponencial com cap de 5 minutos
                    item.next_retry_sec = min(
                        self.RETRY_INTERVAL * (self.BACKOFF_FACTOR ** item.attempts),
                        300,
                    )

                    if item.attempts >= self.MAX_ATTEMPTS:
                        logger.error(
                            f"Retry esgotado — transação descartada | "
                            f"entity_id={item.entry.entity_id} "
                            f"erro={e}"
                        )
                        if on_discard:
                            on_discard(item.entry)
                        await self.remove(item.entry.entity_id)
                    else:
                        logger.warning(
                            f"Retry falhou | "
                            f"entity_id={item.entry.entity_id} "
                            f"tentativa={item.attempts}/{self.MAX_ATTEMPTS} "
                            f"próximo_retry={item.next_retry_sec:.0f}s "
                            f"erro={e}"
                        )

    async def snapshot_data(self) -> list[dict]:
        """Retorna os dados da fila com lock adquirido, para uso em snapshot RAFT."""
        async with self._lock:
            return [
                {
                    "entity_id":   p.entry.entity_id,
                    "entity_type": p.entry.entity_type,
                    "did":         p.entry.did,
                    "verkey":      p.entry.verkey,
                    "attempts":    p.attempts,
                }
                for p in self._queue.values()
            ]

    @property
    def size(self) -> int:
        """Número de transações pendentes."""
        return len(self._queue)

    def stop(self) -> None:
        """Cancela o worker de retry."""
        if self._task:
            self._task.cancel()