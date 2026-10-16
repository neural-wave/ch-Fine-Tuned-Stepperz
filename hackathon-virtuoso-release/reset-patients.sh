#!/usr/bin/env bash
# Clears every patient graph (everything under GRAPH_URI_PREFIX), leaving the loaded
# ontologies and the inference rule set in place.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"
source "$SCRIPT_DIR/lib.sh"

require_docker
require_running_container

graph_uris=()
while IFS= read -r graph_uri; do
  [ -n "$graph_uri" ] && graph_uris+=("$graph_uri")
done < <(isql_exec "SPARQL SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } FILTER(STRSTARTS(STR(?g), \"${GRAPH_URI_PREFIX}\")) };" \
  | grep -o "^${GRAPH_URI_PREFIX}[^[:space:]]*" || true)

if [ "${#graph_uris[@]}" -eq 0 ]; then
  info "no patient graphs to clear"
  exit 0
fi

info "clearing ${#graph_uris[@]} patient graph(s)"
statement=""
statements_in_batch=0
for graph_uri in "${graph_uris[@]}"; do
  statement+="SPARQL CLEAR GRAPH <${graph_uri}>; "
  statements_in_batch=$((statements_in_batch + 1))
  if [ "$statements_in_batch" -ge "$MAX_STATEMENTS_PER_ISQL_EXEC" ]; then
    isql_exec "$statement" >/dev/null
    statement=""
    statements_in_batch=0
  fi
done
[ -n "$statement" ] && isql_exec "$statement" >/dev/null

info "cleared"
