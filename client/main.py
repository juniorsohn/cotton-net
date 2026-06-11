"""
COTTONTRUST — Orquestrador principal do cliente.

Fluxo de registro com cadeia de endorsers (author+endorser SSI):

    Nivel 1: Entidades     — endossadas pelo trustee
    Nivel 2: Fazendas      — endossadas pelo trustee (id_entidade ausente nos dados)
    Nivel 3: Setores       — endossados pela sua Fazenda
    Nivel 4: Talhoes       — endossados pelo seu Setor
    Nivel 5: Armazens      — endossados pelo trustee
    Nivel 6: Lotes MP      — endossados pelo seu Armazem (id_armazem direto)
    Nivel 7: Fardinhos     — endossados pelo trustee (sem id_armazem nos dados)

O registro em ordem garante que o endorser ja existe no ledger
antes de assinar o filho. O registry mapeia entity_id real -> (wallet, did)
para lookup durante o registro dos filhos.
"""
import asyncio
import json
import sys
import urllib.parse
from asyncio import Semaphore
from pathlib import Path
from loguru import logger

from config import load_settings, Settings
from cottontrust_core.ledger import open_pool, submit_nym
from cottontrust_core.wallet import create_wallet
from cottontrust_core.identity import create_and_store_did
from entities.entidade import Entidade
from entities.fazenda import Fazenda
from entities.setor import Setor
from entities.talhao import Talhao
from entities.armazem import Armazem
from entities.lote_mp import LoteMP
from entities.fardinho import Fardinho
from metrics.collector import MetricsCollector
from coordinator import wait_for_drain


def setup_logging(level: str, log_file: str = "/app/output/cottontrust.log") -> None:
    """Configura o loguru com formato estruturado e colorido."""
    logger.remove()
    logger.add(
        sys.stdout,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
        colorize=True,
    )
    logger.add(
        log_file,
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} — {message}",
    )


def load_json(path: Path) -> list[dict]:
    if not path.exists():
        logger.warning(f"Arquivo nao encontrado: {path}")
        return []
    content = path.read_text(encoding="utf-8").strip()
    if not content or content == "null":
        return []
    parsed = json.loads(content)
    return parsed if isinstance(parsed, list) else []


async def init_trustee(settings: Settings, pool):
    store = await create_wallet("wallet_trustee", settings.wallet_key)
    did, verkey = await create_and_store_did(store, seed=settings.trustee_seed)
    if did != settings.trustee_did:
        logger.warning(f"DID derivado ({did}) difere do TRUSTEE_DID configurado.")
    try:
        _, tx_size = await submit_nym(
            pool=pool,
            store=store,
            submitter_did=did,
            target_did=did,
            verkey=verkey,
            role="TRUSTEE",
        )
        logger.info(f"Trustee registrado no ledger | did={did} size={tx_size}B")
    except RuntimeError as e:
        logger.debug(f"Trustee ja registrado: {e}")
    logger.info(f"Trustee pronto | did={did}")
    return store, did


async def register_all(entities, klass, wallet_key, pool, trustee_store, trustee_did,
                       metrics, coordinator_url, endorser_registry: dict,
                       parent_id_field: str | None = None,
                       concurrency: int = 1) -> dict:
    """
    Registra uma lista de entidades e devolve um registry {entity_id: (wallet, did)}.

    Se parent_id_field for fornecido, busca o endorser no endorser_registry
    usando data[parent_id_field] como chave. Se nao encontrar, usa trustee.
    Concurrency controla quantas entidades sao registradas em paralelo dentro do nivel.
    """
    registry = {}
    sem = Semaphore(concurrency)

    async def _one(i: int, data: dict) -> None:
        obj = klass.from_json(data, wallet_key, counter=i)

        endorser_store, endorser_did_val = None, ""
        if parent_id_field:
            parent_id = str(data.get(parent_id_field) or "")
            if parent_id in endorser_registry:
                endorser_store, endorser_did_val = endorser_registry[parent_id]
            else:
                logger.debug(
                    f"Endorser nao encontrado para {parent_id_field}={parent_id} "
                    f"— usando trustee como fallback"
                )

        async with sem:
            wallet, did = await obj.register(
                pool=pool,
                trustee_store=trustee_store,
                trustee_did=trustee_did,
                metrics=metrics,
                coordinator_url=coordinator_url,
                endorser_store=endorser_store,
                endorser_did=endorser_did_val,
            )
        registry[obj.entity_id] = (wallet, did)

    await asyncio.gather(*[_one(i, d) for i, d in enumerate(entities, start=1)])
    return registry


