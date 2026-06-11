from dataclasses import dataclass
from loguru import logger
from entities.base import CottonCell
from cottontrust_core.identity import create_seed

@dataclass
class Talhao(CottonCell):

    @classmethod
    def from_json(cls, data: dict, wallet_key: str, counter: int) -> "Talhao":
        t = cls(
            entity_id=str(data["id"]),
            entity_type="talhao",
            wallet_key=wallet_key,
            metadata={
                "codigo":     data.get("codigo"),
                "descricao":  data.get("descricao"),
                "id_setor":   data.get("id_setor"),
                "id_safra":   data.get("id_safra"),
                "id_empresa": data.get("id_empresa"),
            },
        )
        t._seed = create_seed(counter, data["id"])
        t._public_fields = ["codigo", "descricao"]
        return t

    async def register(
        self, pool, trustee_store, trustee_did, metrics,
        coordinator_url=None, endorser_store=None, endorser_did="",
    ) -> tuple:
        await self.setup(
            pool=pool, trustee_store=trustee_store, trustee_did=trustee_did,
            metrics=metrics, seed=self._seed, coordinator_url=coordinator_url,
            endorser_store=endorser_store, endorser_did=endorser_did,
        )
        logger.info(f"Talhao registrado | codigo='{self.metadata['codigo']}' did={self.did}")
        return self.wallet, self.did
