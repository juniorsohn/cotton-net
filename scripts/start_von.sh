#!/usr/bin/env bash
# von-start.sh — Inicia VON Network em cada supernodo via SSH
#
# Uso:
#   ./scripts/von-start.sh [TOTAL_NODES] [SUPERNODOS]
#
# Exemplos:
#   ./scripts/von-start.sh 32 4    # 4 supernodos, 8 nós cada
#   ./scripts/von-start.sh 100 4   # 4 supernodos, 25 nós cada
#   ./scripts/von-start.sh 8       # 4 supernodos (padrão), 2 nós cada
#
# Requisitos:
#   - SSH configurado para baia1..baia4 sem senha (chave pública)
#   - von-network clonado em $VON_DIR em cada máquina
#   - Usuário $SSH_USER com permissão de executar ./manage

set -euo pipefail

# ── Parâmetros ────────────────────────────────────────────────────────────────

TOTAL_NODES=${1:-32}
SUPERNODOS=${2:-4}
KN=$(( TOTAL_NODES / SUPERNODOS ))

SSH_USER="${SSH_USER:-indy}"
VON_DIR="${VON_DIR:-/home/indy/von-network}"
MACHINES=("baia1" "baia2" "baia3" "baia4")
GENESIS_PORT="${GENESIS_PORT:-9000}"
GENESIS_TIMEOUT="${GENESIS_TIMEOUT:-120}"  # segundos esperando o genesis

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

# ── Início ────────────────────────────────────────────────────────────────────

echo "╔══════════════════════════════════════════════════════╗"
echo "║         COTTON-NET — VON Network Setup               ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Total de nós:    $TOTAL_NODES"
echo "║  Supernodos (Sn): $SUPERNODOS"
echo "║  Nós por Sn (Kn): $KN"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Para instâncias anteriores (limpeza) ─────────────────────────────────────

echo "🛑 Parando instâncias anteriores do VON Network..."
for i in $(seq 0 $(( SUPERNODOS - 1 ))); do
    MACHINE="${MACHINES[$i]}"
    SN=$(( i + 1 ))
    echo "   S$SN → $MACHINE"
    ssh "${SSH_USER}@${MACHINE}" \
        "cd ${VON_DIR} && ./manage stop 2>/dev/null || true" &
done
wait
echo ""

# ── Inicia cada supernodo em paralelo ────────────────────────────────────────

echo "🚀 Iniciando supernodos..."
for i in $(seq 0 $(( SUPERNODOS - 1 ))); do
    MACHINE="${MACHINES[$i]}"
    SN=$(( i + 1 ))

    echo "   S$SN → $MACHINE (${KN} nós Indy)..."
    ssh "${SSH_USER}@${MACHINE}" \
        "cd ${VON_DIR} && ./manage start --nodes ${KN} 2>&1 | tail -5" &
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

    printf "   S$SN ($URL) "
    until curl -sf "${URL}" > /dev/null 2>&1; do
        if (( ELAPSED >= GENESIS_TIMEOUT )); then
            echo "❌ timeout após ${GENESIS_TIMEOUT}s"
            FAILED=$(( FAILED + 1 ))
            break
        fi
        printf "."
        sleep 3
        ELAPSED=$(( ELAPSED + 3 ))
    done

    if curl -sf "${URL}" > /dev/null 2>&1; then
        echo " ✅"
    fi
done

echo ""

# ── Resultado ────────────────────────────────────────────────────────────────

if (( FAILED > 0 )); then
    echo "⚠️  $FAILED supernodo(s) não responderam no tempo esperado."
    echo "   Verifique os logs: ssh indy@baiaX 'cd ${VON_DIR} && ./manage logs'"
    exit 1
fi

echo "✅ Todos os $SUPERNODOS supernodos prontos!"
echo ""
echo "Genesis endpoints:"
for i in $(seq 0 $(( SUPERNODOS - 1 ))); do
    MACHINE="${MACHINES[$i]}"
    SN=$(( i + 1 ))
    echo "   S$SN: http://${MACHINE}:${GENESIS_PORT}/genesis"
done
echo ""
echo "Próximo passo: make deploy"