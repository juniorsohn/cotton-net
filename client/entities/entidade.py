from dataclasses import dataclass
from loguru import logger
from entities.base import CottonCell
from cottontrust_core.identity import create_seed

@dataclass
class Entidade(CottonCell):

    @classmethod
    def from_json(cls, data: dict, wallet_key: str, counter: int) -> "Entidade":
        e = cls(
            entity_id=str(data["id"]),
            entity_type="entidade",
            wallet_key=wallet_key,
            metadata={
                "tipo_entidade": data.get("tipo_entidade"),
                "codigo":        data.get("codigo"),
                "nome_razao":    data.get("nome_razao"),
                "cnpj":          data.get("cnpj"),
                "cpf":           data.get("cpf"),
                "id_empresa":    data.get("id_empresa"),
            },
        )
        e._seed = create_seed(counter, data.get("cnpj") or data["id"])
        e._public_fields = ["nome_razao", "tipo_entidade", "codigo"]
        return e

    async def register(
        self, pool, trustee_store, trustee_did, metrics,
        coordinator_url=None, endorser_store=None, endorser_did="",
    ) -> tuple:
        await self.setup(
            pool=pool, trustee_store=trustee_store, trustee_did=trustee_did,
            metrics=metrics, seed=self._seed, coordinator_url=coordinator_url,
            endorser_store=endorser_store, endorser_did=endorser_did,
        )
        logger.info(f"Entidade registrada | nome='{self.metadata['nome_razao']}' did={self.did}")
        return self.wallet, self.did
