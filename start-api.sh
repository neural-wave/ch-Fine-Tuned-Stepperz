#!/usr/bin/env bash
# Start only the REST API. Qwen/vLLM and the shared MCP must already be ready.
set -Eeuo pipefail
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"
if [[ "${1:-}" == --help ]]; then
  echo 'Usage: bash start-api.sh [uvicorn options]'
  echo 'Config: NL2SPARQL_CONFIG (optional). Bind: --host ADDRESS --port NUMBER.'
  exit 0
fi
if command -v uv >/dev/null; then
  UV_BIN="$(command -v uv)"
elif [[ -x "$HOME/.local/bin/uv" ]]; then
  UV_BIN="$HOME/.local/bin/uv"
else
  echo 'uv is required.' >&2
  exit 1
fi
exec "$UV_BIN" run --locked --extra local --extra api python -m uvicorn api.server:app  --host 0.0.0.0 --port 10100

