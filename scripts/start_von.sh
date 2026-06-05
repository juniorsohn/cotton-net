#!/usr/bin/env bash
# start_von.sh — Configura o von-network compartilhado (NFS) para Kn nós
#
# Como todas as baias compartilham NFS, este script roda UMA VEZ em qualquer
# máquina e gera/atualiza três arquivos no VON_DIR:
#
#   scripts/start_nodes.sh  — genesis com NODE_NUM="1 2 ... Kn"
#   docker-compose.yml      — serviços node1..nodeN com portas corretas
#   von_local_start.sh      — script que cada baia roda localmente
#
# O manage é patchado para incluir todos os nós no comando start.
#
# Uso:
#   ./scripts/start_von.sh [TOTAL_NODES] [SUPERNODOS]
#
# Exemplos:
#   ./scripts/start_von.sh 32 4   # Kn=8
#   ./scripts/start_von.sh 16 4   # Kn=4 (mínimo RBFT)

set -euo pipefail

# ── Parâmetros ────────────────────────────────────────────────────────────────

TOTAL_NODES=${1:-32}
SUPERNODOS=${2:-4}
KN=$(( TOTAL_NODES / SUPERNODOS ))
VON_DIR="${VON_DIR:-/home/indy/von-network}"

# ── Validações ────────────────────────────────────────────────────────────────

if (( KN < 4 )); then
    echo "❌ Kn=$KN < 4. Mínimo RBFT é 4 nós. Use TOTAL_NODES >= $((SUPERNODOS * 4))."
    exit 1
fi

if [ ! -d "$VON_DIR" ]; then
    echo "❌ VON_DIR não encontrado: $VON_DIR"
    echo "   Ajuste VON_DIR no Makefile."
    exit 1
fi

echo "╔══════════════════════════════════════════════════════╗"
echo "║         COTTON-NET — VON Network Config (NFS)        ║"
echo "╠══════════════════════════════════════════════════════╣"
printf "║  Total de nós:    %-35s║\n" "$TOTAL_NODES"
printf "║  Supernodos (Sn): %-35s║\n" "$SUPERNODOS"
printf "║  Nós por Sn (Kn): %-35s║\n" "$KN"
printf "║  Destino:         %-35s║\n" "$VON_DIR"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── 1. Gera scripts/start_nodes.sh (genesis + modo combinado) ─────────────────

START_NODES="${VON_DIR}/scripts/start_nodes.sh"

{
    cat <<'HEADER'
#!/bin/bash
set -e
HOST="${HOST:-0.0.0.0}"
HEADER

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

    printf '[program:printlogs]\n'
    printf 'command=tail -F /tmp/supervisord.log'
    for i in $(seq 1 "$KN"); do printf ' /tmp/node%d.log' "$i"; done
    printf '\nstdout_logfile=/dev/stdout\nstdout_logfile_maxbytes=0\n'

    cat <<'FOOTER'
__SUPERVISORD__

echo "Starting $NODE_NUM indy nodes"
supervisord
FOOTER
} > "$START_NODES"
chmod +x "$START_NODES"
echo "✅ Gerado: $START_NODES"

# ── 2. Gera docker-compose.yml com node1..nodeN ───────────────────────────────

COMPOSE="${VON_DIR}/docker-compose.yml"

