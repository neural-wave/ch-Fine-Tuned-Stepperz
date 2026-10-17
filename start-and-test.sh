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

# Match the stack's configuration, preserving the chosen Laya settings.
# Keep models.json unchanged and never copy API keys into the generated config.
export MODEL_CONFIG="$ROOT/artifacts/tests/models.remote.json"
mkdir -p "$(dirname "$MODEL_CONFIG")"
"$ROOT/LLM_ENGINE/.venv/bin/python" - "$ROOT" "$MODEL_CONFIG" <<'PY'
import json
from pathlib import Path
import sys
from sparql_agent.config import Config

root = Path(sys.argv[1])
remote = Config.from_env(root / 'LLM_ENGINE/.env.remote')
config = json.loads((root / 'config/agents/models.json').read_text(encoding='utf-8-sig'))
config.update(base_url=remote.llm_base_url, model=remote.llm_model, mcp_url=remote.mcp_url)
config.pop('mcp_settings', None)
Path(sys.argv[2]).write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
print(f'Health checks: {remote.llm_model} at {remote.llm_base_url}; MCP {remote.mcp_url}')
PY

.venv/bin/python -m agent_orchestration --config "$MODEL_CONFIG" --check-mcp
bash "$ROOT/test.sh" --with-models
