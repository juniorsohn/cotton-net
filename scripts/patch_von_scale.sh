#!/usr/bin/env bash
# patch_von_scale.sh — Patch de ESCALA no indy-plenum dentro da von-network-base,
# para viabilizar pools RBFT grandes (192/256+ nós) no cluster.
#
# Duas alavancas (viram uma camada nova na imagem, como o patch_von_image.sh):
#
#   1. CAP de instâncias de réplica (REPLICA_CAP, default 4)
#      O Plenum roda f+1 réplicas por nó (a 256 nós: 86!), cada uma com 3PC
#      completo — é o multiplicador que explode a mensageria O(N²) e faz o view
#      change nunca convergir ("no primary chosen"). O cap troca f+1 por
#      min(f+1, K). ⚠️ Enfraquece a deteção BFT de primary malicioso (menos
#      backups auditando) — aceitável em testbed de DESEMPENHO, mas precisa ser
#      declarado no paper. E muda o consenso de TODOS os tamanhos de rede:
#      para comparabilidade, re-colete todos os cenários com a MESMA imagem.
#
#   2. Timeout de view change (VC_TIMEOUT, default 600s)
#      O default (~60s) é curto para a eleição trocar mensagens entre centenas
#      de nós; a eleição expira e recomeça em loop. Vai via /etc/indy/
#      indy_config.py (override de config, sem tocar no fonte).
#
# Uso (em CADA baia que roda nós, após o von-local-build/patch normal):
#   ./scripts/patch_von_scale.sh                     # REPLICA_CAP=4, VC_TIMEOUT=600
#   REPLICA_CAP=8 VC_TIMEOUT=900 ./scripts/patch_von_scale.sh
#
# Idempotente: rodar de novo não re-aplica nem quebra.

set -euo pipefail

REPLICA_CAP="${REPLICA_CAP:-4}"
VC_TIMEOUT="${VC_TIMEOUT:-600}"

if ! docker image inspect von-network-base &>/dev/null; then
    echo "❌ Imagem von-network-base não encontrada localmente."
    echo "   Execute 'make von-local-build' (ou ./manage build + von-patch) primeiro."
    exit 1
fi

echo "🔧 Patch de escala: REPLICA_CAP=${REPLICA_CAP}  VC_TIMEOUT=${VC_TIMEOUT}s ..."

# Build context temporário (compatível com builder clássico — sem heredoc no RUN)
CTX="$(mktemp -d)"
trap 'rm -rf "$CTX"' EXIT

cat > "${CTX}/patch_scale.py" <<'PY'
"""Cap de instâncias de réplica: getRequiredInstances = min(f+1, K)."""
import inspect
import pathlib
import re
import sys

K = int(sys.argv[1])

import plenum.common.util as u  # noqa: E402

src = pathlib.Path(inspect.getfile(u))
txt = src.read_text()
if 'PATCH_SCALE_REPLICA_CAP' in txt:
    print('Cap de réplicas: patch já aplicado —', src)
else:
    # substitui o corpo do return de getRequiredInstances por min(<original>, K)
    pat = re.compile(
        r"(def getRequiredInstances\([^)]*\)[^:]*:\s*\n"
        r"(?:\s+\"{3}[\s\S]*?\"{3}\s*\n)?\s+)return\s+(.+)")
    m = pat.search(txt)
    if not m:
        sys.exit('❌ getRequiredInstances não encontrado — layout do plenum mudou?')
    patched = (txt[:m.start()] + m.group(1)
               + f"return min({m.group(2).strip()}, {K})  # PATCH_SCALE_REPLICA_CAP\n"
               + txt[m.end():])
    src.write_text(patched)
    print(f'Cap de réplicas aplicado (K={K}):', src)

# verificação: a 256 nós (f=85, f+1=86) deve devolver min(86, K)
import importlib  # noqa: E402
importlib.reload(u)
got = u.getRequiredInstances(256)
assert got == min(86, K), f'esperava {min(86, K)}, veio {got}'
print('Verificação OK: getRequiredInstances(256) =', got)
PY

cat > "${CTX}/Dockerfile" <<'DOCKERFILE'
FROM von-network-base
ARG REPLICA_CAP
ARG VC_TIMEOUT
COPY patch_scale.py /tmp/patch_scale.py
RUN python3 /tmp/patch_scale.py "${REPLICA_CAP}" && rm -f /tmp/patch_scale.py
# Timeout de view change via override de config (cobre os dois nomes usados
# entre versões do plenum; atributo desconhecido é inócuo).
RUN mkdir -p /etc/indy && touch /etc/indy/indy_config.py && \
    if ! grep -q PATCH_SCALE_VC_TIMEOUT /etc/indy/indy_config.py; then \
      printf '\n# PATCH_SCALE_VC_TIMEOUT — view change em pools grandes\nVIEW_CHANGE_TIMEOUT = %s\nNEW_VIEW_TIMEOUT = %s\n' \
        "${VC_TIMEOUT}" "${VC_TIMEOUT}" >> /etc/indy/indy_config.py && \
      echo "VC timeout aplicado: ${VC_TIMEOUT}s"; \
    else echo "VC timeout: patch já aplicado"; fi
DOCKERFILE

docker build -q -t von-network-base \
    --build-arg REPLICA_CAP="${REPLICA_CAP}" \
    --build-arg VC_TIMEOUT="${VC_TIMEOUT}" \
    "${CTX}"

echo "✅ von-network-base patcheada para escala (cap=${REPLICA_CAP}, vc=${VC_TIMEOUT}s)."
echo "   Lembre: aplique em TODAS as baias que rodam nós, e re-colete os cenários"
echo "   com a mesma imagem para manter a comparabilidade."
