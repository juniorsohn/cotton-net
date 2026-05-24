"""
Unidade de Beneficiamento de Algodão (UBA).

Representa uma usina de beneficiamento, galpão, depósito ou
fábrica de fertilizantes participante da cadeia produtiva.
No COTTONTRUST, a UBA é um emissor de credenciais verificáveis
para os fardinhos que processa.

Estrutura JSON de entrada (Listing 4.1 do TCC):
    {
        "id":         "identificador único da transação",
        "codigo":     "tipo da empresa (usina, galpão, depósito...)",
        "descricao":  "nome da empresa",
        "local":      "integração ou não",
        "id_empresa": "identificador da empresa ou setor"
    }
"""
from dataclasses import dataclass
from loguru import logger

from entities.base import CottonCell
from cottontrust_core.identity import create_seed
from metrics.collector import MetricsCollector


@dataclass
class UBA(CottonCell):
    """
    Unidade de Beneficiamento de Algodão.

    Herda de CottonCell. Os atributos específicos da UBA
    (codigo, descricao, local, id_empresa) são armazenados
    como metadados na wallet digital.
    """

    @classmethod
    def from_json(cls, data: dict, wallet_key: str, counter: int) -> "UBA":
        """
        Instancia uma UBA a partir de um registro JSON.

        O seed é gerado deterministicamente a partir do contador
        e do código da empresa, garantindo reprodutibilidade
        entre execuções dos experimentos.

        Args:
            data:       Registro JSON da UBA.
            wallet_key: Chave de acesso à wallet.
            counter:    Posição sequencial (usado no seed).

        Returns:
            UBA instanciada, pronta para chamar register().
        """
        uba = cls(
            entity_id=str(data["id"]),
            entity_type="uba",
            wallet_key=wallet_key,
            metadata={
                "codigo":     data["codigo"],
                "descricao":  data["descricao"],
                "local":      data["local"],
                "id_empresa": data["id_empresa"],
            },
        )
        # Seed guardado internamente, usado em register()
        uba._seed = create_seed(counter, data["codigo"])
        return uba

    async def register(
        self,
        pool,
        trustee_store,
        trustee_did: str,
        metrics: MetricsCollector,
        coordinator_url: str | None = None,
    ) -> None:
        """
        Registra a UBA no ledger COTTONTRUST.

        Delega para CottonCell.setup() com o seed determinístico.

        Args:
            pool:            Conexão com o pool Indy (None no modo coordinator).
            trustee_store:   Wallet do trustee (None no modo coordinator).
            trustee_did:     DID do trustee (vazio no modo coordinator).
            metrics:         Coletor de métricas.
            coordinator_url: URL do Coordinator RAFT (modo COTTON-NET).
        """
        await self.setup(
            pool=pool,
            trustee_store=trustee_store,
            trustee_did=trustee_did,
            metrics=metrics,
            seed=self._seed,
            coordinator_url=coordinator_url,
        )
        logger.info(
            f"UBA pronta | "
            f"nome='{self.metadata['descricao']}' "
            f"tipo='{self.metadata['codigo']}'"
        )