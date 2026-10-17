#!/usr/bin/env bash
# Start the current SPHN NL-to-SPARQL stack on ONE Vast.ai machine.
# Run from anywhere: ./start_remote.sh
# Services: vLLM/Qwen on 127.0.0.1:18000, local SPHN MCP on 127.0.0.1:18888.
# Does NOT run Virtuoso, Qdrant, or SPARQL execution.
set -Eeuo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MODEL="Qwen/Qwen3-30B-A3B-GPTQ-Int4"
LLM_URL="http://127.0.0.1:18000/v1"
MCP_URL="http://127.0.0.1:18888/mcp"
VLLM_SESSION="sphn-qwen"
MCP_SESSION="sphn-mcp"
LOG_DIR="/workspace/logs"
MODEL_DIR="/workspace/models"
ENV_FILE="$APP_DIR/.env.remote"
VOID_FILE="$APP_DIR/metadata/sphn-schema-void.ttl"

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

# Don't overwrite a user-customized environment on later starts.
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<'ENV'
LLM_BASE_URL=http://127.0.0.1:18000/v1
LLM_MODEL=Qwen/Qwen3-30B-A3B-GPTQ-Int4
LLM_API_KEY=EMPTY
MCP_URL=http://127.0.0.1:18888/mcp
RETRIEVAL_BACKEND=sphn-void
ENABLE_SPARQL_EXECUTION=false
ENV
  chmod 600 "$ENV_FILE"
  info "Created .env.remote with remote loopback addresses."
fi

# Validate critical settings, so an old Windows tunnel address cannot be used accidentally.
for required in \
  'LLM_BASE_URL=http://127.0.0.1:18000/v1' \
  'LLM_MODEL=Qwen/Qwen3-30B-A3B-GPTQ-Int4' \
  'MCP_URL=http://127.0.0.1:18888/mcp' \
  'ENABLE_SPARQL_EXECUTION=false'; do
  grep -Fxq "$required" "$ENV_FILE" || fail ".env.remote must contain: $required"
done

if [[ ! -d .venv ]]; then
  info "Installing project dependencies with uv sync (first run)..."
  "$UV_BIN" sync
else
  info "Reusing existing .venv (run 'uv sync' after pulling changed dependencies)."
fi

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
else
  if model_response >/dev/null; then
    fail "Port 18000 serves a different model. Stop it deliberately before starting $MODEL."
  fi

  if port_listening 18000 || pgrep -f '[v]llm serve' >/dev/null || tmux has-session -t "=$VLLM_SESSION" 2>/dev/null; then
    info "A vLLM process/session already exists and may still be loading; waiting without starting another."
  else
    info "Starting Qwen in tmux session '$VLLM_SESSION' (first startup can take several minutes)..."
    vllm_args=("$VLLM_BIN" serve "$MODEL"
      --host 127.0.0.1 --port 18000
      --download-dir "$MODEL_DIR"
      --dtype float16
      --max-model-len 8192
      --max-num-seqs 1
      --gpu-memory-utilization 0.90
      --enforce-eager
      --enable-auto-tool-choice
      --tool-call-parser hermes
      --default-chat-template-kwargs '{"enable_thinking": false}')
    printf -v command_str '%q ' "${vllm_args[@]}"
    tmux new-session -d -s "$VLLM_SESSION" -c "$APP_DIR" \
      "exec $command_str >> '$LOG_DIR/qwen30b.log' 2>&1"
  fi

  info "Waiting for model readiness (up to 15 minutes)..."
  ready=0
  for ((i=0; i<180; i++)); do
    if model_ready; then ready=1; break; fi
    if model_response >/dev/null; then
      fail "A different model responded on port 18000."
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

if port_listening 18888; then
  info "Port 18888 already listening — will reuse it and verify with SPHN doctor."
elif pgrep -f '[s]erve_sphn_void.py' >/dev/null || tmux has-session -t "=$MCP_SESSION" 2>/dev/null; then
  info "SPHN MCP process/session already exists; waiting for it to listen."
else
  info "Starting SPHN VoID MCP in tmux session '$MCP_SESSION'..."
  tmux new-session -d -s "$MCP_SESSION" -c "$APP_DIR" \
    "exec '$UV_BIN' run python scripts/serve_sphn_void.py --void-file metadata/sphn-schema-void.ttl >> '$LOG_DIR/sphn-mcp.log' 2>&1"
fi

mcp_ready=0
for ((i=0; i<36; i++)); do
  if port_listening 18888; then mcp_ready=1; break; fi
  sleep 5
done
if [[ "$mcp_ready" != 1 ]]; then
  tail -n 45 "$LOG_DIR/sphn-mcp.log" 2>/dev/null || true
  fail "SPHN MCP did not listen on 18888; inspect $LOG_DIR/sphn-mcp.log"
fi

info "Checking SPHN retrieval tools (and model) through your agent..."
"$UV_BIN" run sparql-agent --env-file "$ENV_FILE" doctor --retrieval-backend sphn-void

cat <<'DONE'

READY: Qwen + SPHN VoID MCP + local agent are on the Vast.ai machine.

Run a sample query (from the LLM_ENGINE directory):
  uv run sparql-agent --env-file .env.remote ask \
    'How many distinct patients have an oncology diagnosis?' \
    --mode deterministic --retrieval-backend sphn-void \
    --classes OncologyDiagnosis SubjectPseudoIdentifier

Useful inspection commands:
  tmux ls
  tail -f /workspace/logs/qwen30b.log
  tail -f /workspace/logs/sphn-mcp.log

Existing processes are reused, not restarted. For changed Python dependencies: uv sync.
No Virtuoso dataset or query execution is started by this script.
DONE
