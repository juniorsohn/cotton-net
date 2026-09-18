#!/usr/bin/env bash
# Mostra o log de uma réplica.  uso: ./05_log.sh <id> [nº de linhas]
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
tail -n "${2:-30}" "$RUN/replica-${1:-1}.log"
