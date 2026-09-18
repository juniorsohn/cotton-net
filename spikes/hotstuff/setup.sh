#!/usr/bin/env bash
# Reconstrói spikes/hotstuff/relab/ a partir do upstream.
#
# O relab é um clone do upstream e NÃO é versionado aqui (tem .git próprio).
# O que é nosso e vive no git: patches/, cottonhs/, demo/, applier_stub.py,
# spike_test.py. Este script junta as peças.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="${VERSION:-v0.5.0}"

if [[ ! -d "$HERE/relab/.git" ]]; then
  echo "→ clonando relab/hotstuff $VERSION"
  git clone --depth 1 --branch "$VERSION" https://github.com/relab/hotstuff.git "$HERE/relab"
fi

cd "$HERE/relab"
for p in "$HERE"/patches/*.patch; do
  if git apply --reverse --check "$p" 2>/dev/null; then
    echo "   $(basename "$p") já aplicado"
  else
    echo "→ aplicando $(basename "$p")"
    git apply "$p"
  fi
done

echo "→ copiando cottonhs/ para o módulo relab (precisa de internal/proto/clientpb)"
mkdir -p "$HERE/relab/cmd/cottonhs"
cp "$HERE/cottonhs/"*.go "$HERE/relab/cmd/cottonhs/"
echo "OK  agora rode demo/00_build.sh"
