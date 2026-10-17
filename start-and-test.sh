#!/usr/bin/env bash
# Reuse LLM_ENGINE's vLLM + SPHN MCP startup, then test the same services.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash start-and-test.sh"
  echo "Linux VM: run LLM_ENGINE/start_remote.sh (vLLM + MCP), then both suites and real health checks."
  echo "Requires uv and the prerequisites of start_remote.sh (tmux, curl, ss, vLLM)."
  echo "Services remain running. No Ollama is installed or started."
  exit 0
fi
if (( $# )); then echo "Usage: bash start-and-test.sh" >&2; exit 2; fi
if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Run this script on the Linux VM." >&2
  exit 1
fi

uv sync --locked --python 3.12 --extra local
uv sync --locked --python 3.12 --project "$ROOT/LLM_ENGINE"
bash "$ROOT/LLM_ENGINE/start_remote.sh"

# API, debugger, CLI and health checks share the tracked configuration.
export MODEL_CONFIG="$ROOT/config/agents/models.json"
.venv/bin/python -m agent_orchestration --check-mcp
bash "$ROOT/test.sh" --with-models
