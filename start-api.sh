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

# Explicit defaults prevent image-provided UVICORN_HOST/PORT from silently
# changing the listener. User arguments still take precedence.
port=8000
arguments=("$@")
for ((index=0; index<${#arguments[@]}; index++)); do
  case "${arguments[index]}" in
    --port) port="${arguments[index+1]:-}" ;;
    --port=*) port="${arguments[index]#--port=}" ;;
  esac
done
if [[ ! "$port" =~ ^[0-9]+$ ]] || (( 10#$port < 1 || 10#$port > 65535 )); then
  echo 'Specify a TCP port between 1 and 65535 with --port.' >&2
  exit 2
fi
if command -v ss >/dev/null && [[ -n "$(ss -H -ltn "( sport = :$port )")" ]]; then
  echo "Port $port already has a listener. Models have not been loaded." >&2
  ss -ltnp "( sport = :$port )" >&2
  echo 'Choose a free internal port with --port, or inspect the existing service.' >&2
  exit 1
fi
# Keep the project's locked environment, even inside an activated GPU venv.
unset VIRTUAL_ENV
exec "$UV_BIN" run --locked --extra local --extra api python -m uvicorn api.server:app \
  --host 127.0.0.1 --port 8000 "$@"
