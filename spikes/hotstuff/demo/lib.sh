# Configuração comum. Todos os scripts fazem `source lib.sh`.
set -euo pipefail
DEMO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE="$(dirname "$DEMO")"
RUN="$DEMO/.run"                 # estado desta execução (config, logs, jsonl, pids)
BIN="$SPIKE/bin/cottonhs"        # daemon Go (compilado por 00_build.sh)
# venv do projeto se existir, senão python3 do sistema (só usamos a stdlib)
VENV="$(dirname "$(dirname "$(dirname "$SPIKE")")")/.venv/bin/python"
PY="${PY:-$([[ -x "$VENV" ]] && echo "$VENV" || command -v python3)}"
N="${N:-4}"                      # nº de réplicas (BFT precisa de 3f+1: 4 tolera 1)
BASE="${BASE:-34000}"            # http da réplica i = BASE+300+i ; applier = BASE+400+i
FILLER="${FILLER:-0s}"           # no-ops (contorno antigo); 0s = desligado, o líder usa bloco vazio
TLS="${TLS:-false}"              # cifra o consenso; desligado por padrão (baseline Raft roda em claro)
EMPTY="${EMPTY:-true}"           # líder propõe bloco vazio p/ fechar a 3-cadeia (false = comportamento original do relab)
LOGLEVEL="${LOGLEVEL:-info}"     # use debug para ver o protocolo por dentro
tool() { "$PY" "$DEMO/_tool.py" "$@"; }