async def run() -> None:
    settings = load_settings()
    log_file = str(Path(settings.metrics_output).parent / "cottontrust.log")
    setup_logging(settings.log_level, log_file)

    logger.info("=" * 60)
    logger.info("COTTONTRUST iniciando")
    logger.info(f"Pool:    {settings.genesis_url}")
    logger.info(f"Modelos: {settings.models_dir}")

    if settings.coordinator_url:
        logger.info(f"Modo:    COORDINATOR — {settings.coordinator_url}")
        pool = trustee_store = None
        trustee_did = ""
    else:
        logger.info("Modo:    DIRETO (Indy ledger)")
        pool = await open_pool(settings.genesis_url)
        trustee_store, trustee_did = await init_trustee(settings, pool)

    logger.info("=" * 60)

    pool_name = urllib.parse.urlparse(settings.genesis_url).hostname or "sandbox"
    metrics = MetricsCollector(pool_name=pool_name, output_path=settings.metrics_output)
    models = Path(settings.models_dir)
    wk = settings.wallet_key

    common = dict(pool=pool, trustee_store=trustee_store, trustee_did=trustee_did,
                  metrics=metrics, coordinator_url=settings.coordinator_url,
                  concurrency=settings.concurrency)

    # Nivel 1 — Entidades (endorser: trustee)
    entidades_data = load_json(models / "entidades.json")
    logger.info(f"Registrando {len(entidades_data)} Entidade(s)...")
    entidade_reg = await register_all(entidades_data, Entidade, wk, **common,
                                      endorser_registry={}, parent_id_field=None)

    # Nivel 2 — Fazendas (endorser: trustee — id_entidade ausente nos dados)
    fazendas_data = load_json(models / "fazendas.json")
    logger.info(f"Registrando {len(fazendas_data)} Fazenda(s)...")
    fazenda_reg = await register_all(fazendas_data, Fazenda, wk, **common,
                                     endorser_registry={}, parent_id_field=None)

    # Nivel 3 — Setores (endorser: Fazenda via id_fazenda)
    setores_data = load_json(models / "setores.json")
    logger.info(f"Registrando {len(setores_data)} Setor(es)...")
    setor_reg = await register_all(setores_data, Setor, wk, **common,
                                   endorser_registry=fazenda_reg,
                                   parent_id_field="id_fazenda")

    # Nivel 4 — Talhoes (endorser: Setor via id_setor)
    talhoes_data = load_json(models / "talhoes.json")
    logger.info(f"Registrando {len(talhoes_data)} Talhao(es)...")
    talhao_reg = await register_all(talhoes_data, Talhao, wk, **common,
                                    endorser_registry=setor_reg,
                                    parent_id_field="id_setor")

    # Nivel 5 — Armazens (endorser: trustee)
    armazens_data = load_json(models / "armazens.json")
    logger.info(f"Registrando {len(armazens_data)} Armazem(ns)...")
    armazem_reg = await register_all(armazens_data, Armazem, wk, **common,
                                     endorser_registry={}, parent_id_field=None)

    # Nivel 6 — Lotes MP (endorser: Armazem via id_armazem)
    lotes_data = load_json(models / "lotes_mp.json")
    logger.info(f"Registrando {len(lotes_data)} Lote(s) MP...")
    await register_all(lotes_data, LoteMP, wk, **common,
                       endorser_registry=armazem_reg,
                       parent_id_field="id_armazem")

    # Nivel 7 — Fardinhos (endorser: trustee — sem id_armazem nos dados)
    fardinhos_data = load_json(models / "fardinhos.json")
    logger.info(f"Registrando {len(fardinhos_data)} Fardinho(s)...")
    await register_all(fardinhos_data, Fardinho, wk, **common,
                       endorser_registry={}, parent_id_field=None)

    # No modo coordinator, aguarda a fila FSM esvaziar antes de encerrar,
    # garantindo que o tempo total inclui a escrita efetiva em todos os supernodos.
    if settings.coordinator_url:
        await wait_for_drain(settings.coordinator_url)

    metrics.save()
    summary = metrics.summary

    logger.info("=" * 60)
    logger.info("COTTONTRUST concluido")
    logger.info(f"Transacoes:  {summary.get('total_transactions', 0)}")
    logger.info(f"Tempo total: {summary.get('total_time_sec', 0)}s")
    logger.info(f"Media/tx:    {summary.get('avg_time_sec', 0)}s")
    logger.info(f"Min/tx:      {summary.get('min_time_sec', 0)}s")
    logger.info(f"Max/tx:      {summary.get('max_time_sec', 0)}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(run())
