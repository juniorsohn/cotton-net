#!/usr/bin/env bash
# gen_cottonnet_stack.sh — Gera docker-stack-cottonnet.yml para COTTON-NET distribuído
#
# Cada super-nó tem um genesis INDEPENDENTE com K_n nós distribuídos pelas baias.
# Como múltiplos super-nós colocam "node 1" na mesma baia física, usamos um
# PORT_OFFSET por super-nó para evitar conflito de portas no host.
#
#   S_i PORT_OFFSET = (i-1) * K_n * 2
#   S1: node1=9701, node2=9703 ...      (offset=0)
#   S2: node1=9709, node2=9711 ...      (offset=8 para K_n=4)
#   S3: node1=9717 ...                  (offset=16)
#   S4: node1=9725 ...                  (offset=24)
#
# Distribuição dos nós de cada super-nó pelas baias (igual ao CT):
#   K_n=4 → 1 nó por baia: flores corisco baiacu pernambuco
#   K_n=8 → 2 nós por baia: flores×2 corisco×2 baiacu×2 pernambuco×2
#
# Uso:
#   ./scripts/gen_cottonnet_stack.sh [TOTAL_NODES] [SUPERNODOS]
#
# Exemplos:
#   ./scripts/gen_cottonnet_stack.sh 16 4   # K_n=4, S_n=4
#   ./scripts/gen_cottonnet_stack.sh 32 4   # K_n=8, S_n=4

set -euo pipefail

# ── Parâmetros ────────────────────────────────────────────────────────────────

TOTAL_NODES=${1:-16}
SUPERNODOS=${2:-4}
MACHINES=4
KN=$(( TOTAL_NODES / SUPERNODOS ))
NPM=$(( KN / MACHINES ))   # nós por baia por super-nó

# ── Validações ────────────────────────────────────────────────────────────────

if (( TOTAL_NODES % SUPERNODOS != 0 )); then
    echo "❌ TOTAL_NODES=${TOTAL_NODES} deve ser divisível por SUPERNODOS=${SUPERNODOS}."
    exit 1
fi
if (( KN < 4 )); then
    echo "❌ K_n=${KN} < 4. RBFT exige mínimo 4 nós por super-nó."
    exit 1
fi
if (( KN % MACHINES != 0 )); then
    echo "❌ K_n=${KN} deve ser divisível por ${MACHINES} (número de baias)."
    exit 1
fi
if (( SUPERNODOS > MACHINES )); then
    echo "❌ SUPERNODOS=${SUPERNODOS} > ${MACHINES}. Não há baias suficientes para os coordinators."
    exit 1
fi

# ── Topologia das baias ───────────────────────────────────────────────────────

HOSTS=(flores corisco baiacu pernambuco)
IPS=(10.10.20.151 10.10.20.152 10.10.20.153 10.10.20.154)
CONTROL_HOST=cacao
CONTROL_IP=10.10.20.155

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="${SCRIPT_DIR}/../docker-stack-cottonnet.yml"

# ── IPS_LIST para o genesis de cada super-nó ─────────────────────────────────
# Todos os super-nós usam a mesma distribuição: NPM nós por baia.
# Ex K_n=4: "151,152,153,154"   Ex K_n=8: "151,151,152,152,153,153,154,154"

IPS_LIST=""
for m in $(seq 0 $(( MACHINES - 1 ))); do
    for _ in $(seq 1 $NPM); do
        IPS_LIST="${IPS_LIST}${IPS[$m]},"
    done
done
IPS_LIST="${IPS_LIST%,}"

echo "╔══════════════════════════════════════════════════════╗"
echo "║     COTTON-NET Distribuído — Configuração            ║"
echo "╠══════════════════════════════════════════════════════╣"
printf "║  Total de nós:            %-26s║\n" "${TOTAL_NODES}"
printf "║  Super-nós (S_n):         %-26s║\n" "${SUPERNODOS}"
printf "║  Nós por super-nó (K_n):  %-26s║\n" "${KN}"
printf "║  Nós por baia/super-nó:   %-26s║\n" "${NPM}"
printf "║  IPS por genesis:         %-26s║\n" "${IPS_LIST}"
echo "╠══════════════════════════════════════════════════════╣"
for s in $(seq 1 $SUPERNODOS); do
    PORT_OFFSET=$(( (s - 1) * KN * 2 ))
    p_start=$(( 9701 + PORT_OFFSET ))
    p_end=$(( 9700 + KN * 2 + PORT_OFFSET ))
    printf "║  S%d  offset=%-4d  portas %-5d–%-5d  baia: %-8s║\n" \
        "$s" "$PORT_OFFSET" "$p_start" "$p_end" "${HOSTS[$((s-1))]}"
