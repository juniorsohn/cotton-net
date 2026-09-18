# Demo do spike HotStuff — para rodar na mão

Objetivo: **ver o HotStuff ordenando NYMs de verdade**, sem suíte automatizada, um
comando por vez. Nada aqui toca o COTTON-NET; é tudo local, em `demo/.run/`.

O cluster tem 4 réplicas HotStuff (Go) + 4 appliers Python. Cada applier faz o papel
do caminho `FSM → _submit_nym` do coordinator: recebe o comando comitado e grava.
Os NYMs são objetos `NymLogEntry` **reais** do projeto — não é mock de formato.

## Roteiro

```bash
cd cotton-net/spikes/hotstuff/demo

./00_build.sh              # compila o daemon Go (só precisa uma vez)
./01_up.sh                 # sobe 4 réplicas + 4 appliers
./02_nym.sh alice          # propõe UMA NYM e mostra onde ela foi parar
./04_lote.sh 20            # propõe 20 NYMs e confere que todas convergiram
./03_status.sh             # só olha o estado, não muda nada
./09_down.sh               # derruba tudo
```

## O que olhar em cada saída

A tabela é o coração da demo:

```
  réplica  estado    aplicadas  hash (12)     pendentes  no-ops
  1        viva      1          579b5c24640c  0          4
```

- **aplicadas** — quantos comandos aquela réplica já executou.
- **hash** — sha256 acumulado de tudo que ela executou, *na ordem*. Se as 4 réplicas
  mostram o mesmo hash, elas concordam sobre o conteúdo **e** sobre a ordem. É a
  prova de consenso: um número diferente em uma réplica seria divergência.
- **no-ops** — comandos vazios que o daemon injeta (veja "a armadilha" abaixo).

Depois da tabela vêm dois vereditos: hash igual entre réplicas, e hash do daemon Go
igual ao hash do applier Python (prova que a fronteira Go→Python não perdeu nem
reordenou nada). E o `02_nym.sh` ainda mostra a linha que cada applier gravou.

## A armadilha que o spike descobriu — e o conserto

Rodando isto pela primeira vez, uma NYM sozinha **nunca comitava**. Eram dois
defeitos empilhados:

1. **Off-by-one na fila de comandos** (`relab/replica/cmdcache.go`): quem insere
   avisa quando a fila chega a `batchSize`, mas quem lê esperava passar de
   `batchSize`. Com lote 1, uma NYM sozinha nunca saía da fila — e com lote maior
   sempre sobrava uma para trás.
2. **A 3-cadeia**: o chained HotStuff só executa um bloco depois que três sucessores
   são empilhados sobre ele, e sem tráfego novo não há sucessores.

O contorno antigo era injetar no-ops (a coluna "no-ops" na tabela). O conserto atual
é o líder **propor bloco vazio** enquanto houver comando não comitado na cadeia —
e parar assim que ele comita. Para ver o antes e o depois:

```bash
EMPTY=false ./01_up.sh     # comportamento original do relab
./02_nym.sh presa          # HTTP 504, "aplicadas" fica em 0 nas quatro
./09_down.sh

./01_up.sh                 # com bloco vazio (padrão)
./02_nym.sh solta          # HTTP 200 em ~20 ms, aplicada nas quatro
```

Com `LOGLEVEL=debug` dá para ver a cadeia inteira em `.run/replica-1.log`:
um bloco com a NYM, três vazios, `DECIDE`, `EXEC` — e aí silêncio.

## Variáveis (prefixo na linha de comando)

| var | padrão | para quê |
|---|---|---|
| `N` | 4 | nº de réplicas (BFT precisa de 3f+1: 4 tolera 1 falha) |
| `BASE` | 34000 | base das portas (http da réplica i = BASE+300+i) |
| `EMPTY` | true | líder propõe bloco vazio p/ fechar a cadeia; `false` = relab original |
| `FILLER` | 0s | no-ops (contorno antigo); só faz sentido com `EMPTY=false` |
| `LOGLEVEL` | info | `debug` mostra o protocolo por dentro em `.run/replica-N.log` |

Ex.: `LOGLEVEL=debug ./01_up.sh` e depois `./05_log.sh 1 50`.

## Onde fica o quê

- `_tool.py` — toda a lógica (HTTP + tabela). Os `.sh` são invólucros de 5 linhas.
- `.run/` — config, chaves, logs e os `.jsonl` de cada applier. Apagado a cada `01_up.sh`.
- `../relab/cmd/cottonhs/main.go` — o daemon: `keygen`, `replica`, `/propose`, `/status`.
- `../applier_stub.py` — o applier Python.

## Ainda não coberto

Injeção de falhas (matar réplica e continuar comitando) — é o passo seguinte,
depois que este baseline estiver de pé na sua mão.
