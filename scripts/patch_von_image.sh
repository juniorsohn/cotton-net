#!/usr/bin/env bash
# patch_von_image.sh — Aplica patch no limite de nós do indy-plenum dentro da
# imagem von-network-base e re-tageia como von-network-base.
#
# O limite original de 100 nós em plenum/common/test_network_setup.py é um
# placeholder de governança, não uma restrição do protocolo RBFT.
# A mensagem original diz explicitamente: "This is not a problem with the protocol".
#
# Uso: ./scripts/patch_von_image.sh
# Requer: von-network-base disponível localmente (./manage build já executado).

set -euo pipefail

# Verifica se a imagem base existe
if ! docker image inspect von-network-base &>/dev/null; then
    echo "❌ Imagem von-network-base não encontrada localmente."
    echo "   Execute './manage build' no diretório von-network primeiro."
    exit 1
fi

echo "🔧 Aplicando patch indy-plenum: limite de nós 100 → 10000..."

docker build -q -t von-network-base - <<'PATCHEOF'
FROM von-network-base
RUN python3 -c "import plenum.common.test_network_setup as m, inspect, pathlib; src = pathlib.Path(inspect.getfile(m)); txt = src.read_text(); patched = txt.replace('if n > 100:', 'if n > 10000:'); src.write_text(patched); print('Patch OK:' if patched != txt else 'Patch ja aplicado:', src)"
PATCHEOF

echo "✅ von-network-base patcheado (limite 100 → 10000 nós)."
