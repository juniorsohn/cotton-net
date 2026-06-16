"""
COTTONTRUST — Indy Validator Exporter

Exportador Prometheus que coleta métricas internas dos nós validadores
Indy via GET_VALIDATOR_INFO e as expõe para scrape.

Completamente autônomo: não depende de cottontrust_core nem de nenhum
outro serviço do stack. Se o pool estiver indisponível, aguarda e tenta
novamente indefinidamente sem travar o Prometheus.

Variáveis de ambiente:
    GENESIS_URL      URL do genesis (obrigatório)
    TRUSTEE_DID      DID do trustee para assinar a requisição
    TRUSTEE_SEED     Seed do trustee (32 chars)
    SCRAPE_INTERVAL  Intervalo entre scrapes em segundos (padrão: 30)
    SUBMIT_TIMEOUT   Timeout do submit_action em segundos (padrão: 15)
    PORT             Porta HTTP do exporter (padrão: 9309)
"""
import asyncio
import json
import os
import sys
import time
import urllib.request

from loguru import logger
from prometheus_client import Gauge, start_http_server
from aries_askar import Key, KeyAlg
import indy_vdr
from indy_vdr import ledger as indy_ledger

# ── Configuração ──────────────────────────────────────────────────────────────

GENESIS_URL     = os.environ["GENESIS_URL"]
TRUSTEE_DID     = os.environ.get("TRUSTEE_DID",     "V4SGRU86Z58d6TV7PBUe6f")
TRUSTEE_SEED    = os.environ.get("TRUSTEE_SEED",    "000000000000000000000000Trustee1")
SCRAPE_INTERVAL = int(os.environ.get("SCRAPE_INTERVAL", "30"))
SUBMIT_TIMEOUT  = int(os.environ.get("SUBMIT_TIMEOUT",  "15"))
PORT            = int(os.environ.get("PORT",             "9309"))

# ── Logging ───────────────────────────────────────────────────────────────────

logger.remove()
logger.add(
    sys.stdout,
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "indy-exporter — <level>{message}</level>"
    ),
    colorize=True,
)

# ── Métricas Prometheus ───────────────────────────────────────────────────────
# Labels: [node] = nome do nó Indy (ex: "Node1", "Node2")

WRITE_TPS     = Gauge("indy_write_tx_per_second",
                      "Throughput de escrita (tx/s) reportado internamente pelo nó",
                      ["node"])
READ_TPS      = Gauge("indy_read_tx_per_second",
                      "Throughput de leitura (tx/s) reportado internamente pelo nó",
                      ["node"])
TXN_DOMAIN    = Gauge("indy_txn_count_domain",
                      "Transações acumuladas no ledger domain (NYMs, ATTRIBs, etc.)",
                      ["node"])
TXN_POOL      = Gauge("indy_txn_count_pool",
                      "Transações acumuladas no ledger pool (membership)",
                      ["node"])
UPTIME        = Gauge("indy_uptime_seconds",
                      "Tempo de vida do processo indy-node em segundos",
                      ["node"])
REACHABLE     = Gauge("indy_reachable_nodes",
                      "Peers alcançáveis por este nó (conectividade RBFT)",
                      ["node"])
BLACKLISTED   = Gauge("indy_blacklisted_nodes",
                      "Peers na blacklist deste nó (suspeitos de falha)",
                      ["node"])
VIEW_CHANGE   = Gauge("indy_view_change_in_progress",
                      "1 se view change em andamento (indica instabilidade PBFT)",
                      ["node"])
IS_PRIMARY    = Gauge("indy_is_primary",
                      "1 se este nó é o primário PBFT atual (replica 0)",
                      ["node"])
LAST_ORDERED  = Gauge("indy_last_ordered_3pc_seqno",
                      "Último número de sequência de consenso 3PC confirmado",
                      ["node"])
MEM_USED      = Gauge("indy_mem_used_gb",
                      "Uso de memória RAM pelo processo indy-node (GB)",
                      ["node"])
HAS_CONSENSUS = Gauge("indy_has_write_consensus",
                      "1 se o ledger domain tem write consensus neste nó",
                      ["node"])

# Métricas de saúde do próprio exporter
SCRAPE_OK     = Gauge("indy_scrape_success",
                      "1 se o último ciclo de scrape completou sem erros")
SCRAPE_DUR    = Gauge("indy_scrape_duration_seconds",
                      "Duração do último ciclo de scrape em segundos")
NODES_UP      = Gauge("indy_nodes_responding",
                      "Número de nós que responderam no último scrape")


# ── Chave do trustee (sem wallet — assinatura direta) ─────────────────────────

def _load_trustee_key() -> Key:
    seed_bytes = TRUSTEE_SEED.encode("utf-8")[:32].ljust(32, b"\x00")
    return Key.from_secret_bytes(KeyAlg.ED25519, seed_bytes)


def _sign(key: Key, request) -> None:
    signature = key.sign_message(request.signature_input)
    request.set_signature(signature)


# ── Conexão com o pool ────────────────────────────────────────────────────────

async def _open_pool_with_retry() -> indy_vdr.Pool:
    attempt = 0
    while True:
        attempt += 1
        try:
            with urllib.request.urlopen(GENESIS_URL, timeout=10) as resp:
                genesis_txns = resp.read().decode("utf-8")
            pool = await indy_vdr.open_pool(transactions=genesis_txns)
            logger.info(f"Pool conectado | genesis={GENESIS_URL}")
            return pool
        except Exception as e:
            delay = min(30 * attempt, 300)
            logger.warning(f"Pool indisponível (tentativa {attempt}) — aguardando {delay}s | erro={e}")
            await asyncio.sleep(delay)


