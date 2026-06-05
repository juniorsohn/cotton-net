#!/usr/bin/env bash
# von-stop.sh — Para VON Network em todos os supernodos
#
# Uso:
#   ./scripts/von-stop.sh

set -euo pipefail

SSH_USER="${SSH_USER:-indy}"
VON_DIR="${VON_DIR:-/home/indy/von-network}"
IFS=' ' read -ra MACHINES <<< "${BAIA_IPS:-10.10.20.151 10.10.20.152 10.10.20.153 10.10.20.154}"

echo "🛑 Parando VON Networks..."

for i in "${!MACHINES[@]}"; do
    MACHINE="${MACHINES[$i]}"
    SN=$(( i + 1 ))
    echo "   S$SN → $MACHINE"
    ssh "${SSH_USER}@${MACHINE}" \
        "cd ${VON_DIR} && DOCKER_API_VERSION=1.41 ./manage stop 2>/dev/null || true" &
done

wait
echo "✅ Todos os VON Networks parados."