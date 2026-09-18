"""
Cliente do daemon de consenso HotStuff (cottonhs).

O cottonhs roda como processo irmão DENTRO do mesmo container do coordinator:
o par (Python, Go) é a unidade que o Swarm agenda numa máquina. A conversa é
por HTTP em 127.0.0.1 — de propósito. Assim o commit aplicado no ledger Indy é
sempre o da MESMA réplica que participou da ordenação, sem depender de VIP de
serviço nem de um salto a mais na overlay.

Dois sentidos, ambos com os bytes de NymLogEntry.encode():

    Python → Go   propose(): POST /propose. Retorna quando f+1 réplicas
                  EXECUTARAM o comando — ou seja, ao menos uma honesta comitou.
    Go → Python   o daemon entrega cada commit, em ordem, no POST /apply do
                  próprio FastAPI (ver main.py), que chama fsm.apply().

Ocupa o lugar do raftify: mesma fronteira de bytes, ordenação bizantina no
lugar da tolerante-a-falhas-por-queda. Como no raftify, o retorno do propose
significa ORDENADO, não durável — a escrita no Indy é assíncrona (fsm.apply
enfileira e o drain_queue aplica).
"""
import asyncio

import httpx
from loguru import logger


class HotStuffError(RuntimeError):
    """Falha ao falar com o daemon de consenso local."""


class HotStuffClient:
    """Fala com o cottonhs local. Uma instância por coordinator."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def wait_ready(self, timeout: float = 300.0) -> dict:
        """
        Espera o daemon responder /status.

        O cottonhs só sobe o HTTP depois de conectar nos peers (Gorums abre os
        streams no Connect), então responder /status já significa que o cluster
        de consenso está formado — é o equivalente ao "líder eleito" do RAFT.
        """
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        tentativa = 0
        while True:
            try:
                r = await self._client.get(f"{self.base_url}/status", timeout=2.0)
                if r.status_code == 200:
                    st = r.json()
                    logger.info(f"HotStuff pronto | url={self.base_url} status={st}")
                    return st
            except httpx.HTTPError:
                pass
            decorrido = loop.time() - t0
            if decorrido > timeout:
                raise HotStuffError(
                    f"daemon não respondeu /status em {timeout}s | url={self.base_url}"
                )
            tentativa += 1
            if tentativa % 10 == 0:
                logger.warning(
                    f"Aguardando daemon HotStuff | url={self.base_url} "
                    f"decorrido={int(decorrido)}s"
                )
            await asyncio.sleep(1.0)

    async def propose(self, data: bytes) -> None:
        """
        Propõe bytes ao consenso. Bloqueia até f+1 réplicas executarem.

        Diferente do RAFT, não há redirecionamento para líder: o daemon manda o
        comando a TODAS as réplicas por quorum call, então qualquer coordinator
        pode receber o /register.
        """
        try:
            r = await self._client.post(f"{self.base_url}/propose", content=data)
        except httpx.HTTPError as e:
            raise HotStuffError(f"daemon inalcançável: {e}") from e
        if r.status_code != 200:
            raise HotStuffError(f"HTTP {r.status_code}: {r.text.strip()}")

    async def status(self) -> dict:
        """Estado do daemon: aplicados, hash acumulado, pendentes."""
        try:
            r = await self._client.get(f"{self.base_url}/status", timeout=2.0)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return {}

    async def aclose(self) -> None:
        await self._client.aclose()
