# COTTON-NET — Fixes identificados em revisão de código

## Contexto do projeto

Este é o COTTON-NET, uma arquitetura distribuída para rastreabilidade
na cadeia produtiva do algodão, baseada em Hyperledger Indy + RAFT.

Estrutura relevante:
```
cottontrust/
├── packages/cottontrust-core/cottontrust_core/
│   ├── wallet.py      (aries-askar)
│   ├── identity.py    (DID Ed25519)
│   └── ledger.py      (indy-vdr)
├── client/
│   ├── main.py
│   ├── entities/
│   │   ├── base.py
│   │   ├── uba.py
│   │   └── bale.py
│   └── metrics/
│       └── collector.py
└── coordinator/
    ├── main.py        (FastAPI + raftify)
    ├── fsm.py         (AbstractStateMachine)
    ├── log_entry.py   (NymLogEntry)
    ├── supernodes.py  (SupernodeRegistry)
    └── pending.py     (PendingQueue)
```

---

## Fixes necessários

### 🔴 Fix 1 — `coordinator/fsm.py`: `apply()` recebe bytes, não objeto

O raftify chama `FSM.apply()` com os bytes brutos do log entry,
não com o objeto já deserializado. O método precisa deserializar
internamente antes de processar.

**Atual:**
```python
async def apply(self, entry: NymLogEntry) -> None:
    logger.info(f"FSM aplicando | entity_id={entry.entity_id} ...")
    try:
        _, tx_size = await submit_nym(...)
```

**Correto:**
```python
async def apply(self, data: bytes) -> None:
    entry = NymLogEntry.decode(data)
    logger.info(f"FSM aplicando | entity_id={entry.entity_id} ...")
    try:
        _, tx_size = await submit_nym(...)
```

Fazer o mesmo ajuste no `snapshot()` e `restore()` se necessário
para manter consistência com a interface do raftify.

---

### 🔴 Fix 2 — `coordinator/main.py`: construção de peers RAFT incorreta

O `NODE_ID` atual é uma string como `"node-1"`, mas o raftify
espera IDs numéricos inteiros. Além disso, a construção do mapa
de peers atribui IDs `"2"`, `"3"`, `"4"` independentemente do
NODE_ID do próprio nó — o que está errado.

A solução é:
1. Adicionar a variável de ambiente `NODE_NUM` (inteiro: 1, 2, 3, 4)
   para uso interno no raftify, mantendo `NODE_ID` como string
   amigável para logs
2. Reconstruir o mapa de peers usando os endereços de `RAFT_PEERS`
   com IDs numéricos sequenciais, excluindo o próprio nó

Exemplo de variáveis de ambiente que o coordinator vai receber:
```
NODE_ID=node-1
NODE_NUM=1
RAFT_ADDR=0.0.0.0:60061
RAFT_PEERS=coordinator-2:60061,coordinator-3:60061,coordinator-4:60061
```

A lógica de construção de peers deve:
- Usar `NODE_NUM` (int) como ID deste nó no raftify
- Gerar IDs sequenciais para os peers, pulando o ID deste nó
- Garantir que os IDs sejam inteiros, não strings

Atualizar o `docker-compose.yml` para incluir `NODE_NUM` em cada
coordinator (1, 2, 3, 4 respectivamente).

---

### 🔴 Fix 3 — `coordinator/supernodes.py`: `pool.get_status()` não existe

O indy-vdr não expõe `pool.get_status()`. O healthcheck do supernodo
precisa ser feito de outra forma.

Substituir por uma tentativa de buscar a transação genesis (seqNo=1)
do ledger usando `indy_vdr.ledger.build_get_txn_request()`:

```python
async def healthcheck(self) -> bool:
    if not self.pool:
        self.alive = False
        return False
    try:
        import indy_vdr
        request = indy_vdr.ledger.build_get_txn_request(
            submitter_did=None,
            ledger_type=1,   # DOMAIN ledger
            seq_no=1,
        )
        response = await self.pool.submit_request(request)
        self.alive = response.get("op") != "REQNACK"
    except Exception:
        self.alive = False
    return self.alive
```

---

### 🔴 Fix 4 — `client/entities/` e `client/metrics/`: faltam `__init__.py`

Criar arquivos `__init__.py` vazios nos seguintes diretórios para
que Python os reconheça como pacotes:

- `client/entities/__init__.py`
- `client/metrics/__init__.py`

---

### 🟡 Fix 5 — `coordinator/pending.py`: `BACKOFF_FACTOR` declarado mas não implementado

O `BACKOFF_FACTOR = 1.5` está declarado mas o `_worker` usa
`RETRY_INTERVAL` fixo. Implementar backoff exponencial real:

```python
async def _worker(self, submit_fn) -> None:
    while True:
        await asyncio.sleep(self.RETRY_INTERVAL)
        async with self._lock:
            pending = list(self._queue.values())

        for item in pending:
            try:
                await submit_fn(item.entry)
                await self.remove(item.entry.entity_id)
                ...
            except Exception as e:
                item.attempts += 1
                item.last_tried = datetime.now()
                item.error = str(e)
                # Backoff exponencial: espera aumenta a cada falha
                item.next_retry_sec = min(
                    self.RETRY_INTERVAL * (self.BACKOFF_FACTOR ** item.attempts),
                    300  # cap de 5 minutos
                )
                ...
```

Adicionar `next_retry_sec: float` ao `PendingEntry` e checar
`datetime.now() >= last_tried + timedelta(seconds=next_retry_sec)`
antes de tentar o retry.

---

### 🟡 Fix 6 — `cottontrust_core/wallet.py`: `WALLET_DIR` hardcoded

O `WALLET_DIR = Path("/app/wallets")` quebra em desenvolvimento local.
Tornar configurável:

```python
import os
WALLET_DIR = Path(os.environ.get("WALLET_DIR", "/app/wallets"))
```

---

### 🟡 Fix 7 — `client/main.py`: `pool_name` hardcoded no MetricsCollector

```python
# Atual
metrics = MetricsCollector(
    pool_name="sandbox",
    output_path=settings.metrics_output,
)

# Correto — derivar do genesis URL
import urllib.parse
pool_name = urllib.parse.urlparse(settings.genesis_url).hostname or "sandbox"
metrics = MetricsCollector(
    pool_name=pool_name,
    output_path=settings.metrics_output,
)
```

---

## Instruções gerais

- Manter o estilo de código existente (docstrings, type hints, loguru)
- Não alterar a lógica de negócio — apenas corrigir os bugs listados
- Após cada fix, verificar se há outros arquivos que precisam ser
  atualizados em consequência (ex: docker-compose.yml após Fix 2)
- Não introduzir novas dependências além das já listadas nos
  requirements.txt existentes