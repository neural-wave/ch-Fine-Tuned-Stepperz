# Run the SPHN agent entirely on Vast.ai

The application, SPHN VoID MCP server, and Qwen3-30B all run **on the same Vast.ai machine**. No Windows-to-model SSH tunnel is needed.

```text
Vast.ai RTX 3090
├── vLLM / Qwen3-30B    http://127.0.0.1:18000/v1
├── SPHN VoID MCP       http://127.0.0.1:18888/mcp
│   └── metadata/sphn-schema-void.ttl
└── sparql-agent CLI   calls both local services
```

**Assumptions:** You have SSH access to Vast.ai and have already cloned `neural-wave/ch-Fine-Tuned-Stepperz` there. The steps below run in the **Vast.ai Bash terminal**, not Windows PowerShell. The current pipeline generates SPARQL offline; it does **not** start Virtuoso, load clinical data, or execute queries.

## 1. Python environment and remote configuration

Go to the directory containing the agent's `pyproject.toml`:

```bash
cd /workspace/ch-Fine-Tuned-Stepperz
find . -name pyproject.toml
cd codebase/LLM_ENGINE
```

If `find` shows a different layout, adjust the final `cd` accordingly.

Install `uv` if needed, then install project dependencies:

```bash
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv sync
```

Check required files:

```bash
ls -lh metadata/sphn-schema-void.ttl
ls -lh scripts/serve_sphn_void.py
```

Both files must exist on the **remote** filesystem. Create a remote-only environment file:

```bash
cat > .env.remote <<'EOF_ENV'
LLM_BASE_URL=http://127.0.0.1:18000/v1
LLM_MODEL=Qwen/Qwen3-30B-A3B-GPTQ-Int4
LLM_API_KEY=EMPTY
MCP_URL=http://127.0.0.1:18888/mcp
RETRIEVAL_BACKEND=sphn-void
ENABLE_SPARQL_EXECUTION=false
EOF_ENV
chmod 600 .env.remote
```

Keep `.env.remote` out of Git. Pass `--env-file .env.remote` **before** the CLI subcommand (`doctor` or `ask`).

## 2. Qwen3-30B: verify or start vLLM

First, check whether Qwen is **already running**:

```bash
curl -fsS --max-time 5 http://127.0.0.1:18000/v1/models
nvidia-smi
```

If the response contains `Qwen/Qwen3-30B-A3B-GPTQ-Int4`, **skip the startup commands**. Do not launch a second vLLM server.

If it is not responding, check for an existing or still-initializing process:

```bash
ps -ef | grep -E '[v]llm|[E]ngineCore'
ss -ltnp | grep ':18000' || true
nvidia-smi
```

Only if no instance is already active and the GPU is available, launch Qwen in a persistent `tmux` session:

```bash
mkdir -p /workspace/models /workspace/logs
command -v tmux || (apt-get update && apt-get install -y tmux)
tmux new -s qwen
```

**Inside `tmux`:**

```bash
vllm serve Qwen/Qwen3-30B-A3B-GPTQ-Int4 \
  --host 127.0.0.1 --port 18000 \
  --download-dir /workspace/models \
  --dtype float16 \
  --max-model-len 8192 \
  --max-num-seqs 1 \
  --gpu-memory-utilization 0.90 \
  --enforce-eager \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --default-chat-template-kwargs '{"enable_thinking": false}' \
  2>&1 | tee /workspace/logs/qwen30b.log
```

Startup may take several minutes. To detach without stopping the process, press **Ctrl+B**, then **D**. To inspect it later:

```bash
tmux attach -t qwen
```

Verify readiness from another SSH terminal:

```bash
curl -fsS http://127.0.0.1:18000/v1/models
```

If Qwen was started earlier **outside `tmux`**, keep its original terminal open until you deliberately migrate it to persistent service management.

## 3. SPHN MCP: serve the VoID locally on Vast.ai

Open a **second SSH terminal**, or another `tmux` session. Navigate to the agent folder:

```bash
cd /workspace/ch-Fine-Tuned-Stepperz/codebase/LLM_ENGINE
uv run python scripts/serve_sphn_void.py --help
```

Verify `--void-file` is supported. Then start the MCP server in its own `tmux` session:

```bash
tmux new -s sphn-mcp
```

**Inside `tmux`:**

```bash
cd /workspace/ch-Fine-Tuned-Stepperz/codebase/LLM_ENGINE
mkdir -p /workspace/logs
uv run python scripts/serve_sphn_void.py \
  --void-file metadata/sphn-schema-void.ttl \
  2>&1 | tee /workspace/logs/sphn-mcp.log
```

Detach with **Ctrl+B**, then **D**. MCP should listen on `http://127.0.0.1:18888/mcp`.

Check that the port is listening:

```bash
ss -ltnp | grep ':18888'
```

A plain `curl` to `/mcp` is **not** a reliable MCP health test; use `doctor --mcp-only` below.

## 4. End-to-end remote tests

From a normal SSH terminal in the `LLM_ENGINE` directory, check both service ports:

```bash
curl -fsS http://127.0.0.1:18000/v1/models
ss -ltnp | grep -E ':18000|:18888'
```

**Test SPHN-specific MCP tools:**

```bash
uv run sparql-agent --env-file .env.remote doctor \
  --retrieval-backend sphn-void \
  --mcp-only
```

Expected: `search_sparql_examples` and `search_sparql_classes` are `ok: true`, with MCP URL `http://127.0.0.1:18888/mcp`—not the public UniProt/Expasy server.

**Test the full LLM + MCP connection:**

```bash
uv run sparql-agent --env-file .env.remote doctor \
  --retrieval-backend sphn-void
```

**Generate a simple SPHN query:**

```bash
uv run sparql-agent --env-file .env.remote ask \
  'How many distinct patients have an oncology diagnosis?' \
  --mode deterministic \
  --retrieval-backend sphn-void \
  --classes OncologyDiagnosis SubjectPseudoIdentifier
```

**Generate the cancer-treatment query in autonomous mode:**

```bash
uv run sparql-agent --env-file .env.remote ask \
  'Once someone is diagnosed with cancer, what usually happens next: surgery, radiotherapy, both, or nothing? And how long do they typically wait for their first treatment?' \
  --mode autonomous \
  --retrieval-backend sphn-void
```

Queries (`.rq`) and traces (`.json`) are saved in `results/`. The quoted question is placed **before** `--classes` because that option consumes subsequent arguments. Do not use `--question`: the question is positional.

**Important:** `Status: success` / `syntax valid: True` confirms only that the pipeline generated parseable SPARQL; it does **not** establish clinical correctness, execution success, or privacy compliance.