done
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Cria Docker configs por super-nó ─────────────────────────────────────────
# Dois configs por super-nó:
#   cn-gen-tx-sn${s}-kn${KN}    → /home/indy/bin/von_generate_transactions
#   cn-start-node-sn${s}-kn${KN} → /home/indy/scripts/start_node.sh

for s in $(seq 1 $SUPERNODOS); do
    PORT_OFFSET=$(( (s - 1) * KN * 2 ))
    CONFIG_GEN="cn-gen-tx-sn${s}-kn${KN}"
    CONFIG_START="cn-start-node-sn${s}-kn${KN}"

    # ── Config 1: von_generate_transactions ──────────────────────────────────
    # Gera genesis independente com K_n nós e aplica PORT_OFFSET nas portas.

    GEN_TX=$(cat <<GENSCRIPT
#!/bin/bash
# von_generate_transactions — COTTON-NET S${s} (K_n=${KN}, offset=${PORT_OFFSET})
# Genesis independente: ${KN} nós distribuídos pelas baias.
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

ipsArg="${IPS_LIST}"

echo "Gerando genesis | S${s} nodes=${KN} offset=${PORT_OFFSET} ips=\${ipsArg}"

if [ -n "\${nodeNum:-}" ]; then
    generate_indy_pool_transactions --nodes ${KN} --clients 0 --nodeNum "\$nodeNum" --ips "\$ipsArg"
else
    generate_indy_pool_transactions --nodes ${KN} --clients 0 --ips "\$ipsArg"
fi
GENSCRIPT
)

    # Adiciona patch de portas apenas quando offset > 0
    if (( PORT_OFFSET > 0 )); then
        GEN_TX="${GEN_TX}

python3 -c \"
import json
genesis = '/home/indy/ledger/sandbox/pool_transactions_genesis'
offset  = ${PORT_OFFSET}
with open(genesis) as f:
    lines = [l.strip() for l in f if l.strip()]
patched = []
for line in lines:
    txn = json.loads(line)
    # Formato von-network (ver=1)
    try:
        d = txn['txn']['data']['data']
        d['node_port']   += offset
        d['client_port'] += offset
        patched.append(json.dumps(txn))
        continue
    except (KeyError, TypeError):
        pass
    # Formato legado
    try:
        d = txn['data']
        d['node_port']   += offset
        d['client_port'] += offset
    except (KeyError, TypeError):
        pass
    patched.append(json.dumps(txn))
with open(genesis, 'w') as f:
    f.write('\n'.join(patched) + '\n')
print('Genesis ports patched +${PORT_OFFSET}')
\""
    fi

    # ── Config 2: start_node.sh ───────────────────────────────────────────────
    # start_node.sh padrão calcula porta como 9700 + NODE_NUM*2 - 1.
    # Injetamos PORT_OFFSET para que cada super-nó use um intervalo exclusivo.

    START_NODE=$(cat <<STARTSCRIPT
#!/bin/bash
# start_node.sh — COTTON-NET S${s} (K_n=${KN}, offset=${PORT_OFFSET})
set -e

NODE_NUM=\${1:-\${NODE_NUM:-1}}
PORT_OFFSET=${PORT_OFFSET}
MY_IP=\$(hostname -I | awk '{print \$1}')
export IP=\${IP:-\$MY_IP}

NODE_PORT=\$(( 9700 + NODE_NUM * 2 - 1 + PORT_OFFSET ))
CLIENT_PORT=\$(( 9700 + NODE_NUM * 2 + PORT_OFFSET ))

if [ ! -d "/home/indy/ledger/sandbox/keys" ]; then
    echo "Gerando genesis | S${s} Node\${NODE_NUM} offset=${PORT_OFFSET}..."
    HOST="\$IP" /home/indy/bin/von_generate_transactions -n "\${NODE_NUM}" -i "\$IP"
fi

echo "Iniciando Node\${NODE_NUM} | \$IP:\${NODE_PORT} (client:\${CLIENT_PORT})"
exec start_indy_node "Node\${NODE_NUM}" "0.0.0.0" "\${NODE_PORT}" "0.0.0.0" "\${CLIENT_PORT}"
STARTSCRIPT
)

    # Recria configs no Swarm (imutáveis — remove e recria se existirem)
    for cfg in "$CONFIG_GEN" "$CONFIG_START"; do
        if docker config inspect "${cfg}" &>/dev/null 2>&1; then
            echo "⚠️  Config '${cfg}' já existe — recriando..."
            docker config rm "${cfg}"
        fi
    done

    printf '%s' "${GEN_TX}"    | docker config create "${CONFIG_GEN}"   -
    printf '%s' "${START_NODE}" | docker config create "${CONFIG_START}" -
    echo "✅ Configs criados: ${CONFIG_GEN}, ${CONFIG_START}"
