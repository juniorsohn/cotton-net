#!/usr/bin/env bash
# start_von.sh — Inicia VON Network em cada supernodo via SSH
#
# Gera start_nodes.sh e .env dinamicamente para o Kn desejado,
# copia para cada baia, reconstrói a imagem e inicia em modo
# combinado (todos os nós num único container via supervisord).
#
# Uso:
#   ./scripts/start_von.sh [TOTAL_NODES] [SUPERNODOS]
#
# Exemplos:
#   ./scripts/start_von.sh 32 4    # 4 supernodos, 8 nós cada
#   ./scripts/start_von.sh 16 4    # 4 supernodos, 4 nós cada (mínimo)
#   ./scripts/start_von.sh 8       # 4 supernodos (padrão), 2 nós cada — inválido

set -euo pipefail

# ── Parâmetros ────────────────────────────────────────────────────────────────

TOTAL_NODES=${1:-32}
SUPERNODOS=${2:-4}
KN=$(( TOTAL_NODES / SUPERNODOS ))

SSH_USER="${SSH_USER:-indy}"
VON_DIR="${VON_DIR:-/home/indy/von-network}"
MACHINES=("baia1" "baia2" "baia3" "baia4")
GENESIS_PORT="${GENESIS_PORT:-9000}"
GENESIS_TIMEOUT="${GENESIS_TIMEOUT:-120}"

# ── Validações ────────────────────────────────────────────────────────────────

if (( KN < 4 )); then
    echo "❌ Erro: Kn=$KN nós por supernodo é insuficiente."
    echo "   O RBFT do Hyperledger Indy requer no mínimo 4 nós."
    echo "   Use TOTAL_NODES >= $((SUPERNODOS * 4))."
    exit 1
fi