{
    cat <<'COMPOSE_HEADER'
version: '3'
services:
  #
  # Client
  #
  client:
    image: von-network-base
    command: ./scripts/start_client.sh
    environment:
      - IP=${IP}
      - IPS=${IPS}
      - DOCKERHOST=${DOCKERHOST}
      - RUST_LOG=${RUST_LOG}
    networks:
      - von
    volumes:
      - client-data:/home/indy/.indy_client
      - ./tmp:/tmp

  #
  # Webserver
  #
  webserver:
    image: von-network-base
    command: bash -c 'sleep 10 && ./scripts/start_webserver.sh'
    environment:
      - IP=${IP}
      - IPS=${IPS}
      - DOCKERHOST=${DOCKERHOST}
      - LOG_LEVEL=${LOG_LEVEL}
      - RUST_LOG=${RUST_LOG}
      - GENESIS_URL=${GENESIS_URL}
      - LEDGER_SEED=${LEDGER_SEED}
      - LEDGER_CACHE_PATH=${LEDGER_CACHE_PATH}
      - MAX_FETCH=${MAX_FETCH:-50000}
      - RESYNC_TIME=${RESYNC_TIME:-120}
      - POOL_CONNECTION_ATTEMPTS=${POOL_CONNECTION_ATTEMPTS:-5}
      - POOL_CONNECTION_DELAY=${POOL_CONNECTION_DELAY:-10}
      - REGISTER_NEW_DIDS=${REGISTER_NEW_DIDS:-True}
      - ENABLE_LEDGER_CACHE=${ENABLE_LEDGER_CACHE:-True}
      - ENABLE_BROWSER_ROUTES=${ENABLE_BROWSER_ROUTES:-True}
      - DISPLAY_LEDGER_STATE=${DISPLAY_LEDGER_STATE:-True}
      - LEDGER_INSTANCE_NAME=${LEDGER_INSTANCE_NAME:-localhost}
      - LEDGER_DESCRIPTION=${LEDGER_DESCRIPTION}
      - WEB_ANALYTICS_SCRIPT=${WEB_ANALYTICS_SCRIPT}
      - INFO_SITE_TEXT=${INFO_SITE_TEXT}
      - INFO_SITE_URL=${INFO_SITE_URL}
      - INDY_SCAN_URL=${INDY_SCAN_URL}
      - INDY_SCAN_TEXT=${INDY_SCAN_TEXT}
    networks:
      - von
    ports:
      - ${WEB_SERVER_HOST_PORT:-9000}:8000
    volumes:
      - ./config:/home/indy/config
      - ./server:/home/indy/server
      - webserver-cli:/home/indy/.indy-cli
      - webserver-ledger:/home/indy/ledger

  #
  # Nodes (modo combinado — mantido para compatibilidade)
  #
  nodes:
    image: von-network-base
    command: ./scripts/start_nodes.sh
    networks:
      - von
    environment:
      - IP=${IP}
      - IPS=${IPS}
      - DOCKERHOST=${DOCKERHOST}
      - LOG_LEVEL=${LOG_LEVEL}
      - RUST_LOG=${RUST_LOG}
    volumes:
      - nodes-data:/home/indy/ledger

COMPOSE_HEADER

    # Serviços individuais node1..nodeN
    for i in $(seq 1 "$KN"); do
        PORT1=$(( 9700 + i * 2 - 1 ))
        PORT2=$(( 9700 + i * 2 ))
        cat <<EOF
  node${i}:
    image: von-network-base
    command: ./scripts/start_node.sh ${i}
    networks:
      - von
    ports:
      - ${PORT1}:${PORT1}
      - ${PORT2}:${PORT2}
    environment:
      - IP=\${IP}
      - IPS=\${IPS}
      - DOCKERHOST=\${DOCKERHOST}
      - LOG_LEVEL=\${LOG_LEVEL}
      - RUST_LOG=\${RUST_LOG}
    volumes:
      - node${i}-data:/home/indy/ledger

EOF
    done

    echo "networks:"
    echo "  von:"
    echo ""
    echo "volumes:"
    echo "  client-data:"
    echo "  webserver-cli:"
    echo "  webserver-ledger:"
    echo "  nodes-data:"
    for i in $(seq 1 "$KN"); do
        echo "  node${i}-data:"
    done
} > "$COMPOSE"
echo "✅ Gerado: $COMPOSE"

# ── 3. Patcha manage: inclui node1..nodeN no comando start ────────────────────

MANAGE="${VON_DIR}/manage"
NODES_LIST=$(seq 1 "$KN" | xargs -I{} printf "node{} " | sed 's/ $//')

# Substitui qualquer linha "-d webserver node..." pelo novo node list
sed -i "s|-d webserver node[0-9 ]*$|-d webserver ${NODES_LIST}|g" "$MANAGE"
sed -i "s|-d synctest node[0-9 ]*$|-d synctest ${NODES_LIST}|g" "$MANAGE"

echo "✅ Patchado: $MANAGE (start com ${KN} nós)"

# ── 4. Gera bin/von_generate_transactions com --nodes ${KN} ──────────────────

GEN_TX="${VON_DIR}/bin/von_generate_transactions"

# Constrói a lista de IPs repetida Kn vezes (ex: Kn=8 → "ip,ip,ip,ip,ip,ip,ip,ip")
IPS_REPEAT=$(python3 -c "print(','.join(['\"\$ipAddress\"'] * ${KN}))")
DOCKERHOST_REPEAT=$(python3 -c "print(','.join(['\"\$DOCKERHOST\"'] * ${KN}))")

cat > "$GEN_TX" <<GENSCRIPT
#!/bin/bash
# von_generate_transactions — Gerado por start_von.sh (Kn=${KN})
# NÃO edite manualmente; re-gere com: ./scripts/start_von.sh ${TOTAL_NODES} ${SUPERNODOS}