done

echo ""

# ── Gera docker-stack-cottonnet.yml ──────────────────────────────────────────

{

cat <<HEADER
# COTTON-NET Distribuído — Docker Swarm Stack
#
# ${SUPERNODOS} super-nós independentes, K_n=${KN} nós cada, distribuídos pelas ${MACHINES} baias.
# Cada super-nó tem seu próprio genesis Indy; comunicação interna percorre a rede física.
# Gerado por: scripts/gen_cottonnet_stack.sh ${TOTAL_NODES} ${SUPERNODOS}
# Para regenerar: make cn-config NODES=${TOTAL_NODES} SUPERNODOS=${SUPERNODOS}
#
# Topologia:
HEADER

for s in $(seq 1 $SUPERNODOS); do
    PORT_OFFSET=$(( (s - 1) * KN * 2 ))
    coord_host="${HOSTS[$((s-1))]}"
    node_list=""
    for n in $(seq 1 $KN); do
        baia_idx=$(( (n - 1) / NPM ))
        node_list="${node_list} node${n}@${HOSTS[$baia_idx]}"
    done
    printf "#   S%d (%s, offset=%d):%s\n" "$s" "$coord_host" "$PORT_OFFSET" "$node_list"
done
echo "#   ${CONTROL_HOST}: cottonclient + prometheus + grafana"

cat <<PREAMBLE

version: '3.9'

networks:
  cotton-overlay:
    driver: overlay
    attachable: true
PREAMBLE

# ── Configs ───────────────────────────────────────────────────────────────────
echo ""
echo "configs:"
for s in $(seq 1 $SUPERNODOS); do
    echo "  cn-gen-tx-sn${s}-kn${KN}:"
    echo "    external: true"
    echo "  cn-start-node-sn${s}-kn${KN}:"
    echo "    external: true"
done

# ── Volumes ───────────────────────────────────────────────────────────────────
echo ""
echo "volumes:"
echo "  client-output:"
echo "  client-wallets:"
echo "  prometheus-data:"
echo "  grafana-data:"
for s in $(seq 1 $SUPERNODOS); do
    echo "  coordinator-${s}-wallets:"
    echo "  coordinator-${s}-raft:"
    echo "  coordinator-${s}-output:"
    echo "  webserver-sn${s}-cli:"
    echo "  webserver-sn${s}-ledger:"
    for n in $(seq 1 $KN); do
        echo "  cn-sn${s}-node${n}-data:"
    done
done

echo ""
echo "services:"

# ── Por super-nó: nós Indy + webserver + coordinator ─────────────────────────
for s in $(seq 1 $SUPERNODOS); do
    PORT_OFFSET=$(( (s - 1) * KN * 2 ))
    COORD_HOST="${HOSTS[$((s-1))]}"
    COORD_IP="${IPS[$((s-1))]}"
    CONFIG_GEN="cn-gen-tx-sn${s}-kn${KN}"
    CONFIG_START="cn-start-node-sn${s}-kn${KN}"

    RAFT_PEERS=""
    for other in $(seq 1 $SUPERNODOS); do
        if (( other != s )); then
            RAFT_PEERS="${RAFT_PEERS}coordinator-${other}:60061,"
        fi
    done
    RAFT_PEERS="${RAFT_PEERS%,}"

    echo ""
    echo "  # ════════════════════════════════════════════════════════════════════"
    echo "  # Super-nó S${s} | K_n=${KN} | genesis independente | coordinator: ${COORD_HOST}"
    echo "  # ════════════════════════════════════════════════════════════════════"

    # ── Webserver de S_s ──────────────────────────────────────────────────────
    cat <<WS

  webserver-sn${s}:
    image: von-network-base
    command: bash -c 'sleep 30 && ./scripts/start_webserver.sh'
    environment:
      - IPS=${IPS_LIST}
      - LOG_LEVEL=WARNING
      - RUST_LOG=warning
      - LEDGER_SEED=000000000000000000000000Trustee1
      - REGISTER_NEW_DIDS=True
      - LEDGER_INSTANCE_NAME=cotton-net-sn${s}-kn${KN}
      - MAX_FETCH=50000
      - RESYNC_TIME=120
      - POOL_CONNECTION_ATTEMPTS=10
      - POOL_CONNECTION_DELAY=10
    ports:
      - target: 8000
        published: 9000
        protocol: tcp
        mode: host
    networks: [cotton-overlay]
    deploy:
      replicas: 1
      placement:
        constraints: [node.hostname == ${COORD_HOST}]
      restart_policy:
        condition: on-failure
        delay: 15s
        max_attempts: 5
    volumes:
      - webserver-sn${s}-cli:/home/indy/.indy-cli
      - webserver-sn${s}-ledger:/home/indy/ledger
    configs:
      - source: ${CONFIG_GEN}
        target: /home/indy/bin/von_generate_transactions
        mode: 0755
WS

    # ── Nós Indy de S_s ───────────────────────────────────────────────────────
    for n in $(seq 1 $KN); do
        baia_idx=$(( (n - 1) / NPM ))
        host="${HOSTS[$baia_idx]}"
        p1=$(( 9700 + n * 2 - 1 + PORT_OFFSET ))
        p2=$(( 9700 + n * 2     + PORT_OFFSET ))

        cat <<NODE

  cn-sn${s}-node${n}:
    image: von-network-base
    command: ./scripts/start_node.sh ${n}
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
    networks: [cotton-overlay]
    deploy:
      replicas: 1
      placement:
        constraints: [node.hostname == ${host}]
      restart_policy:
        condition: on-failure
        delay: 10s
        max_attempts: 5
    volumes:
      - cn-sn${s}-node${n}-data:/home/indy/ledger
    configs:
      - source: ${CONFIG_GEN}
        target: /home/indy/bin/von_generate_transactions
        mode: 0755
      - source: ${CONFIG_START}
        target: /home/indy/scripts/start_node.sh
        mode: 0755
NODE
    done

    # ── Coordinator de S_s ────────────────────────────────────────────────────
    cat <<COORD

  coordinator-${s}:
    image: \${REGISTRY:-localhost:5000}/cottontrust-coordinator:latest
    deploy:
      replicas: 1
      placement:
        constraints: [node.hostname == ${COORD_HOST}]
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
      resources:
        limits: {cpus: '2', memory: 1G}
    environment:
      NODE_ID:      "node-${s}"
      NODE_NUM:     "${s}"
      RAFT_ADDR:    "0.0.0.0:60061"
      RAFT_PEERS:   "${RAFT_PEERS}"
      GENESIS_URL:  "http://${COORD_IP}:9000/genesis"
      TRUSTEE_DID:  "\${TRUSTEE_DID:-V4SGRU86Z58d6TV7PBUe6f}"
      TRUSTEE_SEED: "\${TRUSTEE_SEED:-000000000000000000000000Trustee1}"
      WALLET_KEY:   "\${WALLET_KEY:-7h3gFmD4QZdGdzt2NDtTg3XZwXFENBa1ogAgwHBxHNpw}"
      LOG_LEVEL:    "\${LOG_LEVEL:-INFO}"
    ports:
      - "$(( 8000 + s )):8000"
      - "6006${s}:60061"
    networks: [cotton-overlay]
    volumes:
      - coordinator-${s}-wallets:/app/wallets
      - coordinator-${s}-raft:/app/raft-data
      - coordinator-${s}-output:/app/output
COORD

done

# ── Cottonclient ──────────────────────────────────────────────────────────────
# COORDINATOR_URL preenchido → modo COTTON-NET via RAFT.
# GENESIS_URL → webserver do S1 (para inicializar wallet; o coordinator
# gerencia o consenso de escrita).

cat <<CLIENT

  # ── Cottonclient ─────────────────────────────────────────────────────────────
  cottonclient:
    image: \${REGISTRY:-localhost:5000}/cottontrust-client:latest
    deploy:
      replicas: 0
      placement:
        constraints: [node.hostname == ${CONTROL_HOST}]
      restart_policy:
        condition: on-failure
    environment:
      GENESIS_URL:      "http://${IPS[0]}:9000/genesis"
      TRUSTEE_DID:      "\${TRUSTEE_DID:-V4SGRU86Z58d6TV7PBUe6f}"
      TRUSTEE_SEED:     "\${TRUSTEE_SEED:-000000000000000000000000Trustee1}"
      WALLET_KEY:       "\${WALLET_KEY:-7h3gFmD4QZdGdzt2NDtTg3XZwXFENBa1ogAgwHBxHNpw}"
      LOG_LEVEL:        "\${LOG_LEVEL:-INFO}"
      COORDINATOR_URL:  "\${COORDINATOR_URL:-http://coordinator-1:8000}"
      DATA_DIR:         "/app/data"
      CONCURRENCY:      "\${CONCURRENCY:-1}"
      METRICS_OUTPUT:   "/app/output/raw_tx_metrics.csv"
    networks: [cotton-overlay]
    volumes:
      - client-output:/app/output
      - client-wallets:/app/wallets
      - \${DATA_DIR:-/mnt/prj/g11718038933/cotton-net_2026/data}:/app/data:ro
CLIENT

# ── Monitoramento ─────────────────────────────────────────────────────────────

cat <<MONITORING

  # ── Monitoramento ─────────────────────────────────────────────────────────────

  node-exporter:
    image: prom/node-exporter:v1.8.2
    deploy:
      mode: global
      resources:
        limits: {cpus: '0.2', memory: 64M}
    command:
      - '--path.procfs=/host/proc'
      - '--path.rootfs=/rootfs'
      - '--path.sysfs=/host/sys'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    ports:
      - "9100:9100"
    networks: [cotton-overlay]

  prometheus:
    image: prom/prometheus:v2.53.4
    deploy:
      replicas: 1
      placement:
        constraints: [node.hostname == ${CONTROL_HOST}]
      resources:
        limits: {cpus: '1', memory: 512M}
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
      - '--web.enable-lifecycle'
    ports:
      - "9091:9090"
    networks: [cotton-overlay]
    volumes:
      - prometheus-data:/prometheus

  grafana:
    image: grafana/grafana:12.0.0
    deploy:
      replicas: 1
      placement:
        constraints: [node.hostname == ${CONTROL_HOST}]
      resources:
        limits: {cpus: '1', memory: 512M}
    environment:
      GF_SECURITY_ADMIN_USER:     "admin"
      GF_SECURITY_ADMIN_PASSWORD: "\${GRAFANA_PASSWORD:-cottontrust}"
      GF_USERS_ALLOW_SIGN_UP:     "false"
    ports:
      - "3002:3000"
    networks: [cotton-overlay]
    volumes:
      - grafana-data:/var/lib/grafana

  indy-exporter:
    image: \${REGISTRY:-localhost:5000}/indy-exporter:latest
    deploy:
      replicas: 1
      placement:
        constraints: [node.hostname == ${CONTROL_HOST}]
      restart_policy:
        condition: on-failure
        delay: 15s
      resources:
        limits: {cpus: '0.2', memory: 128M}
    environment:
      GENESIS_URL:     "http://${IPS[0]}:9000/genesis"
      TRUSTEE_DID:     "\${TRUSTEE_DID:-V4SGRU86Z58d6TV7PBUe6f}"
      TRUSTEE_SEED:    "\${TRUSTEE_SEED:-000000000000000000000000Trustee1}"
      SCRAPE_INTERVAL: "30"
      SUBMIT_TIMEOUT:  "15"
      LOG_LEVEL:       "\${LOG_LEVEL:-INFO}"
    ports:
      - "9309:9309"
    networks: [cotton-overlay]
MONITORING

} > "${OUTPUT}"

echo "✅ Gerado: $(realpath "${OUTPUT}")"
echo ""
echo "Próximos passos:"
echo "   make cn-deploy NODES=${TOTAL_NODES} SUPERNODOS=${SUPERNODOS}"
echo "   make cn-genesis    # aguarda os 4 webservers subirem"
echo "   make cn-client-start"
echo ""
echo "Portas por baia:"
for m in $(seq 0 $(( MACHINES - 1 ))); do
    line="${HOSTS[$m]}:"
    for s in $(seq 1 $SUPERNODOS); do
        PORT_OFFSET=$(( (s - 1) * KN * 2 ))
        for n in $(seq 1 $KN); do
            baia_idx=$(( (n - 1) / NPM ))
            if (( baia_idx == m )); then
                p1=$(( 9700 + n * 2 - 1 + PORT_OFFSET ))
                line="${line} S${s}n${n}:${p1}"
            fi
        done
    done
    echo "   ${line}"
done
