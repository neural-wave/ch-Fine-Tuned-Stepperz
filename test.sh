#!/usr/bin/env bash
# Run the two projects locally, keeping their environments separate.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

WITH_MODELS=false
case "${1:-}" in
  "") ;;
  --with-models) WITH_MODELS=true ;;
  -h|--help)
    echo "Usage: bash test.sh [--with-models]"
    echo "Default: both offline suites, temporary MCP integration and XML reports."
    echo "--with-models: also run real inference; configured services must be running."
    exit 0 ;;
  *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
if (( $# > 1 )); then
  echo "Usage: bash test.sh [--with-models]" >&2
  exit 2
fi

# The main integration test needs the real server's isolated environment ready.
uv sync --locked --python 3.12 --project "$ROOT/LLM_ENGINE"
mkdir -p "$ROOT/artifacts/tests"
status=0
extras=(--extra agents --extra mcp --extra api)
if "$WITH_MODELS"; then extras+=(--extra local); fi
echo "Main suite and MCP integration (simulated inference)..."
uv run --locked --python 3.12 "${extras[@]}" --extra validation python -m pytest tests system_validation/tests \
  -m "not model_health" -q --junitxml=artifacts/tests/main.xml || status=1

echo "LLM_ENGINE offline suite..."
(
  cd "$ROOT/LLM_ENGINE"
  uv run --locked --python 3.12 python -m pytest tests -m "not live" -q \
    --junitxml="$ROOT/artifacts/tests/llm-engine.xml"
) || status=1

if "$WITH_MODELS"; then
  echo "Real model health checks explicitly enabled..."
  uv run --locked --python 3.12 --extra local python -m pytest tests/health \
    --run-model-health --model-config "${MODEL_CONFIG:-$ROOT/config/agents/models.json}" \
    -v --junitxml=artifacts/tests/model-health.xml || status=1
fi
echo "Reports: $ROOT/artifacts/tests/ (reports are updated only for executed suites)"
exit "$status"
