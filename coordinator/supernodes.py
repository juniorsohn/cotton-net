"""
Registry de supernodos Indy do COTTON-NET.

Cada instância do Coordinator gerencia a conexão com o supernodo
Indy local (o VON Network rodando na mesma máquina). O registry
mantém o pool aberto e monitora a disponibilidade do supernodo.

No modelo COTTON-NET:
    - Cada máquina física roda um Coordinator + um Supernodo Indy
    - O Coordinator conhece apenas seu supernodo local
    - A coordenação entre supernodos é feita pelo RAFT (raftify)

Configuração via variáveis de ambiente:
    GENESIS_URL:   URL do genesis do supernodo local
    NODE_ID:       Identificador deste nó no cluster RAFT
"""
import asyncio
from dataclasses import dataclass, field
from loguru import logger

from cottontrust_core.ledger import open_pool


@dataclass
class SupernodeInfo:
    """
    Informações e conexão com o supernodo Indy local.

    Attributes:
        node_id:     Identificador único deste nó no cluster.
        genesis_url: URL ou caminho do genesis do supernodo Indy.
        pool:        Conexão ativa com o pool Indy (preenchida em setup).
        alive:       Se o supernodo está respondendo (atualizado pelo heartbeat).
    """
    node_id:     str
    genesis_url: str
    pool:        object = field(default=None, repr=False)
    alive:       bool   = False

    async def connect(self) -> None:
        """Abre conexão com o pool Indy local."""
        try:
            self.pool = await open_pool(self.genesis_url)
            self.alive = True
            logger.info(f"Supernodo conectado | node={self.node_id}")
        except Exception as e:
            self.alive = False
            logger.error(f"Falha ao conectar supernodo | node={self.node_id} erro={e}")
            raise

    async def healthcheck(self) -> bool:
        """
        Verifica se o supernodo Indy está respondendo.

        O indy-vdr não expõe pool.get_status(). O healthcheck é feito
        buscando a transação genesis (seqNo=1) do DOMAIN ledger — uma
        operação de leitura leve que confirma que o pool está acessível.

        Atualiza self.alive e retorna o status.
        """
        if not self.pool:
            self.alive = False
            return False
        try:
            import indy_vdr
            request = indy_vdr.ledger.build_get_txn_request(
                submitter_did=None,
                ledger_type=1,   # DOMAIN ledger
                seq_no=1,
            )
            response = await self.pool.submit_request(request)
            self.alive = response.get("op") != "REQNACK"
        except Exception:
            self.alive = False
        return self.alive


class SupernodeRegistry:
    """
    Gerencia o supernodo Indy local deste Coordinator.

    Responsável por manter a conexão ativa e executar
    healthchecks periódicos conforme configurado.
    """

    def __init__(self, node_id: str, genesis_url: str) -> None:
        self.local = SupernodeInfo(
            node_id=node_id,
            genesis_url=genesis_url,
        )
        self._healthcheck_task: asyncio.Task | None = None

    async def setup(self) -> None:
        """Conecta ao supernodo local e inicia healthcheck periódico."""
        await self.local.connect()
        self._healthcheck_task = asyncio.create_task(
            self._healthcheck_loop()
        )

    async def _healthcheck_loop(
        self,
        interval_sec: int = 30,
    ) -> None:
        """Verifica disponibilidade do supernodo a cada N segundos."""
        while True:
            await asyncio.sleep(interval_sec)
            alive = await self.local.healthcheck()
            if not alive:
                logger.warning(
                    f"Supernodo não responde | node={self.local.node_id}"
                )

    async def teardown(self) -> None:
        """Cancela healthcheck e fecha conexão com o pool."""
        if self._healthcheck_task:
            self._healthcheck_task.cancel()
        logger.info(f"Registry encerrado | node={self.local.node_id}")