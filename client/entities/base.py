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
from cottontrust_core.ledger import submit_nym, submit_attrib
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
        endorser_store=None,
        endorser_did: str = "",
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
        t_start = time.monotonic()

        # 1. Cria wallet (sempre local — chave privada nunca sai da entidade)
        wallet_id = f"wallet_{self.entity_type}_{self.entity_id}"
        self.wallet = await create_wallet(wallet_id, self.wallet_key)

        # 2. Gera DID e verkey (sempre local — Ed25519 via aries-askar)
        self.did, self.verkey = await create_and_store_did(
            self.wallet, seed=seed
        )
        t_after_setup = time.monotonic()

        # 3. Registra no ledger — coordinator, endorser-submits, ou trustee direto
        #
        # Nota sobre endorsed transactions (Aries RFC 0028 / indy-vdr set_endorser):
        # O padrão dual-assinatura (author+endorser multi-sig) exigiria que o
        # RolesAuthorizer do indy-node encontrasse o sender (novo DID) no ledger
        # antes de verificar as assinaturas (authorizer.py, passo 2). Como o novo
        # DID ainda nao existe, o check falha — e nao ha como contornar isso via
        # off_ledger_signature porque auth_constraints.py restringe esse flag a
        # role='*' exclusivamente. O comportamento eh identico em indy-node 1.12.6
        # e 1.13.2 (codigo-fonte verificado). O endorsed transaction RFC 0028 foi
        # projetado para authors JA REGISTRADOS (ex.: publicar SCHEMA/CRED_DEF),
        # nao para registrar novos DIDs via NYM.
        #
        # Padrao adotado (endorser-submits):
        #   NYM: identifier=endorser_did -> prova quem autorizou o registro
        #   ATTRIB: identifier=self.did  -> prova que o filho controla a chave
        #   ATTRIB raw: endorser_did=endorser_did -> link explicito na cadeia
        # Ambas as transacoes ficam imutaveis no ledger, formando a cadeia SSI.
        tx_size = 0
        if coordinator_url:
            from coordinator import register_entity
            await register_entity(
                coordinator_url=coordinator_url,
                entity_id=self.entity_id,
                entity_type=self.entity_type,
                did=self.did,
                verkey=self.verkey,
            )
        elif endorser_store and endorser_did:
            # Passo A: endorser (pai) registra o filho como IDENTITY_OWNER.
            # auth_map: add_new_endorser exige STEWARD/TRUSTEE — um ENDORSER
            # nao pode conceder role=ENDORSER a outro DID. Por isso role=None aqui.
            try:
                _, tx_size = await submit_nym(
                    pool=pool,
                    store=endorser_store,
                    submitter_did=endorser_did,
                    target_did=self.did,
                    verkey=self.verkey,
                    role=None,
                )
            except RuntimeError as e:
                if "can not touch verkey" in str(e) or "UnauthorizedClientRequest" in str(e):
                    logger.debug(f"DID já registrado no ledger, ignorando | did={self.did}")
                else:
                    raise

            # Passo B: Trustee concede role=ENDORSER se a entidade precisa
            # endossar filhos (ex.: Setor endossa Talhões). Apenas STEWARD/TRUSTEE
            # podem fazer isso (auth_map: add_new_endorser / edit_role → ENDORSER).
            ledger_role = getattr(self, "_ledger_role", None)
            if ledger_role and trustee_store and trustee_did:
                try:
                    _, role_tx = await submit_nym(
                        pool=pool,
                        store=trustee_store,
                        submitter_did=trustee_did,
                        target_did=self.did,
                        verkey=self.verkey,
                        role=ledger_role,
                    )
                    tx_size += role_tx
                except RuntimeError as e:
                    if "can not touch verkey" in str(e):
                        logger.debug(f"Role já atribuído, ignorando | did={self.did}")
                    else:
                        raise
        else:
            try:
                _, tx_size = await submit_nym(
                    pool=pool,
                    store=trustee_store,
                    submitter_did=trustee_did,
                    target_did=self.did,
                    verkey=self.verkey,
                    role=getattr(self, "_ledger_role", None),
                )
            except RuntimeError as e:
                if "can not touch verkey" in str(e) or "UnauthorizedClientRequest" in str(e):
                    logger.debug(f"DID já registrado no ledger, ignorando | did={self.did}")
                else:
                    raise
        t_after_register = time.monotonic()

        # 4. Escreve atributos publicos no ledger (rastreabilidade)
        public_fields = getattr(self, "_public_fields", [])
        if public_fields and pool and not coordinator_url:
            public_meta = {k: v for k, v in self.metadata.items() if k in public_fields}
            if endorser_did:
                public_meta["endorser_did"] = endorser_did
            if public_meta:
                attrib_size = await submit_attrib(
                    pool=pool,
                    store=self.wallet,
                    submitter_did=self.did,
                    raw_attrs={self.entity_type: public_meta},
                )
                tx_size += attrib_size

        # 5. Armazena metadados na wallet
        if self.metadata:
            await store_metadata(self.wallet, self.entity_id, self.metadata)

        t_end = time.monotonic()

        # 6. Registra métricas com decomposição de fases
        setup_time       = t_after_setup - t_start
        coordinator_time = (t_after_register - t_after_setup) if coordinator_url else 0.0
        total_time       = t_end - t_start

        if coordinator_url:
            mode = "coordinator"
        elif endorser_store and endorser_did:
            mode = "endorsed"
        else:
            mode = "direto"

        metrics.record(
            operation=f"create_{self.entity_type}",
            tx_time_sec=total_time,
            tx_size_bytes=tx_size,
            mode=mode,
            setup_time_sec=setup_time,
            coordinator_time_sec=coordinator_time,
            entity_id=str(self.entity_id),
        )

        logger.info(
            f"{self.entity_type.upper()} registrado [{mode}] | "
            f"id={self.entity_id} did={self.did} "
            f"total={total_time:.3f}s setup={setup_time:.3f}s "
            + (f"coord={coordinator_time:.3f}s " if coordinator_url else "")
            + (f"size={tx_size}B" if tx_size else "")
        )
