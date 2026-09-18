#!/usr/bin/env bash
# Sobe o cluster: gera chaves/certificados, levanta N appliers Python e N réplicas HotStuff.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
[[ -x "$BIN" ]] || { echo "daemon não compilado — rode ./00_build.sh"; exit 1; }
"$DEMO/09_down.sh" >/dev/null 2>&1 || true
rm -rf "$RUN"; mkdir -p "$RUN"

echo "→ gerando chaves BLS12-381 + certificados TLS para $N réplicas"
"$BIN" keygen -n "$N" -dir "$RUN/cluster" -base-port "$BASE"

echo "→ subindo $N appliers Python (papel do FSM → _submit_nym do coordinator)"
for i in $(seq 1 "$N"); do
  nohup "$PY" "$SPIKE/applier_stub.py" --port $((BASE+400+i)) --out "$RUN/applier-$i.jsonl" \
    > "$RUN/applier-$i.log" 2>&1 & echo $! >> "$RUN/pids"
done
sleep 1

echo "→ subindo $N réplicas HotStuff (chainedhotstuff, bls12, bloco-vazio=$EMPTY, filler=$FILLER, log=$LOGLEVEL)"
for i in $(seq 1 "$N"); do
  nohup "$BIN" replica -id "$i" -dir "$RUN/cluster" -filler-interval "$FILLER" \
    -empty-blocks="$EMPTY" -propose-timeout 10s -log-level "$LOGLEVEL" > "$RUN/replica-$i.log" 2>&1 & echo $! >> "$RUN/pids"
done

echo "→ esperando as réplicas responderem /status"
tool esperar --timeout 60 || { echo "FALHA no boot — veja $RUN/replica-1.log"; exit 1; }
echo
tool table
echo
echo "cluster no ar. logs em $RUN/  |  próximo: ./02_nym.sh alice"
