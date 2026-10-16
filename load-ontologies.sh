#!/usr/bin/env bash
# Loads every ontology/terminology file into ONE shared graph named after the rule set
# URI, then registers that graph with RDFS_RULE_SET once — the same shape as production,
# so inference-dependent query costs behave the same way.
# Called automatically by start.sh; safe to run again (it skips an already-loaded rule set).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"
source "$SCRIPT_DIR/lib.sh"

force=false
[ "${1:-}" = "--force" ] && force=true

require_docker
require_running_container

mkdir -p "$ONTOLOGY_CACHE_DIR"
shopt -s nullglob
# Archives (e.g. SNOMED CT) are slow to unpack, so extracted files are kept in the cache
# directory and only extracted the first time.
for archive in "$ONTOLOGIES_DIR"/*.zip; do
  command -v unzip >/dev/null 2>&1 || fail "unzip not found on PATH, needed for $(basename "$archive")"
  while IFS= read -r member; do
    [ -n "$member" ] || continue
    if [ ! -f "$ONTOLOGY_CACHE_DIR/$(basename "$member")" ]; then
      info "extracting $(basename "$member") from $(basename "$archive")"
      unzip -o -q -j "$archive" "$member" -d "$ONTOLOGY_CACHE_DIR"
    fi
  done < <(unzip -Z1 "$archive" '*.ttl' 2>/dev/null || true)
done

container_paths=()
for path in "$ONTOLOGIES_DIR"/*.ttl; do
  container_paths+=("${ONTOLOGIES_MOUNT_PATH}/$(basename "$path")")
done
for path in "$ONTOLOGY_CACHE_DIR"/*.ttl; do
  container_paths+=("${ONTOLOGY_CACHE_MOUNT_PATH}/$(basename "$path")")
done
shopt -u nullglob

if [ "${#container_paths[@]}" -eq 0 ]; then
  warn "No ontology files found in ${ONTOLOGIES_DIR} — skipping ontology loading."
  warn "Queries using OPTION (inference \"${RULE_SET_URI}\") will return no inferred triples."
  exit 0
fi

escaped_rule_set_uri="$(escape_sql_string_literal "$RULE_SET_URI")"

ontology_triple_count() {
  isql_exec "SPARQL SELECT COUNT(*) WHERE { GRAPH <${RULE_SET_URI}> { ?s ?p ?o } };" | grep -Eo '^[0-9]+$' | head -1
}

# The rule set is registered last, so it only exists once a load ran to the end.
rule_set_registered() {
  [ "$(isql_exec "SELECT COUNT(*) FROM DB.DBA.SYS_RDF_SCHEMA WHERE RS_NAME = '${escaped_rule_set_uri}';" \
    | grep -Eo '^[0-9]+$' | head -1)" -gt 0 ]
}

already_loaded="$(ontology_triple_count)"
if [ "${already_loaded:-0}" -gt 0 ] && [ "$force" = false ]; then
  if rule_set_registered; then
    info "ontologies already loaded (${already_loaded} triples in <${RULE_SET_URI}>); skipping. Use --force to reload."
    exit 0
  fi
  warn "a previous ontology load did not finish (${already_loaded} triples, rule set not registered); reloading."
  force=true
fi

if [ "$force" = true ]; then
  info "clearing <${RULE_SET_URI}>"
  isql_exec "SPARQL CLEAR GRAPH <${RULE_SET_URI}>;" >/dev/null
fi

info "loading ${#container_paths[@]} ontology file(s) into <${RULE_SET_URI}> (can take several minutes)"
for container_path in "${container_paths[@]}"; do
  escaped_path="$(escape_sql_string_literal "$container_path")"
  started=$SECONDS
  printf '%s  %s ...%s' "$BOLD_GREEN" "$(basename "$container_path")" "$RESET"
  isql_exec "DB.DBA.TTLP_MT (file_to_string_output('${escaped_path}'), '', '${escaped_rule_set_uri}');" >/dev/null
  printf '%s %ss%s\n' "$BOLD_GREEN" "$((SECONDS - started))" "$RESET"
done

# Computing the class and property hierarchies over millions of triples prints nothing
# for several minutes. Interrupting here leaves the load unfinished.
started=$SECONDS
info "registering inference rule set <${RULE_SET_URI}>"
info "  this takes several minutes with no output; please don't interrupt it"
isql_exec "DB.DBA.RDFS_RULE_SET ('${escaped_rule_set_uri}', '${escaped_rule_set_uri}');" >/dev/null
info "  done in $((SECONDS - started))s"

info "ontologies loaded ($(ontology_triple_count) triples)"
