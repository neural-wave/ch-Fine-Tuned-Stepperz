#!/usr/bin/env bash
# Stops the container, keeping everything loaded in it. ./infra/virtuoso/scripts/start.sh brings it back with
# the patients and ontologies still in place. Use ./infra/virtuoso/scripts/destroy.sh for an empty store.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"
source "$SCRIPT_DIR/lib.sh"

require_docker

if ! container_exists; then
  info "${CONTAINER_NAME} does not exist. Nothing to do."
  exit 0
fi

if ! container_running; then
  info "${CONTAINER_NAME} is already stopped."
  exit 0
fi

info "checkpointing before shutdown"
isql_exec "checkpoint;" >/dev/null || warn "checkpoint failed; stopping anyway"
docker stop "$CONTAINER_NAME" >/dev/null
info "stopped ${CONTAINER_NAME} (data kept — ./infra/virtuoso/scripts/start.sh resumes it)"
