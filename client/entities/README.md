# entities — Entidades da cadeia produtiva

Implementação do modelo COTTON-CELL: cada participante da cadeia
do algodão é uma entidade com DID, wallet e metadados próprios.

## Hierarquia

```
CottonCell (base.py)
├── UBA    (uba.py)   — Unidade de Beneficiamento de Algodão
└── Bale   (bale.py)  — Fardinho de algodão
```

## Como adicionar uma nova entidade

1. Crie `entities/nova_entidade.py` herdando de `CottonCell`
2. Implemente `from_json()` com os campos específicos em `metadata`
3. Implemente `register()` chamando `self.setup()`
4. Importe e use em `main.py`

```python
from entities.base import CottonCell
from core.identity import create_seed

@dataclass
class Farm(CottonCell):

    @classmethod
    def from_json(cls, data, wallet_key, counter):
        farm = cls(
            entity_id=str(data["id"]),
            entity_type="farm",
            wallet_key=wallet_key,
            metadata={"nome": data["nome"], "municipio": data["municipio"]},
        )
        farm._seed = create_seed(counter, data["id"])
        return farm

    async def register(self, pool, trustee_store, trustee_did, metrics):
        await self.setup(pool, trustee_store, trustee_did, metrics, self._seed)
```

## Estrutura JSON esperada

### UBA (`models/ubas.json`)
```json
{
    "id":         "TX-001",
    "codigo":     "USINA",
    "descricao":  "Usina Exemplo Ltda",
    "local":      "integrado",
    "id_empresa": "EMP-42"
}
```

### Bale (`models/bales.json`)
```json
{
    "id":                  "BL-001",
    "id_beneficiamento":   "BEN-10",
    "id_produto":          "PROD-3",
    "produto_descricao":   "Algodão em Pluma",
    "peso_bruto":          227.5,
    "peso_liquido":        220.0,
    "data_hora_producao":  "2021-03-15T08:30:00"
}
```