#!/usr/bin/env bash
# swarm-init.sh — Inicializa Docker Swarm na Baía da Babitonga
#
# Deve ser executado uma vez antes do primeiro deploy.
# Assume que baia1 será o manager (nó principal do Swarm).
#
# Uso:
#   ./scripts/swarm-init.sh

set -euo pipefail

SSH_USER="${SSH_USER:-indy}"
MANAGER="baia1"
WORKERS=("baia2" "baia3" "baia4" "baia5")

echo "🐝 Inicializando Docker Swarm..."
echo "   Manager: $MANAGER"
echo "   Workers: ${WORKERS[*]}"
echo ""

# Inicializa o Swarm no manager e captura o token de join
MANAGER_IP=$(ssh "${SSH_USER}@${MANAGER}" "hostname -I | awk '{print \$1}'")
echo "   IP do manager: $MANAGER_IP"

JOIN_TOKEN=$(ssh "${SSH_USER}@${MANAGER}" \
    "docker swarm init --advertise-addr ${MANAGER_IP} 2>/dev/null || \
     docker swarm join-token worker -q")

echo "   Token de join obtido."
echo ""

# Adiciona cada worker ao Swarm
for WORKER in "${WORKERS[@]}"; do
    echo "   Adicionando $WORKER ao Swarm..."
    ssh "${SSH_USER}@${WORKER}" \
        "docker swarm join --token ${JOIN_TOKEN} ${MANAGER_IP}:2377 2>/dev/null || \
         echo '   (já membro do Swarm)'" 
done

echo ""
echo "✅ Swarm inicializado. Nós:"
ssh "${SSH_USER}@${MANAGER}" "docker node ls"