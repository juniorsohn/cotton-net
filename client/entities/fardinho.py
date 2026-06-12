from dataclasses import dataclass
from loguru import logger
from entities.base import CottonCell
from cottontrust_core.identity import create_seed

@dataclass
class Fardinho(CottonCell):

    @classmethod
    def from_json(cls, data: dict, wallet_key: str, counter: int) -> "Fardinho":
        f = cls(
            entity_id=str(data["id"]),
            entity_type="fardinho",
            wallet_key=wallet_key,
            metadata={
                "id_beneficiamento":  data.get("id_beneficiamento"),
                "id_produto":         data.get("id_produto"),
                "peso_bruto":         data.get("peso_bruto"),
                "peso_liquido":       data.get("peso_liquido"),
                "data_hora_producao": data.get("data_hora_producao"),
                "id_empresa":         data.get("id_empresa"),
                "id_armazem":         data.get("id_armazem"),
            },
        )
        f._seed = create_seed(counter, data["id"])
        f._public_fields = ["peso_bruto", "peso_liquido", "data_hora_producao"]
        return f

    async def register(
        self, pool, trustee_store, trustee_did, metrics,
        coordinator_url=None, endorser_store=None, endorser_did="",
    ) -> tuple:
        await self.setup(
            pool=pool, trustee_store=trustee_store, trustee_did=trustee_did,
            metrics=metrics, seed=self._seed, coordinator_url=coordinator_url,
            endorser_store=endorser_store, endorser_did=endorser_did,
        )
        logger.info(
            f"Fardinho registrado | peso_liq={self.metadata['peso_liquido']}kg did={self.did}"
        )
        return self.wallet, self.did
