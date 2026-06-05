#!/usr/bin/env bash
# swarm-init.sh — Inicializa Docker Swarm na Baía da Babitonga
#
# Deve ser executado uma vez antes do primeiro deploy.
# baia1 (flores) é o manager; baia2-5 são workers.
#
# Uso:
#   ./scripts/swarm-init.sh

set -euo pipefail

SSH_USER="${SSH_USER:-indy}"

# IPs lidos do Makefile via env ou defaults
IFS=' ' read -ra ALL_IPS   <<< "${BAIA_IPS:-10.10.20.151 10.10.20.152 10.10.20.153 10.10.20.154 10.10.20.155}"
IFS=' ' read -ra ALL_NAMES <<< "${BAIA_NAMES:-flores corisco baiacu pernambuco cacao}"

MANAGER_IP="${ALL_IPS[0]}"
MANAGER_NAME="${ALL_NAMES[0]}"
WORKER_IPS=("${ALL_IPS[@]:1}")

echo "🐝 Inicializando Docker Swarm..."
printf "   Manager: %s (%s)\n" "$MANAGER_NAME" "$MANAGER_IP"
printf "   Workers: %s\n" "${ALL_NAMES[*]:1}"
echo ""

# Inicializa o Swarm no manager e captura o token de join
JOIN_TOKEN=$(ssh "${SSH_USER}@${MANAGER_IP}" \
    "DOCKER_API_VERSION=1.41 docker swarm init --advertise-addr ${MANAGER_IP} 2>/dev/null || \
     DOCKER_API_VERSION=1.41 docker swarm join-token worker -q")

echo "   Token de join obtido."
echo ""

# Adiciona cada worker ao Swarm
for IP in "${WORKER_IPS[@]}"; do
    echo "   Adicionando ${IP} ao Swarm..."
    ssh "${SSH_USER}@${IP}" \
        "DOCKER_API_VERSION=1.41 docker swarm join --token ${JOIN_TOKEN} ${MANAGER_IP}:2377 2>/dev/null || \
         echo '   (já membro do Swarm)'"
done

echo ""
echo "✅ Swarm inicializado. Nós:"
ssh "${SSH_USER}@${MANAGER_IP}" "DOCKER_API_VERSION=1.41 docker node ls"
