from dataclasses import dataclass
from loguru import logger
from entities.base import CottonCell
from cottontrust_core.identity import create_seed

@dataclass
class Armazem(CottonCell):

    @classmethod
    def from_json(cls, data: dict, wallet_key: str, counter: int) -> "Armazem":
        a = cls(
            entity_id=str(data["id"]),
            entity_type="armazem",
            wallet_key=wallet_key,
            metadata={
                "codigo":     data.get("codigo"),
                "descricao":  data.get("descricao"),
                "local":      data.get("local"),
                "id_empresa": data.get("id_empresa"),
            },
        )
        a._seed = create_seed(counter, data["id"])
        a._public_fields = ["codigo", "descricao", "local"]
        a._ledger_role = "ENDORSER"
        return a

    async def register(
        self, pool, trustee_store, trustee_did, metrics,
        coordinator_url=None, endorser_store=None, endorser_did="",
    ) -> tuple:
        await self.setup(
            pool=pool, trustee_store=trustee_store, trustee_did=trustee_did,
            metrics=metrics, seed=self._seed, coordinator_url=coordinator_url,
            endorser_store=endorser_store, endorser_did=endorser_did,
        )
        logger.info(f"Armazem registrado | nome='{self.metadata['descricao']}' did={self.did}")
        return self.wallet, self.did
