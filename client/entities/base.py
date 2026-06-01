"""
COTTON-CELL: unidade atômica do COTTONTRUST.

Toda entidade participante da cadeia produtiva do algodão —
fazendas, usinas, traders, fardinhos — é representada como
um CottonCell. Cada célula é identificada por um DID único
registrado imutavelmente no ledger Indy, e possui uma wallet
digital onde sua chave privada e metadados são armazenados.

Fluxo de registro (REG_ENTITY):
    1. Criação da wallet digital (aries-askar)
    2. Geração do par DID/verkey (Ed25519)
    3. Submissão do NYM ao ledger (indy-vdr), endossado pelo trustee
    4. Armazenamento dos metadados específicos na wallet
    5. Coleta de métricas (tempo e tamanho do payload)

Referência arquitetural:
    Duarte et al. (2024) — COTTONTRUST, Figura 3.1
    Sohn Junior (2025)  — COTTON-NET, Seção 3.3
"""
import time
from dataclasses import dataclass, field
from loguru import logger

from cottontrust_core.wallet import create_wallet, store_metadata
from cottontrust_core.identity import create_and_store_did
from cottontrust_core.ledger import submit_nym
from metrics.collector import MetricsCollector


@dataclass
class CottonCell:
    """
    Representa uma entidade participante da rede COTTONTRUST.

    Esta é a classe base. Entidades concretas (UBA, Bale, etc.)
    herdam dela e adicionam seus atributos específicos via `metadata`.

    Attributes:
        entity_id:   Identificador único da entidade (do sistema de origem).
        entity_type: Tipo da entidade ('uba', 'bale', 'client', etc.).
        wallet_key:  Chave de acesso à wallet (aries-askar).
        metadata:    Atributos específicos da entidade (peso, local, etc.).
        did:         DID registrado no ledger (preenchido após setup).
        verkey:      Chave pública associada ao DID (preenchido após setup).
        wallet:      Conexão com a wallet digital (preenchido após setup).
    """
    entity_id:   str
    entity_type: str
    wallet_key:  str
    metadata:    dict = field(default_factory=dict)

    # Preenchidos durante o setup — não são parâmetros do construtor
    did:    str   = field(default="", init=False, repr=False)
    verkey: str   = field(default="", init=False, repr=False)
    wallet: object = field(default=None, init=False, repr=False)

    async def setup(
        self,
        pool,
        trustee_store,
        trustee_did: str,
        metrics: MetricsCollector,
        seed: str | None = None,
        coordinator_url: str | None = None,
    ) -> None:
        """
        Inicializa a entidade na rede COTTONTRUST.

        Deve ser chamado uma vez após a instanciação. Executa o
        fluxo completo de REG_ENTITY conforme o TCC.

        Suporta dois modos de operação:
            - Direto:      submit_nym() local via pool Indy (legado COTTONTRUST).
            - Coordinator: POST /register ao cluster RAFT (COTTON-NET).

        Args:
            pool:            Conexão com o pool Indy (None no modo coordinator).
            trustee_store:   Wallet do trustee (None no modo coordinator).
            trustee_did:     DID do trustee (vazio no modo coordinator).
            metrics:         Coletor de métricas de desempenho.
            seed:            Seed determinístico para geração do DID (opcional).
            coordinator_url: URL do Coordinator RAFT. Se fornecido, usa o modo
                             COTTON-NET em vez de submeter direto ao Indy.
        """
        start = time.monotonic()

        # 1. Cria wallet (sempre local — chave privada nunca sai da entidade)
        wallet_id = f"wallet_{self.entity_type}_{self.entity_id}"
        self.wallet = await create_wallet(wallet_id, self.wallet_key)

        # 2. Gera DID e verkey (sempre local — Ed25519 via aries-askar)
        self.did, self.verkey = await create_and_store_did(
            self.wallet, seed=seed
        )

        # 3. Registra no ledger — via Coordinator (RAFT) ou direto (Indy)
        if coordinator_url:
            from coordinator import register_entity
            await register_entity(
                coordinator_url=coordinator_url,
                entity_id=self.entity_id,
                entity_type=self.entity_type,
                did=self.did,
                verkey=self.verkey,
            )
            # tx_size indisponível no modo coordinator (NYM aplicado remotamente)
            tx_size = 0
        else:
            try:
                _, tx_size = await submit_nym(
                    pool=pool,
                    store=trustee_store,
                    submitter_did=trustee_did,
                    target_did=self.did,
                    verkey=self.verkey,
                )
            except RuntimeError as e:
                if "can not touch verkey" in str(e) or "UnauthorizedClientRequest" in str(e):
                    logger.debug(f"DID já registrado no ledger, ignorando | did={self.did}")
                    tx_size = 0
                else:
                    raise

        # 4. Armazena metadados na wallet
        if self.metadata:
            await store_metadata(self.wallet, self.entity_id, self.metadata)

        # 5. Registra métricas
        duration = time.monotonic() - start
        metrics.record(
            operation=f"create_{self.entity_type}",
            tx_time_sec=duration,
            tx_size_bytes=tx_size,
        )

        mode = "coordinator" if coordinator_url else "direto"
        logger.info(
            f"{self.entity_type.upper()} registrado [{mode}] | "
            f"id={self.entity_id} did={self.did} "
            f"tempo={duration:.3f}s"
            + (f" size={tx_size}B" if tx_size else "")
        )