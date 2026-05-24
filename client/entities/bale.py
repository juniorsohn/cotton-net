"""
Fardinho de Algodão (Bale).

Representa um lote de algodão produzido em uma UBA, com
rastreabilidade completa de tipo de produto, pesos e timestamp
de produção. No COTTONTRUST, o fardinho é um titular de
credenciais verificáveis emitidas pela UBA que o produziu.

Estrutura JSON de entrada (Listing 4.2 do TCC):
    {
        "id":                  "ID da transação do fardinho",
        "id_beneficiamento":   "processo de beneficiamento de origem",
        "id_produto":          "ID único do tipo de produto",
        "produto_descricao":   "nome do tipo de produto",
        "peso_bruto":          "peso com embalagem (kg)",
        "peso_liquido":        "peso do produto puro (kg)",
        "data_hora_producao":  "timestamp ISO de produção"
    }
"""
from dataclasses import dataclass
from loguru import logger

from entities.base import CottonCell
from cottontrust_core.identity import create_seed
from metrics.collector import MetricsCollector


@dataclass
class Bale(CottonCell):
    """
    Fardinho de Algodão.

    Herda de CottonCell. Os atributos de rastreabilidade do fardinho
    (pesos, tipo de produto, timestamp) são armazenados como
    metadados na wallet digital, vinculados ao DID registrado no ledger.
    """

    @classmethod
    def from_json(cls, data: dict, wallet_key: str, counter: int) -> "Bale":
        """
        Instancia um Bale a partir de um registro JSON.

        O seed é gerado a partir do contador e do id_produto,
        garantindo que fardinhos do mesmo tipo em execuções
        diferentes produzam DIDs distintos (pelo contador).

        Args:
            data:       Registro JSON do fardinho.
            wallet_key: Chave de acesso à wallet.
            counter:    Posição sequencial (usado no seed).

        Returns:
            Bale instanciado, pronto para chamar register().
        """
        bale = cls(
            entity_id=str(data["id"]),
            entity_type="bale",
            wallet_key=wallet_key,
            metadata={
                "id_beneficiamento":  data["id_beneficiamento"],
                "id_produto":         data["id_produto"],
                "produto_descricao":  data["produto_descricao"],
                "peso_bruto":         data["peso_bruto"],
                "peso_liquido":       data["peso_liquido"],
                "data_hora_producao": data["data_hora_producao"],
            },
        )
        bale._seed = create_seed(counter, data["id_produto"])
        return bale

    async def register(
        self,
        pool,
        trustee_store,
        trustee_did: str,
        metrics: MetricsCollector,
        coordinator_url: str | None = None,
    ) -> None:
        """
        Registra o fardinho no ledger COTTONTRUST.

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
            f"Bale pronto | "
            f"produto='{self.metadata['produto_descricao']}' "
            f"peso_liq={self.metadata['peso_liquido']}kg"
        )