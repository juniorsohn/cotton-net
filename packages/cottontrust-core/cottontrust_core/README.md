# cottontrust_core — Primitivas blockchain

Pacote compartilhado entre `client` e `coordinator`. Camada de abstração
sobre `indy-vdr` e `aries-askar`. Nenhum outro módulo deve importar
essas bibliotecas diretamente.

## Instalação

```bash
# Desenvolvimento local (a partir da raiz do repositório)
pip install -e packages/cottontrust-core

# No Dockerfile (feito automaticamente)
pip install /tmp/cottontrust-core
```

## Módulos

### `wallet.py` — Wallets digitais (aries-askar)

Gerencia wallets SQLite por entidade. Cada wallet armazena
a chave privada Ed25519 e os metadados da entidade.

```python
from cottontrust_core.wallet import create_wallet, store_metadata

store = await create_wallet("wallet_armazem_001", "minha_chave")
await store_metadata(store, "001", {"codigo": "ARM", "local": "SP"})
```

### `identity.py` — DIDs (aries-askar + base58)

Deriva e armazena pares DID/verkey compatíveis com o Hyperledger Indy.

```python
from cottontrust_core.identity import create_and_store_did, create_seed

seed = create_seed(counter=1, name="ARM001")
did, verkey = await create_and_store_did(store, seed=seed)
```

### `ledger.py` — Ledger Indy (indy-vdr)

Três funções de submissão para os três modos de operação:

```python
from cottontrust_core.ledger import open_pool, submit_nym, submit_nym_endorsed, submit_attrib

pool = await open_pool("http://baia1:9000/genesis")

# Modo direto — trustee assina
response, tx_size = await submit_nym(
    pool=pool, store=trustee_store, submitter_did=trustee_did,
    target_did=did, verkey=verkey,
)

# Modo endorsed — author + endorser assinam (author+endorser SSI)
response, tx_size = await submit_nym_endorsed(
    pool=pool,
    author_store=entity_wallet, author_did=entity_did,
    endorser_store=parent_wallet, endorser_did=parent_did,
    target_did=entity_did, verkey=entity_verkey,
)

# Atributos públicos on-chain (rastreabilidade)
tx_size = await submit_attrib(
    pool=pool, store=entity_wallet, submitter_did=entity_did,
    raw_attrs={"codigo": "ARM-01", "descricao": "Armazém Central"},
)
```

## Decisões de design

- **Sem estado global**: cada função recebe o que precisa via parâmetros.
- **Pool como parâmetro**: permite múltiplos pools (supernodos) simultaneamente.
- **Assinatura explícita**: separada da submissão, viabilizando o padrão author+endorser.
- **Pacote instalável**: compartilhado via `pip install` entre `client` e `coordinator`, evitando duplicação.
- **Dados sensíveis fora do ledger**: `submit_attrib` recebe apenas os campos declarados em `_public_fields` — CPF, CNPJ e geolocalização nunca chegam a essa função.
