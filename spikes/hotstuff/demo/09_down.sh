#!/usr/bin/env bash
# Derruba tudo que o 01_up.sh subiu e confere que não sobrou processo nem porta.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
if [[ -f "$RUN/pids" ]]; then while read -r p; do kill -9 "$p" 2>/dev/null || true; done < "$RUN/pids"; rm -f "$RUN/pids"; fi
pkill -9 -f "[c]ottonhs replica .*$RUN" 2>/dev/null || true
pkill -9 -f "[a]pplier_stub.py .*$RUN" 2>/dev/null || true
sleep 1
sobrou="$(pgrep -af '[c]ottonhs replica|[a]pplier_stub.py' 2>/dev/null | grep -v 'bash -c' || true)"
[[ -z "$sobrou" ]] && echo "OK  nenhum processo do spike rodando" || { echo "ATENÇÃO, sobrou:"; echo "$sobrou"; }
nossas=""
for i in $(seq 1 "$N"); do for off in 100 200 300 400; do nossas="$nossas|:$((BASE+off+i))\\>"; done; done
portas="$(ss -ltn 2>/dev/null | grep -E "${nossas#|}" | awk '{print $4}' || true)"
[[ -z "$portas" ]] && echo "OK  portas do cluster livres" || { echo "ATENÇÃO, portas ocupadas:"; echo "$portas"; }
