"""
Configuração centralizada do COTTONTRUST.

Todas as variáveis de ambiente são carregadas aqui e expostas
como um objeto Settings tipado. Nenhum outro módulo deve
chamar os.environ diretamente.

Uso:
    from config import load_settings
    settings = load_settings()
    print(settings.genesis_url)
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """
    Configurações da aplicação.

    Attributes:
        genesis_url:      URL ou caminho do arquivo genesis do pool Indy.
        trustee_seed:     Seed do trustee para derivação de DID/verkey.
        trustee_did:      DID do trustee já registrado no ledger genesis.
        wallet_key:       Chave de acesso às wallets (aries-askar).
        models_dir:       Diretório com os arquivos JSON de entidades.
        metrics_output:   Caminho do arquivo CSV de saída de métricas.
        log_level:        Nível de log (DEBUG, INFO, WARNING, ERROR).
        coordinator_url:  URL base do Coordinator RAFT (modo COTTON-NET).
                          Se None, opera em modo direto (Indy local).
    """
    genesis_url:     str
    trustee_seed:    str
    trustee_did:     str
    wallet_key:      str
    models_dir:      str
    metrics_output:  str
    log_level:       str
    coordinator_url: str | None   # None = modo direto (sem RAFT)
    data_dir:        str | None   # None = usa models_dir (JSON sintético legado)
    concurrency:     int          # workers paralelos dentro do processo


def load_settings() -> Settings:
    """
    Carrega e valida as configurações do ambiente.

    Raises:
        EnvironmentError: Se alguma variável obrigatória estiver ausente.
    """
    required = ["GENESIS_URL", "TRUSTEE_SEED", "TRUSTEE_DID"]
    missing = [k for k in required if not os.environ.get(k)]

    if missing:
        raise EnvironmentError(
            f"Variáveis de ambiente obrigatórias ausentes: {', '.join(missing)}\n"
            f"Copie .env.example para .env e preencha os valores."
        )

    return Settings(
        genesis_url=os.environ["GENESIS_URL"],
        trustee_seed=os.environ["TRUSTEE_SEED"],
        trustee_did=os.environ["TRUSTEE_DID"],
        wallet_key=os.environ.get("WALLET_KEY", "changeme"),
        models_dir=os.environ.get("MODELS_DIR", "./models"),
        metrics_output=os.environ.get("METRICS_OUTPUT", "./output/raw_tx_metrics.csv"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        coordinator_url=os.environ.get("COORDINATOR_URL") or None,
        data_dir=os.environ.get("DATA_DIR") or None,
        concurrency=int(os.environ.get("CONCURRENCY", "1")),
    )