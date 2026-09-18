#!/usr/bin/env bash
# Sobe o par que forma uma réplica do COTTON-NET:
#   - cottonhs (Go): participa do consenso HotStuff com as outras réplicas;
#   - uvicorn (Python): API do coordinator, que propõe ao daemon e recebe os
#     commits de volta no /apply.
#
# Os dois vivem e morrem juntos: se um cair, o container cai e o Swarm reinicia
# o par. Meia réplica de pé seria pior que nenhuma — um daemon sem API pararia
# de aplicar no Indy, e uma API sem daemon não ordenaria nada.
set -euo pipefail

: "${NODE_NUM:?NODE_NUM é obrigatório (id desta réplica, 1..n)}"
HOTSTUFF_DIR="${HOTSTUFF_DIR:-/run/hotstuff}"   # chaves + cluster.json (docker config)
HOTSTUFF_LISTEN="${HOTSTUFF_LISTEN:-0.0.0.0}"   # bind local; o discável vem do cluster.json
API_PORT="${API_PORT:-8000}"

if [[ ! -f "${HOTSTUFF_DIR}/cluster.json" ]]; then
    echo "[entrypoint] ERRO: ${HOTSTUFF_DIR}/cluster.json não encontrado." >&2
    echo "[entrypoint] Gere com: cottonhs keygen -n <N> -hosts coordinator-1,... " >&2
    exit 1
fi

echo "[entrypoint] cottonhs réplica ${NODE_NUM} | dir=${HOTSTUFF_DIR} listen=${HOTSTUFF_LISTEN}"
cottonhs replica -id "${NODE_NUM}" -dir "${HOTSTUFF_DIR}" -listen "${HOTSTUFF_LISTEN}" &
pid_hs=$!

echo "[entrypoint] uvicorn | porta=${API_PORT}"
uvicorn main:app --host 0.0.0.0 --port "${API_PORT}" &
pid_api=$!

encerrar() {
    echo "[entrypoint] sinal recebido; encerrando o par"
    kill -TERM "${pid_hs}" "${pid_api}" 2>/dev/null || true
}
trap encerrar TERM INT

wait -n "${pid_hs}" "${pid_api}"
codigo=$?
echo "[entrypoint] um dos processos saiu (código=${codigo}); derrubando o container"
kill -TERM "${pid_hs}" "${pid_api}" 2>/dev/null || true
wait 2>/dev/null || true
exit "${codigo}"
