from dataclasses import dataclass
from loguru import logger
from entities.base import CottonCell
from cottontrust_core.identity import create_seed

@dataclass
class LoteMP(CottonCell):

    @classmethod
    def from_json(cls, data: dict, wallet_key: str, counter: int) -> "LoteMP":
        l = cls(
            entity_id=str(data["id"]),
            entity_type="lote_mp",
            wallet_key=wallet_key,
            metadata={
                "codigo":                   data.get("codigo"),
                "peso_estimado":            data.get("peso_estimado"),
                "peso_liquido":             data.get("peso_liquido"),
                "rendimento":               data.get("rendimento"),
                "rendimento_realizado":     data.get("rendimento_realizado"),
                "id_armazem":               data.get("id_armazem"),
                "id_produto":               data.get("id_produto"),
                "id_talhao":                data.get("id_talhao"),
                "status":                   data.get("status"),
                "geolocalizacao_latitude":  data.get("geolocalizacao_latitude"),
                "geolocalizacao_longitude": data.get("geolocalizacao_longitude"),
                "id_empresa":               data.get("id_empresa"),
            },
        )
        l._seed = create_seed(counter, data["id"])
        l._public_fields = ["codigo", "peso_liquido", "rendimento", "status"]
        return l

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
            f"LoteMP registrado | codigo='{self.metadata['codigo']}' "
            f"armazem={self.metadata['id_armazem']} did={self.did}"
        )
        return self.wallet, self.did
