#!/usr/bin/env bash
# Run LLM_ENGINE's SPHN retrieval server in its own dependency environment.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT/LLM_ENGINE"
exec uv run --locked --python 3.12 python scripts/serve_sphn_void.py \
  --void-file "$ROOT/schemas/void/sphn-schema-void.ttl" \
  --ontology "$ROOT/schemas/sphn/sphn_rdf_schema.ttl" "$@"
