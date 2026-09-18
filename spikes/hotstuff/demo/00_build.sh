#!/usr/bin/env bash
# Compila o daemon cottonhs a partir do relab (com o patch OnExec aplicado).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
echo "→ sincronizando fontes (patches + cottonhs) no clone do relab"
"$SPIKE/setup.sh" > /dev/null
echo "→ compilando $BIN"
cd "$SPIKE/relab"
GOTOOLCHAIN=auto go build -o "$BIN" ./cmd/cottonhs
echo "OK  $(ls -lh "$BIN" | awk '{print $5}')  $("$BIN" 2>&1 | head -1 || true)"
