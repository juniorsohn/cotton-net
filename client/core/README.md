# core — Módulo movido para cottontrust-core

Os módulos `wallet.py`, `identity.py` e `ledger.py` foram extraídos
para o pacote compartilhado `packages/cottontrust-core`, instalável
via pip e usado tanto pelo `client` quanto pelo `coordinator`.

## Imports corretos

```python
# Use sempre assim — não importe de client/core/
from cottontrust_core.wallet   import create_wallet, store_metadata
from cottontrust_core.identity import create_and_store_did, create_seed
from cottontrust_core.ledger   import open_pool, submit_nym
```

## Instalação para desenvolvimento local

A partir da raiz do repositório:

```bash
pip install -e packages/cottontrust-core
```

O `-e` (editable) permite editar os módulos sem reinstalar.
No Docker, a instalação é feita automaticamente pelo Dockerfile.