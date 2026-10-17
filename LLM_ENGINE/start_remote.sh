#!/usr/bin/env bash
# Start the current SPHN NL-to-SPARQL stack on ONE Vast.ai machine.
# Run from anywhere: ./start_remote.sh
# Services: vLLM/Qwen on 127.0.0.1:18000, local SPHN MCP on 127.0.0.1:18888.
# Does NOT run Virtuoso, Qdrant, or SPARQL execution.
set -Eeuo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VLLM_SESSION="sphn-qwen"
MCP_SESSION="sphn-mcp"
LOG_DIR="/workspace/logs"
MODEL_DIR="/workspace/models"
CONFIG="$APP_DIR/../config/agents/models.json"
VOID_FILE="$APP_DIR/metadata/sphn-schema-void.ttl"
# New starts use CUDA graphs and shared-prefix caching. Eager mode is an
# explicit fallback for GPU/version incompatibilities; existing services stay up.
VLLM_ENFORCE_EAGER="${VLLM_ENFORCE_EAGER:-0}"
VLLM_PREFIX_CACHING="${VLLM_PREFIX_CACHING:-1}"
[[ "$VLLM_ENFORCE_EAGER" =~ ^[01]$ && "$VLLM_PREFIX_CACHING" =~ ^[01]$ ]] || { echo "vLLM switches must be 0 or 1" >&2; exit 1; }

cd "$APP_DIR"

info() { printf '[INFO] %s\n' "$*"; }
fail() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

[[ -f pyproject.toml ]] || fail "Run this script from the LLM_ENGINE project (pyproject.toml must be next to it)."
[[ -f scripts/serve_sphn_void.py ]] || fail "Missing scripts/serve_sphn_void.py"
[[ -s "$VOID_FILE" ]] || fail "Missing/empty $VOID_FILE; copy it to the remote project before starting."
command -v tmux >/dev/null || fail "tmux missing. Install it once: apt-get update && apt-get install -y tmux"
command -v curl >/dev/null || fail "curl is required."
command -v ss >/dev/null || fail "ss (iproute2) is required to detect busy ports."

if command -v uv >/dev/null; then
  UV_BIN="$(command -v uv)"
elif [[ -x "$HOME/.local/bin/uv" ]]; then
  UV_BIN="$HOME/.local/bin/uv"
else
  fail "uv missing. Install once: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

mkdir -p "$LOG_DIR" "$MODEL_DIR" "$APP_DIR/results"

if [[ ! -d .venv ]]; then
  info "Installing MCP project dependencies..."
  "$UV_BIN" sync --locked --python 3.12
fi

# Read the same configuration used by the API, debugger, CLI and tests.
# Environment values below are derived for the standalone LLM_ENGINE CLI only.
settings="$(.venv/bin/python - "$CONFIG" <<'PY'
import json, sys
from urllib.parse import urlparse
from pathlib import Path
config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
model = config["model"]
if not isinstance(model, str) or not model.strip() or any(c in model for c in "\r\n"):
    sys.exit("model must be a nonempty single-line identifier")
print(model)
for key, path in (("base_url", "/v1"), ("mcp_url", "/mcp")):
    raw = config[key]
    url = urlparse(raw)
    if (url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1"}
            or url.path.rstrip("/") != path or url.username or url.password
            or url.query or url.fragment or any(c in raw for c in "\r\n")):
        sys.exit(f"{key} must be a local HTTP URL ending in {path}")
    print(raw.rstrip("/"))
    print(url.port or 80)
PY
)"
mapfile -t settings <<< "$settings"
MODEL="${settings[0]}"
LLM_URL="${settings[1]}"
LLM_PORT="${settings[2]}"
MCP_URL="${settings[3]}"
MCP_PORT="${settings[4]}"
export LLM_MODEL="$MODEL" LLM_BASE_URL="$LLM_URL" MCP_URL
export LLM_API_KEY="${MODEL_API_KEY:-local}"
export RETRIEVAL_BACKEND=sphn-void ENABLE_SPARQL_EXECUTION=false

if command -v vllm >/dev/null; then
  VLLM_BIN="$(command -v vllm)"
elif [[ -x /venv/main/bin/vllm ]]; then
  VLLM_BIN=/venv/main/bin/vllm
else
  fail "vllm not found. Use a Vast.ai vLLM image or install vLLM in its GPU environment."
fi

port_listening() {
  ss -ltn "( sport = :$1 )" | grep -Eq "[:.]$1[[:space:]]"
}

model_response() {
  curl -fsS --connect-timeout 2 --max-time 5 "$LLM_URL/models" 2>/dev/null
}

model_ready() {
  local result
  result="$(model_response)" || return 1
  [[ "$result" == *"$MODEL"* ]]
}

