#!/usr/bin/env bash
# Removes the container and everything loaded into it. The next ./start.sh begins from an
# empty store and reloads the ontologies. Your .ttl files on disk are never touched.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"
source "$SCRIPT_DIR/lib.sh"

require_docker

if ! container_exists; then
  info "${CONTAINER_NAME} does not exist. Nothing to do."
  exit 0
fi

docker rm -f "$CONTAINER_NAME" >/dev/null
info "removed ${CONTAINER_NAME}"
