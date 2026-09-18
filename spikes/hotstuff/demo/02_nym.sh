#!/usr/bin/env bash
# Propõe UMA NYM e mostra o resultado nas réplicas e nos appliers.
# uso: ./02_nym.sh <entity_id> [réplica]
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
tool nym "${1:-alice}" --replica "${2:-1}"
