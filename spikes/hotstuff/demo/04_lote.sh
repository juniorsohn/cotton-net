#!/usr/bin/env bash
# Propõe N NYMs em sequência, alternando réplicas, e confere convergência.
# uso: ./04_lote.sh [quantidade] [prefixo]
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
tool lote "${1:-10}" --prefixo "${2:-lote}"
