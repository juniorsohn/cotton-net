# Patches no relab/hotstuff v0.5.0

O spike usa o `relab/hotstuff` com duas alterações. Elas vivem aqui porque `relab/`
é um clone do upstream — se ele for reclonado, reaplique:

```bash
cd relab
git apply ../patches/0001-onexec-hook.patch
git apply ../patches/0002-empty-blocks.patch
```

## 0001 — gancho de execução (`Config.OnExec`)

O plano original era plugar nosso executor pela API pública, e **não dá**: o
`replica.New` registra o servidor de cliente por último e o `Build()` inverte a
ordem, de modo que um `Executor` adicionado via `builder.Add` nunca é chamado.
O patch adiciona um callback opcional `OnExec` em `replica.Config`, chamado para
cada comando comitado, em ordem de execução. É por onde a NYM sai do Go para o
applier Python.

## 0002 — blocos vazios (liveness com pouco tráfego)

Conserta os dois defeitos que faziam uma NYM isolada nunca comitar:

- `replica/cmdcache.go` — o produtor sinaliza em `Len() >= batchSize` mas o consumidor
  esperava `Len() > batchSize`: off-by-one que deixava a última NYM presa na fila.
  Corrigido para `< batchSize`, e o `Get` agora libera **lote parcial** quando a view
  expira, em vez de não propor nada (batch timeout).
- `modules/options.go` — opção `ShouldProposeEmptyBlocks` (desligada por padrão, para
  não alterar o comportamento do relab nos benchmarks dele).
- `consensus/consensus.go` — com a opção ligada, se ainda houver bloco **com comandos**
  entre o último commit e o topo da cadeia, o líder propõe imediatamente (bloco vazio
  se a fila estiver vazia) em vez de esperar a view expirar. A varredura da cadeia é
  o freio: quando o último bloco com comandos comita, ela devolve false e a cadeia
  para de crescer.

Efeito medido (4 réplicas locais, chainedhotstuff+bls12): NYM isolada passou de
**nunca comitar** para ~20 ms; lote de 20 NYMs, mediana **75 ms → 37 ms**, porque os
no-ops deixaram de existir.
