#!/usr/bin/env bash
# gen_cottontrust_stack.sh — Gera docker-stack-cottontrust.yml para COTTONTRUST distribuído
#
# Distribui TOTAL_NODES nodos Indy entre 4 máquinas físicas usando Docker Swarm.
# Não modifica o diretório von-network: usa Docker configs para injetar o script
# von_generate_transactions customizado nos containers em runtime.
#
# Uso:
#   ./scripts/gen_cottontrust_stack.sh [TOTAL_NODES]
#
# Exemplos:
#   ./scripts/gen_cottontrust_stack.sh 4    # 1 nó por máquina (mínimo RBFT)
#   ./scripts/gen_cottontrust_stack.sh 16   # 4 nós por máquina
#   ./scripts/gen_cottontrust_stack.sh 32   # 8 nós por máquina
#
# Requisitos:
#   - TOTAL_NODES deve ser divisível por 4 (número de baias ativas)
#   - Mínimo: 4 nós (RBFT exige f=1 → 3f+1=4)
#   - Docker Swarm ativo (docker swarm init já executado)

set -euo pipefail

# ── Parâmetros ────────────────────────────────────────────────────────────────

TOTAL_NODES=${1:-16}
MACHINES=4
KN=$(( TOTAL_NODES / MACHINES ))

# ── Validações ────────────────────────────────────────────────────────────────

if (( TOTAL_NODES % MACHINES != 0 )); then
    echo "❌ TOTAL_NODES=${TOTAL_NODES} deve ser divisível por ${MACHINES} (baias ativas)."
    echo "   Tente: 4, 8, 12, 16, 20, 24, 28, 32..."
    exit 1
fi

if (( TOTAL_NODES < 4 )); then
    echo "❌ TOTAL_NODES=${TOTAL_NODES} < 4. RBFT exige mínimo 4 nós (f=1)."
    exit 1
fi

# ── Topologia fixa das baias ──────────────────────────────────────────────────
# Mesma topologia do docker-compose.yml principal (cotton-net)

HOSTS=(flores corisco baiacu pernambuco)
IPS=(10.10.20.151 10.10.20.152 10.10.20.153 10.10.20.154)
CONTROL_HOST=cacao
CONTROL_IP=10.10.20.155

# ── Constrói IPS_LIST: cada IP repetido KN vezes ──────────────────────────────
# Exemplo (KN=2): "10.10.20.151,10.10.20.151,10.10.20.152,10.10.20.152,..."
# O von_generate_transactions usa este CSV para mapear nó_i → IP_i.

IPS_LIST=""
for ip in "${IPS[@]}"; do
    for _ in $(seq 1 $KN); do
        IPS_LIST="${IPS_LIST}${ip},"
    done
done
IPS_LIST="${IPS_LIST%,}"

# ── Caminhos de saída ─────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="${SCRIPT_DIR}/../docker-stack-cottontrust.yml"
CONFIG_NAME="von-gen-tx-n${TOTAL_NODES}"

echo "╔══════════════════════════════════════════════════════╗"
echo "║      COTTONTRUST Distribuído — Configuração          ║"
echo "╠══════════════════════════════════════════════════════╣"
printf "║  Total de nós:     %-34s║\n" "${TOTAL_NODES}"
printf "║  Nós por máquina:  %-34s║\n" "${KN}"
printf "║  Faixa de portas:  %-34s║\n" "9701-$(( 9700 + TOTAL_NODES * 2 ))"
printf "║  Webserver/client: %-34s║\n" "${CONTROL_HOST} (${CONTROL_IP})"
printf "║  Config Swarm:     %-34s║\n" "${CONFIG_NAME}"
echo "╠══════════════════════════════════════════════════════╣"
for m in $(seq 0 $(( MACHINES - 1 ))); do
    start=$(( m * KN + 1 ))
    end=$(( (m + 1) * KN ))
    p_start=$(( 9700 + start * 2 - 1 ))
    p_end=$(( 9700 + end * 2 ))
    printf "║  %-10s nós %3d–%3d  portas %5d-%5d         ║\n" \
        "${HOSTS[$m]}" "$start" "$end" "$p_start" "$p_end"
done
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── 1. Cria Docker config com von_generate_transactions customizado ───────────
#
# O von_generate_transactions dentro da imagem von-network-base é hardcoded
# para --nodes 4. Sobrescrevemos via Docker config (montado em
# /usr/local/bin/von_generate_transactions) sem alterar a imagem ou o repo.
#
# As chaves do genesis são DETERMINÍSTICAS (derivadas do número do nó),
# então todos os containers geram o mesmo genesis independentemente — não
# é necessário compartilhar arquivo por NFS.

