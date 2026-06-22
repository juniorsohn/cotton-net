#!/usr/bin/env bash
# Deploy sequencial COTTON-NET: um supernodo por vez.
# Uso: ./scripts/cn_deploy_seq.sh NODES SUPERNODOS [STACK]
#   Ex: ./scripts/cn_deploy_seq.sh 128 4
set -euo pipefail

NODES="${1:-128}"
SUPERNODOS="${2:-4}"
CN_STACK="${3:-cn}"
KN=$(( NODES / SUPERNODOS ))

BAIA_IPS=(10.10.20.151 10.10.20.152 10.10.20.153 10.10.20.154)

echo "=== Deploy sequencial COTTON-NET: ${SUPERNODOS} SN × ${KN} nós ==="

docker stack deploy --resolve-image=never -c docker-stack-cottonnet.yml "${CN_STACK}"

echo "Pausando SN2..SN${SUPERNODOS} antes que os containers iniciem..."
for s in $(seq 2 "${SUPERNODOS}"); do
    (
        for n in $(seq 1 "${KN}"); do
            docker service update --replicas=0 --detach \
                "${CN_STACK}_cn-sn${s}-node${n}" >/dev/null 2>&1
        done
        docker service update --replicas=0 --detach \
            "${CN_STACK}_webserver-sn${s}" >/dev/null 2>&1
        echo "SN${s} pausado."
    ) &
done
wait

echo ""
echo "SN2-SN${SUPERNODOS} pausados. Iniciando sequência..."

for s in $(seq 1 "${SUPERNODOS}"); do
    echo ""
    echo "=== SN${s}: escalando ${KN} nós Indy + webserver ==="
    for n in $(seq 1 "${KN}"); do
        docker service update --replicas=1 --detach \
            "${CN_STACK}_cn-sn${s}-node${n}" >/dev/null 2>&1
    done
    docker service update --replicas=1 --detach \
        "${CN_STACK}_webserver-sn${s}" >/dev/null 2>&1

    WEBIP="${BAIA_IPS[$(( s - 1 ))]}"
    echo "Aguardando genesis SN${s} em http://${WEBIP}:9000 ..."
    until curl -sf "http://${WEBIP}:9000/genesis" >/dev/null 2>&1; do
        printf '.'
        sleep 15
    done
    echo " ✅ SN${s} OK"
done

echo ""
echo "✅ Todos os ${SUPERNODOS} supernodos com genesis OK"
