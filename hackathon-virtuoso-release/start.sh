#!/usr/bin/env bash
# Starts the Virtuoso container, registers the bulk loader, and loads any ontologies.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"
source "$SCRIPT_DIR/lib.sh"

require_docker

# A running or stopped container may come from a start.sh that was interrupted, so
# load-ontologies.sh runs in every case: it finishes an incomplete load, or skips at once.
if container_running; then
  info "${CONTAINER_NAME} is already running."
  "$SCRIPT_DIR/load-ontologies.sh"
  info "  SPARQL endpoint: http://localhost:${HTTP_HOST_PORT}/sparql"
  exit 0
fi

# A stopped container still holds everything that was loaded into it, and reloading
# ontologies is slow, so resume it rather than recreating it. ./destroy.sh for a fresh one.
if container_exists; then
  info "resuming stopped container ${CONTAINER_NAME} (previously loaded data is still there)"
  docker start "$CONTAINER_NAME" >/dev/null
  wait_until_ready
  "$SCRIPT_DIR/load-ontologies.sh"
  info "${CONTAINER_NAME} is up."
  info "  SPARQL endpoint:  http://localhost:${HTTP_HOST_PORT}/sparql"
  info "  patients folder:  ${PATIENTS_DIR}  ($(count_ttl_files "$PATIENTS_DIR") .ttl files)"
  "$SCRIPT_DIR/status.sh"
  exit 0
fi

mkdir -p "$PATIENTS_DIR" "$ONTOLOGIES_DIR" "$ONTOLOGY_CACHE_DIR"

ram_gb="$(buffer_pool_ram_gb)"
number_of_buffers="$(number_of_buffers_for "$ram_gb")"
max_dirty_buffers="$(max_dirty_buffers_for "$number_of_buffers")"

info "starting ${CONTAINER_NAME} (Virtuoso ${VIRTUOSO_VERSION}, buffer pool ~${ram_gb} GB)"
docker run -d \
  --name "$CONTAINER_NAME" \
  -p "${ISQL_HOST_PORT}:${ISQL_PORT}" \
  -p "${HTTP_HOST_PORT}:${VIRTUOSO_HTTP_PORT}" \
  -v "$(cd "$PATIENTS_DIR" && pwd):${DATA_MOUNT_PATH}" \
  -v "$(cd "$ONTOLOGIES_DIR" && pwd):${ONTOLOGIES_MOUNT_PATH}" \
  -v "$(cd "$ONTOLOGY_CACHE_DIR" && pwd):${ONTOLOGY_CACHE_MOUNT_PATH}" \
  -e "DBA_PASSWORD=${DBA_PASSWORD}" \
  -e "VIRT_Parameters_DirsAllowed=${DIRS_ALLOWED}" \
  -e "VIRT_Parameters_MaxQueryCostEstimationTime=0" \
  -e "VIRT_SPARQL_MaxQueryCostEstimationTime=0" \
  -e "VIRT_Parameters_NumberOfBuffers=${number_of_buffers}" \
  -e "VIRT_Parameters_MaxDirtyBuffers=${max_dirty_buffers}" \
  "openlink/virtuoso-opensource-7:${VIRTUOSO_VERSION}" >/dev/null

info "waiting for Virtuoso to accept connections"
wait_until_ready

# Enumerates a directory and queues one (file, graph) row per .ttl file onto
# Virtuoso's own load_list; rdf_loader_run() workers do the actual parsing.
# Virtuoso has no CREATE OR REPLACE PROCEDURE, so this runs once per container.
info "registering bulk loader procedure"
isql_exec "CREATE PROCEDURE ${BULK_LOADER_PROCEDURE} (IN dir_path VARCHAR, IN graph_prefix VARCHAR) { \
DECLARE files ANY; DECLARE i INTEGER; DECLARE fname VARCHAR; DECLARE graph_uri VARCHAR; \
DECLARE n_queued INTEGER; \
DELETE FROM DB.DBA.load_list; \
COMMIT WORK; \
files := sys_dirlist (dir_path, 1); \
n_queued := 0; \
FOR (i := 0; i < LENGTH (files); i := i + 1) \
{ \
fname := files[i]; \
IF (fname LIKE '%.ttl') \
{ \
graph_uri := CONCAT (graph_prefix, SUBSEQ (fname, 0, LENGTH (fname) - 4)); \
INSERT INTO DB.DBA.load_list (ll_file, ll_graph) VALUES (CONCAT (dir_path, '/', fname), graph_uri); \
n_queued := n_queued + 1; \
IF (MOD (n_queued, 10000) = 0) { COMMIT WORK; } \
} \
}; \
COMMIT WORK; \
RETURN n_queued; \
}" >/dev/null

"$SCRIPT_DIR/load-ontologies.sh"

info "${CONTAINER_NAME} is up."
info "  SPARQL endpoint:  http://localhost:${HTTP_HOST_PORT}/sparql"
info "  isql:             docker exec -it ${CONTAINER_NAME} isql ${ISQL_PORT} dba ${DBA_PASSWORD}"
info "  patients folder:  ${PATIENTS_DIR}  ($(count_ttl_files "$PATIENTS_DIR") .ttl files)"
info "Next: ./load-patients.sh"
