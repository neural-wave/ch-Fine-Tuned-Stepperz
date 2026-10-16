#!/usr/bin/env bash
# Runs a SPARQL query and prints its results plus the server-side elapsed time.
# Usage: ./query.sh queries/count-per-graph.rq
#        ./query.sh "SELECT * WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 10"
#        ./query.sh queries/my.rq --out results.txt
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"
source "$SCRIPT_DIR/lib.sh"

[ $# -ge 1 ] || fail "Usage: ./query.sh <query-file.rq | \"SPARQL text\"> [--out results.txt]"

query_source="$1"
shift
out_path=""
if [ "${1:-}" = "--out" ]; then
  [ $# -ge 2 ] || fail "--out needs a file path"
  out_path="$2"
fi

if [ -f "$query_source" ]; then
  query="$(cat "$query_source")"
  query_name="$(basename "$query_source")"
else
  query="$query_source"
  query_name="inline query"
fi

require_docker
require_running_container

output="$(isql_exec "SPARQL ${query}")"
# Drop isql's connection banner so only the result table and its timing footer remain.
output="$(printf '%s' "$output" | grep -v -E '^(OpenLink Virtuoso Interactive SQL|Version [0-9]|Type HELP;|Connected to OpenLink|Driver: )')"
printf '%s\n' "$output"

if [ -n "$out_path" ]; then
  printf '%s\n' "$output" >"$out_path"
  info "results written to ${out_path}"
fi

# isql prints its own server-side timing footer, which excludes Docker/CLI overhead.
elapsed_msec="$(printf '%s' "$output" | grep -Eo -- '--[[:space:]]*[0-9]+(\.[0-9]+)?[[:space:]]*msec\.' | tail -1 | grep -Eo '[0-9]+(\.[0-9]+)?' || true)"
if [ -n "$elapsed_msec" ]; then
  printf '%s%s: %s ms%s\n' "$BOLD_YELLOW" "$query_name" "$elapsed_msec" "$RESET"
fi
