"""
COTTONTRUST — Orquestrador principal do cliente.

Responsável por coordenar o fluxo completo de registro de entidades
na rede COTTONTRUST:

    1. Carrega configuração do ambiente (.env)
    2. Conecta ao pool Indy (via indy-vdr)
    3. Inicializa o trustee (endossador das transações)
    4. Registra UBAs no ledger
    5. Registra Bales no ledger
    6. Exporta métricas de desempenho para CSV

Arquitetura COTTON-CELL (Duarte et al., 2024):
    Cada entidade é um nó identificado por um DID único,
    registrado imutavelmente no ledger via operação REG_ENTITY,
    com metadados armazenados em sua wallet digital.

COTTON-NET (Sohn Junior, 2025):
    A replicação para supernodos (CNv1/CNv2) será coordenada
    pelo serviço Coordinator, a ser integrado na próxima etapa.
    Por ora, o cliente opera sobre um único pool.

Uso:
    python main.py

    Ou via Docker:
    docker run --env-file .env cottontrust-client
"""
import asyncio
import json
import sys
import urllib.parse
from pathlib import Path
from loguru import logger

from config import load_settings, Settings
from cottontrust_core.ledger import open_pool, submit_nym
from cottontrust_core.wallet import create_wallet
from cottontrust_core.identity import create_and_store_did
from entities.uba import UBA
from entities.bale import Bale
from metrics.collector import MetricsCollector


# ── Logging ───────────────────────────────────────────────────────────────────

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


# ── Carregamento de dados ─────────────────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    """
    Carrega registros de um arquivo JSON.

    Suporta tanto arrays JSON quanto JSON Lines (um objeto por linha),
    ignorando linhas vazias ou malformadas com um aviso.

    Args:
        path: Caminho do arquivo JSON.

    Returns:
        Lista de dicionários com os registros carregados.
    """
    if not path.exists():
        logger.warning(f"Arquivo não encontrado: {path}")
        return []

    records = []
    with open(path, encoding="utf-8") as f:
        content = f.read().strip()

    # Tenta carregar como array JSON primeiro
    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fallback: JSON Lines (um objeto por linha)
    for i, line in enumerate(content.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning(f"Linha {i} ignorada (JSON inválido): {line[:60]}...")

    return records


# ── Trustee ───────────────────────────────────────────────────────────────────

async def init_trustee(settings: Settings, pool):
    """
    Inicializa o trustee na wallet local.

    O trustee é o endossador de todas as transações NYM no COTTONTRUST.
    Seu DID já está registrado no ledger genesis do VON Network com
    role TRUSTEE, portanto não precisa ser re-registrado — apenas
    sua chave precisa estar disponível na wallet local para assinar.

    Args:
        settings: Configurações da aplicação.
        pool:     Conexão com o pool Indy.

    Returns:
        Tupla (trustee_store, trustee_did).
    """
    logger.info("Inicializando trustee...")

    store = await create_wallet("wallet_trustee", settings.wallet_key)
    did, verkey = await create_and_store_did(store, seed=settings.trustee_seed)

    # Garante que o DID derivado do seed corresponde ao DID configurado
    if did != settings.trustee_did:
        logger.warning(
            f"DID derivado ({did}) difere do TRUSTEE_DID configurado "
            f"({settings.trustee_did}). Verifique o TRUSTEE_SEED."
        )

    # Registra o trustee no ledger (idempotente no VON Network)
    try:
        await submit_nym(
            pool=pool,
            store=store,
            submitter_did=did,
            target_did=did,
            verkey=verkey,
            role="TRUSTEE",
        )
    except RuntimeError as e:
        # DID já registrado — comportamento esperado no VON Network
        logger.debug(f"Trustee já registrado no ledger: {e}")

    logger.info(f"Trustee pronto | did={did}")
    return store, did


# ── Fluxo principal ───────────────────────────────────────────────────────────

async def run() -> None:
    settings = load_settings()
    log_file = str(Path(settings.metrics_output).parent / "cottontrust.log")
    setup_logging(settings.log_level, log_file)

    logger.info("=" * 60)
    logger.info("COTTONTRUST iniciando")
    logger.info(f"Pool:    {settings.genesis_url}")
    logger.info(f"Modelos: {settings.models_dir}")

    # ── Modo de operação ──────────────────────────────────────────────────────
    #
    # COTTON-NET (coordinator_url configurado):
    #   Transações passam pelo cluster RAFT antes de atingir o ledger Indy.
    #   Wallet e DID ainda são gerados localmente; o NYM é submetido pelo
    #   Coordinator após quórum entre os supernodos.
    #
    # Direto (legado COTTONTRUST):
    #   submit_nym() chamado diretamente via indy-vdr, sem consenso externo.
    #
    if settings.coordinator_url:
        logger.info(f"Modo:    COORDINATOR — {settings.coordinator_url}")
        pool          = None
        trustee_store = None
        trustee_did   = ""
    else:
        logger.info("Modo:    DIRETO (Indy ledger)")
        pool = await open_pool(settings.genesis_url)
        trustee_store, trustee_did = await init_trustee(settings, pool)

    logger.info("=" * 60)

    # Inicializa métricas — pool_name derivado do hostname do genesis URL
    pool_name = urllib.parse.urlparse(settings.genesis_url).hostname or "sandbox"
    metrics = MetricsCollector(
        pool_name=pool_name,
        output_path=settings.metrics_output,
    )

    models_dir = Path(settings.models_dir)

    # Registra UBAs
    ubas_data = load_jsonl(models_dir / "ubas.json")
    logger.info(f"Registrando {len(ubas_data)} UBA(s)...")

    for i, data in enumerate(ubas_data, start=1):
        uba = UBA.from_json(data, settings.wallet_key, counter=i)
        await uba.register(
            pool, trustee_store, trustee_did, metrics,
            coordinator_url=settings.coordinator_url,
        )

    # Registra Bales
    bales_data = load_jsonl(models_dir / "bales.json")
    logger.info(f"Registrando {len(bales_data)} Bale(s)...")

    for i, data in enumerate(bales_data, start=1):
        bale = Bale.from_json(data, settings.wallet_key, counter=i)
        await bale.register(
            pool, trustee_store, trustee_did, metrics,
            coordinator_url=settings.coordinator_url,
        )

    # Exporta métricas e exibe resumo
    metrics.save()
    summary = metrics.summary

    logger.info("=" * 60)
    logger.info("COTTONTRUST concluído")
    logger.info(f"Transações:  {summary.get('total_transactions', 0)}")
    logger.info(f"Tempo total: {summary.get('total_time_sec', 0)}s")
    logger.info(f"Média/tx:    {summary.get('avg_time_sec', 0)}s")
    logger.info(f"Mín/tx:      {summary.get('min_time_sec', 0)}s")
    logger.info(f"Máx/tx:      {summary.get('max_time_sec', 0)}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(run())