if model_ready; then
  info "Qwen already serving on $LLM_URL — not starting a second copy."
  info "Launch options are unchanged for this running service. To apply tuning, deliberately stop its owner/session and run again."
else
  if model_response >/dev/null; then
    fail "Port $LLM_PORT serves a different model. Stop it deliberately before starting $MODEL."
  fi

  if port_listening "$LLM_PORT" || pgrep -f '[v]llm serve' >/dev/null || tmux has-session -t "=$VLLM_SESSION" 2>/dev/null; then
    info "A vLLM process/session already exists and may still be loading; waiting without starting another."
  else
    info "Starting Qwen in tmux session '$VLLM_SESSION' (first startup can take several minutes)..."
    vllm_args=("$VLLM_BIN" serve "$MODEL"
      --host 127.0.0.1 --port "$LLM_PORT"
      --download-dir "$MODEL_DIR"
      --dtype float16
      --max-model-len 8192
      --max-num-seqs 1
      --gpu-memory-utilization 0.90
      --enable-auto-tool-choice
      --tool-call-parser hermes
      --default-chat-template-kwargs '{"enable_thinking": false}')
    if [[ "$VLLM_ENFORCE_EAGER" == 1 ]]; then vllm_args+=(--enforce-eager); fi
    if [[ "$VLLM_PREFIX_CACHING" == 1 ]]; then
      vllm_args+=(--enable-prefix-caching)
    else
      vllm_args+=(--no-enable-prefix-caching)
    fi
    printf -v command_str '%q ' "${vllm_args[@]}"
    printf '%s\n' "$command_str" > "$LOG_DIR/qwen30b-command.txt"
    info "vLLM eager=$VLLM_ENFORCE_EAGER prefix_caching=$VLLM_PREFIX_CACHING (launch command saved in $LOG_DIR/qwen30b-command.txt)"
    tmux new-session -d -s "$VLLM_SESSION" -c "$APP_DIR" \
      "exec $command_str >> '$LOG_DIR/qwen30b.log' 2>&1"
  fi

  info "Waiting for model readiness (up to 30 minutes)..."
  ready=0
  for ((i=0; i<360; i++)); do
    if model_ready; then ready=1; break; fi
    if model_response >/dev/null; then
      fail "A different model responded on port $LLM_PORT."
    fi
    if (( i % 12 == 0 )); then info "Qwen loading... (${i} x 5 s)"; fi
    sleep 5
  done
  if [[ "$ready" != 1 ]]; then
    tail -n 35 "$LOG_DIR/qwen30b.log" 2>/dev/null || true
    fail "Qwen did not become ready; inspect: tmux ls; tail -f $LOG_DIR/qwen30b.log; nvidia-smi"
  fi
  info "Qwen API ready."
fi

if port_listening "$MCP_PORT"; then
  info "Port $MCP_PORT already listening — will reuse it and verify with SPHN doctor."
elif pgrep -f '[s]erve_sphn_void.py' >/dev/null || tmux has-session -t "=$MCP_SESSION" 2>/dev/null; then
  info "SPHN MCP process/session already exists; waiting for it to listen."
else
  info "Starting SPHN VoID MCP in tmux session '$MCP_SESSION'..."
  tmux new-session -d -s "$MCP_SESSION" -c "$APP_DIR" \
    "exec '$UV_BIN' run --locked --python 3.12 python scripts/serve_sphn_void.py --void-file metadata/sphn-schema-void.ttl --port '$MCP_PORT' >> '$LOG_DIR/sphn-mcp.log' 2>&1"
fi

mcp_ready=0
for ((i=0; i<36; i++)); do
  if port_listening "$MCP_PORT"; then mcp_ready=1; break; fi
  sleep 5
done
if [[ "$mcp_ready" != 1 ]]; then
  tail -n 45 "$LOG_DIR/sphn-mcp.log" 2>/dev/null || true
  fail "SPHN MCP did not listen on $MCP_PORT; inspect $LOG_DIR/sphn-mcp.log"
fi

info "Checking SPHN retrieval tools (and model) through your agent..."
"$UV_BIN" run --locked --python 3.12 sparql-agent doctor --retrieval-backend sphn-void

cat <<DONE

READY: Qwen + SPHN VoID MCP + local agent are on the Vast.ai machine.

Run a sample query (using the shared configuration):
  cd ..
  uv run --extra local sparql-run --prompt 'How many patients are in the database?'

Useful inspection commands:
  tmux ls
  tail -f /workspace/logs/qwen30b.log
  tail -f /workspace/logs/sphn-mcp.log

Existing processes are reused, not restarted. For changed Python dependencies: uv sync.
No Virtuoso dataset or query execution is started by this script.
DONE