GEN_TX=$(cat <<GENSCRIPT
#!/bin/bash
# von_generate_transactions — Injetado via Docker Swarm config
# Gerado para ${TOTAL_NODES} nós. Não edite manualmente.
# Para regenerar: make ct-config NODES=${TOTAL_NODES}
set -e

rm -rf /var/lib/indy/*

options=':i:s:n:h'
while getopts \$options option; do
    case \$option in
        i  ) ipAddress=\$OPTARG ;;
        s  ) ipAddresses=\$OPTARG ;;
        n  ) nodeNum=\$OPTARG ;;
        h  ) exit 0 ;;
        \? ) echo "Opção desconhecida: -\$OPTARG" >&2; exit 1 ;;
        :  ) echo "Argumento ausente para -\$OPTARG" >&2; exit 1 ;;
    esac
done

if [ -n "\$ipAddresses" ]; then
    ipsArg="\$ipAddresses"
elif [ -n "\$ipAddress" ]; then
    ipsArg=\$(python3 -c "print(','.join(['\$ipAddress'] * ${TOTAL_NODES}))")
elif [ -n "\$DOCKERHOST" ]; then
    ipsArg=\$(python3 -c "print(','.join(['\$DOCKERHOST'] * ${TOTAL_NODES}))")
else
    echo "Erro: nenhum argumento de IP fornecido (-i, -s ou DOCKERHOST)." >&2
    exit 1
fi

echo "Gerando genesis | nodes=${TOTAL_NODES} ips=\${ipsArg}"
if [ -n "\$nodeNum" ]; then
    generate_indy_pool_transactions --nodes ${TOTAL_NODES} --clients 0 --nodeNum "\$nodeNum" --ips "\$ipsArg"
else
    generate_indy_pool_transactions --nodes ${TOTAL_NODES} --clients 0 --ips "\$ipsArg"
fi
GENSCRIPT
)

# Configs são imutáveis no Swarm — remove e recria se já existe
if docker config inspect "${CONFIG_NAME}" &>/dev/null 2>&1; then
    echo "⚠️  Config '${CONFIG_NAME}' já existe — recriando..."
    docker config rm "${CONFIG_NAME}"
fi
printf '%s' "${GEN_TX}" | docker config create "${CONFIG_NAME}" -
echo "✅ Docker config criado: ${CONFIG_NAME}"
echo ""

# ── 2. Gera docker-stack-cottontrust.yml ──────────────────────────────────────

{
cat <<HEADER
# COTTONTRUST Distribuído — Docker Swarm Stack
#
# ${TOTAL_NODES} nós Indy RBFT distribuídos em 4 máquinas físicas (${KN} por máquina).
# Gerado automaticamente por: scripts/gen_cottontrust_stack.sh ${TOTAL_NODES}
# Para regenerar: make ct-config NODES=${TOTAL_NODES}
#
# Distribuição:
HEADER

for m in $(seq 0 $(( MACHINES - 1 ))); do
    start=$(( m * KN + 1 ))
    end=$(( (m + 1) * KN ))
    echo "#   ${HOSTS[$m]} (${IPS[$m]}): nós ${start}–${end}"
done
echo "#   ${CONTROL_HOST} (${CONTROL_IP}): webserver (:9000) + cottonclient"

cat <<PREAMBLE

version: '3.9'

networks:
  von:
    driver: overlay
    attachable: true
    ipam:
      config:
        - subnet: 10.20.0.0/20   # /20 = 4094 IPs; /24 (default) esgota com 128 nós + churn de --force

configs:
  ${CONFIG_NAME}:
    external: true

volumes:
  webserver-cli:
  webserver-ledger:
  client-wallets:
PREAMBLE

for i in $(seq 1 $TOTAL_NODES); do
    echo "  node${i}-data:"
done

echo ""
echo "services:"

# ── Nós Indy ──────────────────────────────────────────────────────────────────
# Cada nó usa mode: host nos ports para que o RBFT inter-nó funcione via rede
# física (os peers se conectam ao IP real da máquina, não ao VIP do Swarm).

for i in $(seq 1 $TOTAL_NODES); do
    m=$(( (i - 1) / KN ))
    host="${HOSTS[$m]}"
    p1=$(( 9700 + i * 2 - 1 ))
    p2=$(( 9700 + i * 2 ))

cat <<NODE

  node${i}:
    image: von-network-base
    command: ./scripts/start_node.sh ${i}
    environment:
      - IPS=${IPS_LIST}
      - LOG_LEVEL=WARNING
      - RUST_LOG=warning
    ports:
      - target: ${p1}
        published: ${p1}
        protocol: tcp
        mode: host
      - target: ${p2}
        published: ${p2}
        protocol: tcp
        mode: host
    networks: [von]
    deploy:
      replicas: 1
      placement:
        constraints: [node.hostname == ${host}]
      restart_policy:
        condition: on-failure
        delay: 10s
        max_attempts: 5
    volumes:
      - node${i}-data:/home/indy/ledger
    configs:
      - source: ${CONFIG_NAME}
        target: /home/indy/bin/von_generate_transactions
        mode: 0755
NODE
done

# ── Webserver ─────────────────────────────────────────────────────────────────
# Serve o genesis em http://CONTROL_IP:9000/genesis e o explorador Indy.
# sleep 30 dá tempo para os nós levantarem antes do webserver tentar conectar.

cat <<WEBSERVER

  webserver:
    image: von-network-base
    command: bash -c 'sleep 30 && ./scripts/start_webserver.sh'
    environment:
      - IPS=${IPS_LIST}
      - LOG_LEVEL=WARNING
      - LEDGER_SEED=000000000000000000000000Trustee1
      - REGISTER_NEW_DIDS=True
      - LEDGER_INSTANCE_NAME=cottontrust-distributed-${TOTAL_NODES}n
      - MAX_FETCH=50000
      - RESYNC_TIME=120
      - POOL_CONNECTION_ATTEMPTS=10
      - POOL_CONNECTION_DELAY=10
    ports:
      - target: 8000
        published: 9000
        protocol: tcp
        mode: host
    networks: [von]
    deploy:
      replicas: 1
      placement:
        constraints: [node.hostname == ${CONTROL_HOST}]
      restart_policy:
        condition: on-failure
        delay: 15s
        max_attempts: 5
    volumes:
      - webserver-cli:/home/indy/.indy-cli
      - webserver-ledger:/home/indy/ledger
    configs:
      - source: ${CONFIG_NAME}
        target: /home/indy/bin/von_generate_transactions
        mode: 0755

WEBSERVER

# ── Cottonclient ──────────────────────────────────────────────────────────────
# replicas: 0 — inicia manualmente com: make ct-client-start
# COORDINATOR_URL vazio → modo direto (sem RAFT), Indy puro.
# GENESIS_URL aponta para o webserver no ${CONTROL_HOST}.

cat <<CLIENT
  cottonclient:
    image: \${REGISTRY:-localhost:5000}/cottontrust-client:latest
    deploy:
      replicas: 0
      placement:
        constraints: [node.hostname == ${CONTROL_HOST}]
      restart_policy:
        condition: on-failure
    environment:
      GENESIS_URL:     "http://${CONTROL_IP}:9000/genesis"
      TRUSTEE_DID:     "\${TRUSTEE_DID:-V4SGRU86Z58d6TV7PBUe6f}"
      TRUSTEE_SEED:    "\${TRUSTEE_SEED:-000000000000000000000000Trustee1}"
      WALLET_KEY:      "\${WALLET_KEY:-7h3gFmD4QZdGdzt2NDtTg3XZwXFENBa1ogAgwHBxHNpw}"
      LOG_LEVEL:       "\${LOG_LEVEL:-INFO}"
      COORDINATOR_URL: ""
      DATA_DIR:        "/app/data"
      CONCURRENCY:     "\${CONCURRENCY:-1}"
      METRICS_OUTPUT:  "/app/output/ct_n${TOTAL_NODES}.csv"
    networks: [von]
    volumes:
      - \${RESULTS_DIR:-/mnt/prj/g11718038933/cotton-net_2026/results}:/app/output
      - client-wallets:/app/wallets
      - \${DATA_DIR:-/mnt/prj/g11718038933/cotton-net_2026/data}:/app/data:ro
CLIENT

} > "${OUTPUT}"

echo "✅ Gerado: $(realpath "${OUTPUT}")"
echo ""
echo "Próximos passos:"
echo ""
echo "   make ct-deploy NODES=${TOTAL_NODES}"
echo "   make ct-status"
echo "   make ct-client-start"
echo ""
echo "IPS configurado (${TOTAL_NODES} entradas):"
echo "   ${IPS_LIST}" | fold -s -w 72 | sed 's/^/   /'
