#!/usr/bin/env bash
# Install/start local Ollama and prepare the model from models.json.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$ROOT/config/agents/models.json"
for command in curl python3; do
  command -v "$command" >/dev/null || { echo "Missing dependency: $command" >&2; exit 1; }
done

settings="$(python3 - "$CONFIG" <<'PY'
import json, sys
from urllib.parse import urlparse
with open(sys.argv[1], encoding="utf-8-sig") as source:
    config = json.load(source)
url = urlparse(config["base_url"])
if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1"} or url.path.rstrip("/") != "/v1" or url.username or url.password or url.query or url.fragment:
    sys.exit("base_url must be a local Ollama URL: http://localhost:11434/v1")
print(config["model"])
print(f"{url.hostname}:{url.port or 80}")
PY
)"
MODEL="${1:-${settings%%$'\n'*}}"
export OLLAMA_HOST="${settings#*$'\n'}"
URL="http://$OLLAMA_HOST"
LOG="$ROOT/artifacts/ollama/server.log"

if ! command -v ollama >/dev/null; then
  echo "Installing Ollama (requires root or sudo)..."
  curl -fsSL https://ollama.com/install.sh | sh
fi

if ! curl -fsS --max-time 2 "$URL/api/version" >/dev/null 2>&1; then
  mkdir -p "$(dirname "$LOG")"
  export OLLAMA_MODELS="${OLLAMA_MODELS:-$ROOT/artifacts/ollama/models}"
  nohup ollama serve >"$LOG" 2>&1 < /dev/null &
  pid=$!
  echo "$pid" > "$ROOT/artifacts/ollama/server.pid"
  for ((attempt=0; attempt<60; attempt++)); do
    if curl -fsS --max-time 2 "$URL/api/version" >/dev/null 2>&1; then break; fi
    if ! kill -0 "$pid" 2>/dev/null; then break; fi
    sleep 1
  done
  if ! curl -fsS --max-time 2 "$URL/api/version" >/dev/null 2>&1; then
    echo "Ollama failed to start. See $LOG" >&2
    exit 1
  fi
fi

ollama pull "$MODEL"
echo "Ollama ready at $URL — model: $MODEL"
