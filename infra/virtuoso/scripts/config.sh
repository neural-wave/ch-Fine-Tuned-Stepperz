# Settings shared by every script here. Override any of them from the environment:
#   VIRTUOSO_VERSION=7.2.13 ./infra/virtuoso/scripts/start.sh
#   PATIENTS_DIR=/path/to/my/patients ./infra/virtuoso/scripts/start.sh

VIRTUOSO_VERSION="${VIRTUOSO_VERSION:-7.2.16}"
CONTAINER_NAME="${CONTAINER_NAME:-hackathon-virtuoso}"
DBA_PASSWORD="${DBA_PASSWORD:-dba}"

ISQL_HOST_PORT="${ISQL_HOST_PORT:-1111}"
HTTP_HOST_PORT="${HTTP_HOST_PORT:-8890}"

# La posizione degli script e cambiata; i percorsi dati dei mount restano stabili.
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PATIENTS_DIR="${PATIENTS_DIR:-$PROJECT_ROOT/patients}"
ONTOLOGIES_DIR="${ONTOLOGIES_DIR:-$PROJECT_ROOT/ontologies}"
ONTOLOGY_CACHE_DIR="${ONTOLOGY_CACHE_DIR:-$PROJECT_ROOT/.ontology_cache}"

# One named graph per patient file: <prefix><file name without .ttl>
GRAPH_URI_PREFIX="${GRAPH_URI_PREFIX:-http://example.org/graph/}"

# The inference rule set every ontology file is loaded into and registered under.
# Queries reference it as: OPTION (inference "https://biomedit.ch/rdf/sphn-resource/global")
RULE_SET_URI="${RULE_SET_URI:-https://biomedit.ch/rdf/sphn-resource/global}"

# Concurrent rdf_loader_run() workers pulling off Virtuoso's shared load queue.
LOAD_WORKER_COUNT="${LOAD_WORKER_COUNT:-8}"

# Buffer pool size, in GB. Empty means "compute it from the RAM Docker reports".
VIRTUOSO_RAM_GB="${VIRTUOSO_RAM_GB:-}"
