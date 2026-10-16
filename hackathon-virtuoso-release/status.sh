#!/usr/bin/env bash
# Shows what is running and what is loaded.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"
source "$SCRIPT_DIR/lib.sh"

require_docker

if ! container_running; then
  info "container:        ${CONTAINER_NAME} is NOT running (./start.sh to start it)"
  exit 0
fi

ontology_triples="$(isql_exec "SPARQL SELECT COUNT(*) WHERE { GRAPH <${RULE_SET_URI}> { ?s ?p ?o } };" | grep -Eo '^[0-9]+$' | head -1)"

info "container:        ${CONTAINER_NAME} (Virtuoso ${VIRTUOSO_VERSION})"
info "SPARQL endpoint:  http://localhost:${HTTP_HOST_PORT}/sparql"
info "patients folder:  ${PATIENTS_DIR}  ($(count_ttl_files "$PATIENTS_DIR") .ttl files on disk)"
info "patient graphs:   $(patient_graph_count) loaded, $(patient_triple_count) triple(s)"
info "ontologies:       ${ontology_triples:-0} triple(s) in <${RULE_SET_URI}>"
