#!/usr/bin/env bash
# Reconstrói spikes/hotstuff/relab/ a partir do upstream.
#
# O relab é um clone do upstream e NÃO é versionado aqui (tem .git próprio).
# O que é nosso e vive no git: patches/, cottonhs/, demo/, applier_stub.py,
# spike_test.py, test_coordinator_boundary.py. Este script junta as peças.
#
# É DETERMINÍSTICO: devolve o clone ao estado do upstream e reaplica o patch.
# Ou seja, editar relab/ direto não sobrevive a um setup — o patch é a fonte da
# verdade. Para mudar o relab: edite, rode `git -C relab diff > patches/0001-*.patch`
# e só então rode o setup de novo.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="${VERSION:-v0.5.0}"

if [[ ! -d "$HERE/relab/.git" ]]; then
  echo "→ clonando relab/hotstuff $VERSION"
  git clone --depth 1 --branch "$VERSION" https://github.com/relab/hotstuff.git "$HERE/relab"
fi

cd "$HERE/relab"
git checkout -- .                       # volta ao upstream
for p in "$HERE"/patches/*.patch; do
  echo "→ aplicando $(basename "$p")"
  git apply "$p"
done

echo "→ copiando cottonhs/ para o módulo relab (precisa de internal/proto/clientpb)"
mkdir -p "$HERE/relab/cmd/cottonhs"
cp "$HERE/cottonhs/"*.go "$HERE/relab/cmd/cottonhs/"
echo "OK  agora rode demo/00_build.sh"
