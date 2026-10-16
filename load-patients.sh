#!/usr/bin/env bash
# Bulk-loads every .ttl file in the patients folder, one named graph per file, using
# Virtuoso's load_list queue and parallel rdf_loader_run() workers.
# Usage: ./load-patients.sh [--reset]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"
source "$SCRIPT_DIR/lib.sh"

reset=false
[ "${1:-}" = "--reset" ] && reset=true

require_docker
require_running_container

file_count="$(count_ttl_files "$PATIENTS_DIR")"
if [ "$file_count" -eq 0 ]; then
  fail "No .ttl files in ${PATIENTS_DIR}. Put the patient files there and run this again."
fi

mounted_dir="$(docker inspect --format "{{range .Mounts}}{{if eq .Destination \"${DATA_MOUNT_PATH}\"}}{{.Source}}{{end}}{{end}}" "$CONTAINER_NAME")"
if [ "$(cd "$PATIENTS_DIR" && pwd)" != "$mounted_dir" ]; then
  fail "The running container has ${mounted_dir} mounted as ${DATA_MOUNT_PATH}, not ${PATIENTS_DIR}.
Mounts are fixed when a container is created: run ./destroy.sh, then PATIENTS_DIR=${PATIENTS_DIR} ./start.sh"
fi

if [ "$reset" = true ]; then
  "$SCRIPT_DIR/reset-patients.sh"
fi

# Standard Virtuoso bulk-load tuning: no checkpoints or transaction logging during the
# load (a crash mid-load then loses the log — fine, the files are the source of truth),
# restored and checkpointed afterwards no matter how this exits.
restore_durability() {
  isql_exec "log_enable (1); checkpoint_interval (60); checkpoint;" >/dev/null || true
}
isql_exec "checkpoint_interval (-1); log_enable (2);" >/dev/null
trap restore_durability EXIT

info "queueing ${file_count} file(s) from ${PATIENTS_DIR}"
isql_exec "SELECT ${BULK_LOADER_PROCEDURE} ('${DATA_MOUNT_PATH}', '$(escape_sql_string_literal "$GRAPH_URI_PREFIX")');" >/dev/null

info "loading with ${LOAD_WORKER_COUNT} parallel workers"
start_seconds="$SECONDS"
pids=()
for _ in $(seq 1 "$LOAD_WORKER_COUNT"); do
  isql_exec "rdf_loader_run();" >/dev/null &
  pids+=("$!")
done
load_failed=false
for pid in "${pids[@]}"; do
  wait "$pid" || load_failed=true
done

trap - EXIT
restore_durability

errors="$(isql_exec "SELECT ll_file, ll_error FROM DB.DBA.load_list WHERE ll_error IS NOT NULL;")"
if printf '%s' "$errors" | grep -q 'ttl'; then
  warn "Some files failed to load:"
  printf '%s\n' "$errors" >&2
fi
[ "$load_failed" = true ] && fail "At least one loader worker failed — see the output above."

info "loaded in $((SECONDS - start_seconds))s: $(patient_graph_count) graph(s), $(patient_triple_count) triple(s)"
info "Next: ./query.sh queries/count-per-graph.rq"
