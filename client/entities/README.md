# entities — Entidades da cadeia produtiva

Implementação do modelo COTTON-CELL: cada participante da cadeia
do algodão possui DID próprio, wallet digital, metadados e atributos
públicos no ledger. O registro usa o padrão SSI author+endorser —
a entidade assina seu próprio NYM e a entidade-pai countersigns.

## Hierarquia

```
CottonCell (base.py)
├── Entidade   — empresa/cooperativa produtora     (endorser: trustee)
├── Fazenda    — propriedade rural                 (endorser: trustee)
│   └── Setor  — subdivisão da fazenda             (endorser: Fazenda)
│       └── Talhao — parcela agrícola              (endorser: Setor)
└── Armazem    — unidade de beneficiamento (UBA)   (endorser: trustee)
    ├── LoteMP — lote de matéria-prima             (endorser: Armazem)
    └── Fardinho — fardo individual de pluma       (endorser: Armazem via id_armazem)
```

## Dados públicos no ledger (ATTRIB)

Cada entidade define `_public_fields` — campos não-sensíveis
gravados como ATTRIB transaction após o NYM:

| Entidade | Campos públicos |
|---|---|
| Entidade | `nome_razao`, `tipo_entidade`, `codigo` |
| Fazenda | `codigo`, `descricao` |
| Setor | `codigo`, `descricao` |
| Talhao | `codigo`, `descricao` |
| Armazem | `codigo`, `descricao`, `local` |
| LoteMP | `codigo`, `peso_liquido`, `rendimento`, `status` |
| Fardinho | `peso_bruto`, `peso_liquido`, `data_hora_producao` |

Dados sensíveis (CPF, CNPJ, geolocalização) ficam apenas na wallet local.

## Como adicionar uma nova entidade

1. Crie `entities/nova.py` herdando de `CottonCell`
2. Implemente `from_json()` com `metadata` e `_public_fields`
3. Implemente `register()` chamando `self.setup()`
4. Exporte em `__init__.py` e use em `main.py`

```python
from dataclasses import dataclass
from loguru import logger
from entities.base import CottonCell
from cottontrust_core.identity import create_seed

@dataclass
class Nova(CottonCell):

    @classmethod
    def from_json(cls, data: dict, wallet_key: str, counter: int) -> "Nova":
        obj = cls(
            entity_id=str(data["id"]),
            entity_type="nova",
            wallet_key=wallet_key,
            metadata={"campo": data.get("campo")},
        )
        obj._seed = create_seed(counter, data["id"])
        obj._public_fields = ["campo"]
        return obj

    async def register(
        self, pool, trustee_store, trustee_did, metrics,
        coordinator_url=None, endorser_store=None, endorser_did="",
    ) -> tuple:
        await self.setup(
            pool=pool, trustee_store=trustee_store, trustee_did=trustee_did,
            metrics=metrics, seed=self._seed, coordinator_url=coordinator_url,
            endorser_store=endorser_store, endorser_did=endorser_did,
        )
        return self.wallet, self.did
```

## Estrutura JSON esperada (exemplos)

### Armazem (`models/armazens.json`)
```json
{
    "id":         "uuid",
    "codigo":     "ARM-01",
    "descricao":  "Armazém Central",
    "local":      "integrado",
    "id_empresa": "uuid-empresa"
}
```

### LoteMP (`models/lotes_mp.json`)
```json
{
    "id":          "uuid",
    "codigo":      "LMP-001",
    "peso_liquido": 1250.0,
    "rendimento":  38.5,
    "status":      "beneficiado",
    "id_armazem":  "uuid-armazem"
}
```

### Fardinho (`models/fardinhos.json`)
```json
{
    "id":                  "uuid",
    "peso_bruto":          227.5,
    "peso_liquido":        220.0,
    "data_hora_producao":  "2021-03-15T08:30:00",
    "id_beneficiamento":   "uuid-ben"
}
```