if (( ${#MACHINES[@]} < SUPERNODOS )); then
    echo "❌ Erro: Mais supernodos ($SUPERNODOS) do que máquinas (${#MACHINES[@]})."
    exit 1
fi

# ── Banner ────────────────────────────────────────────────────────────────────

echo "╔══════════════════════════════════════════════════════╗"
echo "║         COTTON-NET — VON Network Setup               ║"
echo "╠══════════════════════════════════════════════════════╣"
printf "║  Total de nós:    %-35s║\n" "$TOTAL_NODES"
printf "║  Supernodos (Sn): %-35s║\n" "$SUPERNODOS"
printf "║  Nós por Sn (Kn): %-35s║\n" "$KN"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Geração do start_nodes.sh ─────────────────────────────────────────────────
#
# Gera o script de inicialização do supervisord para Kn nós.
# O arquivo é gerado localmente em /tmp e depois copiado para cada baia.
# $HOST e $BAIA_IP precisam ser avaliados dentro do container (runtime),
# por isso aparecem escapados (\$HOST) no arquivo gerado.

TMP_START_NODES=$(mktemp /tmp/start_nodes_kn${KN}.XXXXXX.sh)
trap "rm -f ${TMP_START_NODES}" EXIT

{
    cat <<'HEADER'
#!/bin/bash
set -e

HOST="${HOST:-0.0.0.0}"
START_PORT="9700"
HEADER

    # NODE_NUM: "1 2 3 ... KN"
    printf 'export NODE_NUM="'
    seq 1 "$KN" | tr '\n' ' ' | sed 's/ $//'
    printf '"\n\n'

    cat <<'LEDGER_CHECK'
if [ ! -d "/home/indy/ledger/sandbox/keys" ]; then
    echo "Ledger does not exist - Creating..."
    bash ./scripts/init_genesis.sh
fi

cat <<__SUPERVISORD__ > supervisord.conf
[supervisord]
logfile = /tmp/supervisord.log
logfile_maxbytes = 50MB
logfile_backups=10
loglevel = info
pidfile = /tmp/supervisord.pid
nodaemon = true
minfds = 1024
minprocs = 200
umask = 022
user = indy
identifier = supervisor
directory = /tmp
nocleanup = true
childlogdir = /tmp
strip_ansi = false

LEDGER_CHECK

    # Bloco [program:nodeX] para cada nó
    for i in $(seq 1 "$KN"); do
        PORT1=$(( 9700 + i * 2 - 1 ))
        PORT2=$(( 9700 + i * 2 ))
        printf '[program:node%d]\n' "$i"
        printf 'command=start_indy_node Node%d $HOST %d $HOST %d\n' "$i" "$PORT1" "$PORT2"
        printf 'directory=/home/indy\n'
        printf 'stdout_logfile=/tmp/node%d.log\n' "$i"
        printf 'stderr_logfile=/tmp/node%d.log\n' "$i"
        printf '\n'
    done

    # Seção printlogs: tail em todos os logs
    printf '[program:printlogs]\n'
    printf 'command=tail -F /tmp/supervisord.log'
    for i in $(seq 1 "$KN"); do
        printf ' /tmp/node%d.log' "$i"
    done
    printf '\nstdout_logfile=/dev/stdout\n'
    printf 'stdout_logfile_maxbytes=0\n'

    cat <<'FOOTER'
__SUPERVISORD__

echo "Starting $NODE_NUM indy nodes"
supervisord
FOOTER

} > "$TMP_START_NODES"
chmod +x "$TMP_START_NODES"

# ── Para instâncias anteriores ────────────────────────────────────────────────

echo "🛑 Parando instâncias anteriores do VON Network..."
for i in $(seq 0 $(( SUPERNODOS - 1 ))); do
    MACHINE="${MACHINES[$i]}"
    SN=$(( i + 1 ))
    echo "   S$SN → $MACHINE"
    ssh "${SSH_USER}@${MACHINE}" \
        "cd ${VON_DIR} && DOCKER_API_VERSION=1.41 ./manage down 2>/dev/null || true" &
done
wait
echo ""

# ── Configura e inicia cada supernodo em paralelo ─────────────────────────────

echo "🔧 Configurando e iniciando supernodos..."
for i in $(seq 0 $(( SUPERNODOS - 1 ))); do
    MACHINE="${MACHINES[$i]}"
    SN=$(( i + 1 ))
    (
        echo "   S$SN → $MACHINE: copiando configuração..."

        # IP da baia para o genesis
        BAIA_IP=$(ssh "${SSH_USER}@${MACHINE}" "hostname -I | awk '{print \$1}'")

        # IPS = IP repetido KN vezes (parâmetro do von_generate_transactions)
        IPS_VAL=$(for j in $(seq 1 "$KN"); do printf '%s,' "$BAIA_IP"; done | sed 's/,$//')

        # Copia start_nodes.sh gerado
        scp -q "$TMP_START_NODES" \
            "${SSH_USER}@${MACHINE}:${VON_DIR}/scripts/start_nodes.sh"

        # Escreve .env com IP local da baia
        ssh "${SSH_USER}@${MACHINE}" \
            "printf 'IP=%s\nIPS=%s\n' '${BAIA_IP}' '${IPS_VAL}' > ${VON_DIR}/.env"

        # Reconstrói imagem com o novo start_nodes.sh
        echo "   S$SN → $MACHINE: rebuild..."
        ssh "${SSH_USER}@${MACHINE}" \
            "cd ${VON_DIR} && DOCKER_API_VERSION=1.41 ./manage build 2>&1 | tail -2"

        # Inicia em modo combinado (todos os Kn nós num único container)
        echo "   S$SN → $MACHINE: start-combined..."
        ssh "${SSH_USER}@${MACHINE}" \
            "cd ${VON_DIR} && DOCKER_API_VERSION=1.41 ./manage start-combined 2>&1 | tail -2"

        echo "   S$SN → $MACHINE: ✅ iniciado"
    ) &
done
wait
echo ""

# ── Aguarda genesis de cada supernodo ────────────────────────────────────────

echo "⏳ Aguardando genesis endpoints..."
FAILED=0

for i in $(seq 0 $(( SUPERNODOS - 1 ))); do
    MACHINE="${MACHINES[$i]}"
    SN=$(( i + 1 ))
    URL="http://${MACHINE}:${GENESIS_PORT}/genesis"
    ELAPSED=0

    printf "   S$SN (%s) " "$URL"
    until curl -sf "$URL" > /dev/null 2>&1; do
        if (( ELAPSED >= GENESIS_TIMEOUT )); then
            echo "❌ timeout após ${GENESIS_TIMEOUT}s"
            FAILED=$(( FAILED + 1 ))
            break
        fi
        printf "."
        sleep 3
        ELAPSED=$(( ELAPSED + 3 ))
    done
    curl -sf "$URL" > /dev/null 2>&1 && echo " ✅"
done
echo ""

# ── Resultado ────────────────────────────────────────────────────────────────

if (( FAILED > 0 )); then
    echo "⚠️  $FAILED supernodo(s) não responderam no tempo esperado."
    echo "   Verifique: ssh indy@baiaX 'cd ${VON_DIR} && ./manage logs'"
    exit 1
fi

echo "✅ Todos os $SUPERNODOS supernodos prontos! (${KN} nós cada)"
echo ""
echo "Genesis endpoints:"
for i in $(seq 0 $(( SUPERNODOS - 1 ))); do
    echo "   S$(( i + 1 )): http://${MACHINES[$i]}:${GENESIS_PORT}/genesis"
done
echo ""
echo "Próximo passo: make deploy"