# ── Parser da resposta GET_VALIDATOR_INFO ─────────────────────────────────────

def _parse_node_response(node_name: str, raw) -> dict | None:
    """
    Extrai o dicionário de dados de um nó da resposta do submit_action.

    A resposta pode ser um dict aninhado ou uma string JSON.
    Retorna None se o nó não respondeu ou a resposta é inválida.
    """
    try:
        if isinstance(raw, str):
            raw = json.loads(raw)

        op = raw.get("op", "")
        if op != "REPLY":
            logger.debug(f"Nó {node_name} respondeu op={op} — ignorado")
            return None

        data = raw.get("result", {}).get("data", {})
        if isinstance(data, str):
            data = json.loads(data)

        return data
    except Exception as e:
        logger.debug(f"Nó {node_name} — erro ao parsear resposta: {e}")
        return None


def _update_metrics(node_name: str, data: dict) -> None:
    """Atualiza as Gauges Prometheus com os dados de um nó."""
    label = node_name

    # Throughput interno
    avg = data.get("Metrics", {}).get("average-per-second", {})
    WRITE_TPS.labels(label).set(avg.get("write-transactions", 0))
    READ_TPS.labels(label).set(avg.get("read-transactions",  0))

    # Contagem de transações
    txn = data.get("Metrics", {}).get("transaction-count", {})
    TXN_DOMAIN.labels(label).set(txn.get("ledger", 0))
    TXN_POOL.labels(label).set(txn.get("pool", 0))

    # Uptime
    UPTIME.labels(label).set(data.get("Metrics", {}).get("uptime", 0))

    # Conectividade
    pool_info   = data.get("Pool_info", {})
    reachable   = pool_info.get("Reachable_nodes", [])
    blacklisted = pool_info.get("Blacklisted_nodes", [])
    REACHABLE.labels(label).set(len(reachable))
    BLACKLISTED.labels(label).set(len(blacklisted))

    # Estabilidade PBFT
    vc = data.get("View_change_in_progress", False)
    VIEW_CHANGE.labels(label).set(1 if vc else 0)

    # Primário (replica 0)
    replicas = data.get("Replicas_status", {})
    replica_0 = replicas.get(f"{node_name}:0", replicas.get(list(replicas.keys())[0], {})) \
        if replicas else {}
    primary_str = replica_0.get("Primary", "")
    is_primary  = primary_str.startswith(node_name) if primary_str else False
    IS_PRIMARY.labels(label).set(1 if is_primary else 0)

    # Último seq# de consenso
    last_3pc = replica_0.get("Last_ordered_3PC", [0, 0])
    LAST_ORDERED.labels(label).set(last_3pc[1] if len(last_3pc) > 1 else 0)

    # Hardware
    hw = data.get("Hardware", {})
    MEM_USED.labels(label).set(hw.get("MEM_used_size_in_GB", 0))

    # Write consensus
    freshness = data.get("freshness_status", {})
    domain_fresh = freshness.get("0", {}).get("Has_write_consensus", True)
    HAS_CONSENSUS.labels(label).set(1 if domain_fresh else 0)


# ── Loop principal ────────────────────────────────────────────────────────────

async def scrape_loop(pool: indy_vdr.Pool, key: Key) -> None:
    """Coleta métricas em loop. Nunca lança exceção — só loga e dorme."""
    while True:
        t0 = time.monotonic()
        nodes_ok = 0

        try:
            req = indy_ledger.build_get_validator_info_request(TRUSTEE_DID)
            _sign(key, req)

            responses = await asyncio.wait_for(
                pool.submit_action(req),
                timeout=SUBMIT_TIMEOUT,
            )

            if not isinstance(responses, dict):
                raise ValueError(f"Resposta inesperada: {type(responses)}")

            for node_name, raw in responses.items():
                data = _parse_node_response(node_name, raw)
                if data is None:
                    continue
                _update_metrics(node_name, data)
                nodes_ok += 1
                logger.debug(f"Métricas coletadas | node={node_name}")

            SCRAPE_OK.set(1 if nodes_ok > 0 else 0)
            NODES_UP.set(nodes_ok)
            logger.info(f"Scrape completo | nós={nodes_ok}/{len(responses)}")

        except asyncio.TimeoutError:
            logger.warning(f"Scrape timeout após {SUBMIT_TIMEOUT}s")
            SCRAPE_OK.set(0)
        except Exception as e:
            logger.warning(f"Erro no scrape: {e}")
            SCRAPE_OK.set(0)

        SCRAPE_DUR.set(time.monotonic() - t0)
        await asyncio.sleep(SCRAPE_INTERVAL)


async def main() -> None:
    logger.info(f"Indy Exporter iniciando | genesis={GENESIS_URL} port={PORT} interval={SCRAPE_INTERVAL}s")

    start_http_server(PORT)
    logger.info(f"Métricas disponíveis em http://0.0.0.0:{PORT}/metrics")

    key  = _load_trustee_key()
    pool = await _open_pool_with_retry()

    await scrape_loop(pool, key)


if __name__ == "__main__":
    asyncio.run(main())
