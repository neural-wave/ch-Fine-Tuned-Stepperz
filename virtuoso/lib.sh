# Helpers shared by every script. Source config.sh before this file.

ISQL_PORT=1111
VIRTUOSO_HTTP_PORT=8890
DATA_MOUNT_PATH=/data
ONTOLOGIES_MOUNT_PATH=/ontologies
ONTOLOGY_CACHE_MOUNT_PATH=/ontologies-cache
DIRS_ALLOWED="., ../vad, /usr/share/proj, ${DATA_MOUNT_PATH}, ${ONTOLOGIES_MOUNT_PATH}, ${ONTOLOGY_CACHE_MOUNT_PATH}"
BULK_LOADER_PROCEDURE=bulk_load_dir_into_graphs

# isql caps a single exec= at 50 semicolon-terminated statements.
MAX_STATEMENTS_PER_ISQL_EXEC=40

BUFFER_POOL_AVAILABLE_RAM_PERCENT=80
BUFFER_POOL_NUMBER_OF_BUFFERS_PERCENT=65
BUFFER_POOL_MAX_DIRTY_BUFFERS_PERCENT=75

BOLD_GREEN=$'\033[1;92m'
BOLD_YELLOW=$'\033[1;33m'
BOLD_RED=$'\033[1;31m'
RESET=$'\033[0m'

if [ ! -t 1 ]; then
  BOLD_GREEN=""; BOLD_YELLOW=""; BOLD_RED=""; RESET=""
fi

info() { printf '%s%s%s\n' "$BOLD_GREEN" "$*" "$RESET"; }
warn() { printf '%s%s%s\n' "$BOLD_YELLOW" "$*" "$RESET" >&2; }
fail() { printf '%s%s%s\n' "$BOLD_RED" "$*" "$RESET" >&2; exit 1; }

require_docker() {
  command -v docker >/dev/null 2>&1 || fail "docker not found on PATH."
  docker info >/dev/null 2>&1 || fail "Docker is not running. Start Docker Desktop (or your daemon) and try again."
}

container_exists() {
  [ -n "$(docker ps -aq --filter "name=^${CONTAINER_NAME}$")" ]
}

container_running() {
  [ -n "$(docker ps -q --filter "name=^${CONTAINER_NAME}$")" ]
}

require_running_container() {
  container_running || fail "Container '${CONTAINER_NAME}' is not running. Run ./start.sh first."
}

# isql URL-decodes the exec= value, so a literal + becomes a space and %XX is decoded.
escape_isql_exec_argument() {
  printf '%s' "$1" | sed -e 's/%/%25/g' -e 's/+/%2B/g'
}

escape_sql_string_literal() {
  printf '%s' "$1" | sed -e "s/'/''/g"
}

# Runs one isql statement. Prints its output on stdout. Virtuoso reports errors on
# stdout with exit code 0, so the output is checked for "*** Error" too.
isql_exec() {
  local statement escaped output status
  statement="$1"
  escaped="$(escape_isql_exec_argument "$statement")"
  set +e
  output="$(docker exec "$CONTAINER_NAME" isql "$ISQL_PORT" dba "$DBA_PASSWORD" "exec=$escaped" 2>&1)"
  status=$?
  set -e
  if [ "$status" -ne 0 ] || printf '%s' "$output" | grep -q '\*\*\* Error'; then
    printf '%s%s%s\n' "$BOLD_RED" "isql failed on: ${statement:0:200}" "$RESET" >&2
    printf '%s\n' "$output" >&2
    return 1
  fi
  printf '%s\n' "$output"
}

wait_until_ready() {
  local attempts="${1:-60}" attempt
  for attempt in $(seq 1 "$attempts"); do
    if isql_exec "STATUS();" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  fail "Virtuoso did not become ready after ${attempts}s. Check: docker logs ${CONTAINER_NAME}"
}

buffer_pool_ram_gb() {
  if [ -n "$VIRTUOSO_RAM_GB" ]; then
    printf '%s' "$VIRTUOSO_RAM_GB"
    return
  fi
  local total_bytes
  total_bytes="$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)"
  awk -v bytes="$total_bytes" -v percent="$BUFFER_POOL_AVAILABLE_RAM_PERCENT" \
    'BEGIN { gb = bytes / 1073741824 * percent / 100; if (gb < 1) gb = 1; printf "%.3f", gb }'
}

# Virtuoso buffers are 8 KB each, so a GB budget is (gb * 1024 * 1024 / 8) buffers.
number_of_buffers_for() {
  awk -v gb="$1" -v percent="$BUFFER_POOL_NUMBER_OF_BUFFERS_PERCENT" \
    'BEGIN { printf "%d", gb * 1024 * 1024 / 8 * percent / 100 }'
}

max_dirty_buffers_for() {
  awk -v buffers="$1" -v percent="$BUFFER_POOL_MAX_DIRTY_BUFFERS_PERCENT" \
    'BEGIN { printf "%d", buffers * percent / 100 }'
}

count_ttl_files() {
  find "$1" -maxdepth 1 -type f -name '*.ttl' 2>/dev/null | wc -l | tr -d ' '
}

patient_graph_count() {
  isql_exec "SPARQL SELECT COUNT(DISTINCT ?g) WHERE { GRAPH ?g { ?s ?p ?o } FILTER(STRSTARTS(STR(?g), \"${GRAPH_URI_PREFIX}\")) };" \
    | grep -Eo '^[0-9]+$' | head -1
}

patient_triple_count() {
  isql_exec "SPARQL SELECT COUNT(*) WHERE { GRAPH ?g { ?s ?p ?o } FILTER(STRSTARTS(STR(?g), \"${GRAPH_URI_PREFIX}\")) };" \
    | grep -Eo '^[0-9]+$' | head -1
}