set -e

rm -rf /var/lib/indy/*

usage () {
  cat <<-EOF

    Used to generate a genesis transaction file.

    Usage:
        \$0 [options]

    Options:
    -i <ip address>
        Specify the ip address to use in the genesis transaction file.
    -s <ip addresses>
        Specify a comma delimited list of addresses to use in the genesis transaction file.
    -n <node number>
        Specify the number to use for the given node.
    -h
        Display usage documentation.

    Examples:
        \$0 -i x.x.x.x -n y
        \$0 -s "a.a.a.a,b.b.b.b,..." -n x
EOF
exit 1
}

options=':i:s:n:h'
while getopts \$options option
do
    case \$option in
        i  ) ipAddress=\$OPTARG;;
        s  ) ipAddresses=\$OPTARG;;
        n  ) nodeNum=\$OPTARG;;
        h  ) usage; exit;;
        \? ) echo -e "Unknown option: -\$OPTARG" >&2; exit 1;;
        :  ) echo -e "Missing option argument for -\$OPTARG" >&2; exit 1;;
        *  ) echo -e "Unimplemented option: -\$OPTARG" >&2; exit 1;;
    esac
done

genesisFileName=\${genesisFileName:-pool_transactions_genesis}
genesisFileDir=\${genesisFileDir:-/home/indy/ledger/sandbox}
genesisFilePath=\${genesisFilePath:-\${genesisFileDir}/\${genesisFileName}}

nodeArg=""
if [ ! -z "\$nodeNum" ]; then
    nodeArg="--nodeNum \$nodeNum"
fi

if [ ! -z "\$ipAddresses" ]; then
    ipsArg="\$ipAddresses"
elif [ ! -z "\$ipAddress" ]; then
    ipsArg=${IPS_REPEAT}
elif [ ! -z "\$DOCKERHOST" ]; then
    ipsArg=${DOCKERHOST_REPEAT}
else
    echo "Error: no IP, IPS, or DOCKERHOST argument provided."
    exit 1
fi

echo "Generating genesis | nodes=${KN} ips=\${ipsArg}"

generate_indy_pool_transactions \
    --nodes ${KN} \
    --clients 0 \
    \$nodeArg \
    --ips "\$ipsArg"

echo "Genesis gerado: \${genesisFilePath}"
GENSCRIPT

chmod +x "$GEN_TX"
echo "✅ Gerado: $GEN_TX (--nodes ${KN})"

# ── 5. Gera von_local_start.sh — roda em cada baia individualmente ──────────

LOCAL_START="${VON_DIR}/von_local_start.sh"

cat > "$LOCAL_START" <<LOCALSCRIPT
#!/usr/bin/env bash
# von_local_start.sh — Gerado por von-config (Kn=${KN})
# Roda na baia local: reconstrói imagem e inicia os ${KN} nós Indy.
# Uso: ./von_local_start.sh

set -euo pipefail

MY_IP=\$(hostname -I | awk '{print \$1}')
IPS_VAL=\$(for i in \$(seq 1 ${KN}); do printf '%s,' "\$MY_IP"; done | sed 's/,\$//')
VON_DIR="\$(dirname "\$(realpath "\$0")")"

echo "🔧 Rebuild da imagem von-network-base..."
cd "\$VON_DIR"
DOCKER_API_VERSION=1.41 ./manage build

echo "🚀 Iniciando VON Network (\${MY_IP}, ${KN} nós)..."
DOCKER_API_VERSION=1.41 ./manage start "\$IPS_VAL"

echo "✅ VON Network iniciado | genesis: http://\${MY_IP}:9000/genesis"
LOCALSCRIPT

chmod +x "$LOCAL_START"
echo "✅ Gerado: $LOCAL_START"

# ── Resumo ────────────────────────────────────────────────────────────────────

echo ""
echo "Configuração pronta (NFS — visível em todas as baias)."
echo ""

# Lista apenas os primeiros SUPERNODOS nomes de baia (BAIA_NAMES vem do Makefile)
BAIA_LIST=( ${BAIA_NAMES:-baia1 baia2 baia3 baia4 baia5} )
BAIAS_ATIVAS=( "${BAIA_LIST[@]:0:${SUPERNODOS}}" )
echo "Em cada baia ativa (${BAIAS_ATIVAS[*]}):"
echo ""
echo "   cd ${VON_DIR} && ./von_local_start.sh"
echo ""
echo "Ou pelo Makefile (de dentro de cada baia):"
echo ""
echo "   make von-local-start"
