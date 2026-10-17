# SIB MCP + Qwen SPARQL Agent

> **Scope:** this is a separate experimental project with its own `pyproject.toml`,
> dependencies and configuration. Its `sparql-agent` / `sparql-benchmark` commands
> are different from the main project's `sparql-run` / `sparql-check`.
> Start from the [repository command guide](../docs/guides/commands.md) to choose
> a workflow. This prototype does not route queries through the main verified
> RDFLib runtime. Deployment details below are session records, not live checks.

The main workflow now reuses this project's SPHN VoID server over HTTP.
From the repository root, run `bash start-mcp.sh`; in another terminal run
`uv run --extra agents --extra mcp sparql-run --check-mcp`.
The script starts `scripts/serve_sphn_void.py` in this project's isolated
environment with the shared files under the root `schemas/` directory.
The default URL is `http://127.0.0.1:18888/mcp`. Only schema/example retrieval
is shared; the main workflow retains its prompt guard and checked execution.
The UniProt compose and this prototype's LLM settings are not selected automatically.

> **Latest session, 17 Oct 2026:** `Qwen/Qwen3-30B-A3B-GPTQ-Int4` is deployed on the new **RTX 4090 24 GB** instance. See section 9 for the current connection and commands; sections 1–8 retain the earlier 9B baseline. The larger model did not improve correctness on the three-question comparison. Only clinical example 1 ran; approval for the full clinical benchmark was rejected.

A small, reproducible **natural-language → SPARQL** prototype. A Python CLI calls a Qwen model through an OpenAI-compatible endpoint, retrieves SPARQL examples/schema information through the public SIB MCP server, and saves the generated query plus timing/token metrics.

This is an **experimental prototype**, not yet a complete SPHN hackathon submission. The current smoke tests use **UniProt**, not the mocked SPHN clinical dataset. In particular, SPARQL syntax validation is **not** equivalent to endpoint-schema correctness, semantic correctness, or privacy compliance. See [results.md](results.md) for measured outcomes.

## 1. Architecture

```text
Windows / project CLI
    |
    +-- SIB MCP (HTTPS): https://chat.expasy.org/mcp/
    |      +-- search_sparql_examples
    |      +-- search_sparql_classes
    |      +-- execute_sparql_query (separate, opt-in)
    |
    +-- OpenAI-compatible HTTP client
           |
           +-- localhost:18080/v1 (SSH tunnel on Windows)
                 |
                 +-- Vast.ai RTX 3090 / vLLM
                       +-- Qwen/Qwen3.5-9B
```

Two generation modes:

- **`deterministic`**: the application retrieves relevant SPARQL examples first, then asks the model to produce a query. Optional class hints can be supplied using `--classes`.
- **`autonomous`**: the model decides whether/when to invoke MCP retrieval tools, potentially over multiple model iterations.

Generation does **not** execute queries by default. Query execution is a separate CLI action.

## 2. Observed working environment

| Component | Configuration actually tested |
| --- | --- |
| Local client | Windows PowerShell, Python >= 3.11, `uv` |
| Project | `ch-Fine-Tuned-Stepperz`, Python package `sparql_agent` |
| Remote GPU | Vast.ai instance with **NVIDIA RTX 3090 (24 GB)** |
| LLM server | vLLM, OpenAI-compatible API |
| Tested model | `Qwen/Qwen3.5-9B` |
| Remote server address | `127.0.0.1:18000` **inside** Vast.ai |
| Windows forwarding address | `http://127.0.0.1:18080/v1` |
| Retrieval tools | Public SIB MCP server: `https://chat.expasy.org/mcp/` |
| Output | SPARQL `.rq` files and JSON records under `results/` |

**Current operational note (17 Oct 2026):** the previously working 9B vLLM process was terminated while attempting a 14B comparison. A later 14B startup failed. **Do not assume a model is currently running.** Verify the remote API before running the local agent.

## 3. Setup / restore a session

### A. Install local dependencies

In PowerShell:

```powershell
cd C:\Users\manue\Desktop\MyProjects\NEURAL_WAVE_2026\ch-Fine-Tuned-Stepperz
uv sync
uv run sparql-agent --help
```

The project exposes two installed entry points:

```text
sparql-agent      # ask, doctor, tools, execute
sparql-benchmark  # compare retrieval modes over a question set
```

### B. Check or restore the model on Vast.ai

Connect to your Vast.ai SSH instance. The prior instance used `root@108.240.82.27` on SSH port `56482`; **these values may change** if the instance is restarted/replaced.

Check server state **in the Vast SSH terminal**:

```bash
nvidia-smi
ps aux | grep -E '[v]llm|[E]ngineCore'
ss -ltnp | grep ':18000' || echo 'Port 18000 is free'
curl -s http://127.0.0.1:18000/v1/models
```

If the original Vast vLLM template is running, **do not start a second model**. It previously launched Qwen3.5-9B with the following command (recorded from the process list):

```bash
vllm serve Qwen/Qwen3.5-9B \
  --max-num-seqs 8 \
  --max-model-len 32000 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  --download-dir /workspace/models \
  --host 127.0.0.1 \
  --port 18000 \
  --tensor-parallel-size 1 \
  --compilation-config '{"cudagraph_capture_sizes": [1,2,3,4,5,6,7,8]}'
```

This documents the **previously observed working process**, not a guarantee that manual startup will work on every vLLM image/version. If restoring the Vast template is easier, use that rather than running competing servers. Wait until `curl .../v1/models` confirms `Qwen/Qwen3.5-9B`.

### C. Open the Windows SSH tunnel

**In a separate PowerShell terminal** (keep it open):

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 18080:127.0.0.1:18000 -p 56482 root@108.240.82.27
```

Replace the SSH address/port if Vast assigned new ones. The mapping is **Windows port 18080 → remote port 18000**.

Verify from another Windows PowerShell terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:18080/v1/models
```

This must report the model that you intend to benchmark.

### D. Configure the local CLI

Use `.env` for persistent settings (start with `.env.example` if needed):

```dotenv
LLM_BASE_URL=http://127.0.0.1:18080/v1
LLM_MODEL=Qwen/Qwen3.5-9B
LLM_API_KEY=EMPTY
LLM_TEMPERATURE=0
MCP_URL=https://chat.expasy.org/mcp/
MAX_AGENT_ITERATIONS=5
ENABLE_SPARQL_EXECUTION=false
```

If an existing shell or `.env` still selects local Ollama (`qwen3:1.7b` at `localhost:11434`), explicitly override the model **in the PowerShell terminal where you run the CLI**:

```powershell
$env:LLM_BASE_URL = 'http://127.0.0.1:18080/v1'
$env:LLM_MODEL = 'Qwen/Qwen3.5-9B'
$env:LLM_API_KEY = 'EMPTY'
$env:ENABLE_SPARQL_EXECUTION = 'false'
```

**Always check the effective configuration** with `doctor`; simply changing `.env` is not proof that the desired model is selected.

## 4. Everyday commands

Run from the repository root in PowerShell.

### Connectivity and tools

```powershell
uv run sparql-agent doctor
uv run sparql-agent tools
```

The successful remote `doctor` run showed model `Qwen/Qwen3.5-9B`, working MCP discovery, and successful `search_sparql_examples` and `search_sparql_classes` calls.

### Ask a natural-language question

```powershell
uv run sparql-agent ask --mode deterministic "Write a SPARQL query to retrieve human proteins encoded by the LCT gene from UniProt."

uv run sparql-agent ask --mode autonomous "Write a SPARQL query to retrieve human proteins encoded by the LCT gene from UniProt."
```

To receive the full machine-readable record:

```powershell
uv run sparql-agent ask --mode deterministic --json "List human proteins encoded by the LCT gene in UniProt."
```

The CLI prints status, syntax validity, elapsed time, token usage, tools called, and saved result paths (one `.json`, one `.rq`). Do not interpret `syntax valid: True` as proof that the query answers the question.

### Benchmark both modes

```powershell
uv run sparql-benchmark --limit 3 --repeats 1 --warmups 0 --modes deterministic autonomous
```

Or save to a specific output path:

```powershell
uv run sparql-benchmark --limit 3 --repeats 1 --warmups 0 --modes deterministic autonomous --model Qwen/Qwen3.5-9B --output results\qwen35-9b-recheck.jsonl
```

Available benchmark options include `--questions`, `--modes`, `--repeats`, `--warmups`, `--limit`, `--with-classes`, `--model`, `--env-file`, and `--output`. For more stable comparisons, repeat runs and include warmups; the initial results used **three questions, one measured run per mode, no warmups**.

### Execute a saved query (explicit opt-in)

The command accepts **one path to a `.rq` file**. For example, the manually corrected UniProt query was saved as `results\lct_human_fixed.rq`:

```powershell
$env:ENABLE_SPARQL_EXECUTION = 'true'
uv run sparql-agent execute 'results\lct_human_fixed.rq'
$env:ENABLE_SPARQL_EXECUTION = 'false'
```

Only enable execution for an **approved endpoint/query**. In these tests, the `.rq` files included a `#+ endpoint: https://sparql.uniprot.org/sparql/` header, and the SIB execution tool checked endpoint schema before execution. This is **not** the hackathon's clinical-data privacy checker; observed execution output explicitly said `compliance_checked: false`.

## 5. Switching or comparing models

1. Stop the previous model **and its inference engine**. Verify both processes and GPU memory are gone.
2. Start exactly one vLLM model on the remote GPU.
3. Confirm its exact ID using remote `/v1/models` (and Windows `/v1/models` through the tunnel).
4. Change `$env:LLM_MODEL` (and `LLM_BASE_URL` if the port/tunnel changed).
5. Run `uv run sparql-agent doctor` **before** benchmarking.
6. Run the same questions, modes, repeats and warmups as the baseline; record query execution and semantic correctness separately.

**Attempted, not benchmarked:** `Qwen/Qwen3-14B-AWQ`. Its startup failed, so no model-to-model performance result is available. See [results.md](results.md).

## 6. Troubleshooting

| Symptom | Check / action |
| --- | --- |
| `doctor` shows `qwen3:1.7b` and `localhost:11434` | This is local Ollama, not Vast. Set `LLM_BASE_URL` and `LLM_MODEL` in the current PowerShell session. |
| Windows `localhost:18080` fails | Check SSH tunnel is open and remote `curl http://127.0.0.1:18000/v1/models` works. |
| `Address already in use` on port 18000 | Inspect `ss -ltnp \| grep ':18000'`; don't run a second API server. |
| GPU memory remains near 20 GB after stopping server | Inspect `ps aux \| grep -E '[v]llm\|[E]ngineCore'`; the inference engine may still be alive. The Vast container may show no processes in `nvidia-smi` even while memory is occupied. |
| `Engine core initialization failed` | This is a wrapper error. Inspect **earlier** engine logs for the root cause (OOM, incompatible configuration, loader error, etc.). Changing ports alone does not release GPU memory. |
| Query parses but `execute` fails | Read the SIB endpoint-schema error. Generated predicates may not exist or may be attached to the wrong classes. |
| Query executes but has extra/missing results | Verify it encodes **all** natural-language constraints; schema and syntax checks cannot establish full semantic correctness. |
| Output says `truncated: true` | Response was truncated by the client; it is not necessarily a database failure. |

To avoid GPU hosting charges between work sessions, **stop the Vast.ai instance when you are finished**, following Vast's billing controls.

## 7. Hackathon target vs. prototype status

The SIB/SPHN hackathon requires **SPHN schema 2026.1**, mocked clinical RDF, a compliant SPARQL generator, and a compliance-decision component. It also specifies `POST /nl-to-sparql` returning the query and total tokens. The current code documented here is a **CLI prototype**; a compliant REST endpoint, the full organizer-provided rule set, and Virtuoso evaluation have **not** been demonstrated.

The provided hackathon brief gives example privacy constraints (no single identifiable patient, aggregate-only outputs, no unrestricted whole-graph matching) and says the **complete minimal constraint set is supplied with the dataset**. Do not treat those examples as an exhaustive implementation specification. Keep restricted terminologies/datasets within their permitted hackathon use; do not send sensitive data to a public third-party MCP service.

**Evaluation priorities:** time to produce a compliant query (including checking/repair), correct compliance verdicts in both directions, and query execution time averaged over 10 isolated runs. Token usage and model size are secondary considerations.

## 8. Project pointers

- Results: [results.md](results.md)
- Local commands: `uv run sparql-agent --help`, `uv run sparql-agent ask --help`, `uv run sparql-benchmark --help`
- SIB MCP reference: <https://github.com/sib-swiss/sparql-llm>
- SIB curated examples: <https://github.com/sib-swiss/sparql-examples>
- SPHN schema: <https://biomedit.ch/rdf/sphn-schema/sphn>
- Hackathon problem statement: `SPHN Hackathon Secure NL-to-SPARQL over Clinical Knowledge Graphs-1-1.pdf` (organizer-provided)

## 9. Current Qwen3-30B-A3B-GPTQ-Int4 deployment

The new host is `root@79.112.26.222`, SSH port `48453`. Its actual GPU is an **RTX 4090**, not the expected 3090. The exact checkpoint revision is `9b534e4318b7ebc3c961a839f13eb18b1833f441`. Installed software: vLLM 0.30.0, PyTorch 2.13.0+cu130, Transformers 5.17.0, Python 3.12. The model has about 30B total / 3B active parameters and GPTQ 4-bit weights.

The deployment uses 0.85 GPU memory utilization, one sequence, eager execution, float16 activations, the `hermes` tool parser, thinking disabled, and `127.0.0.1:18000`. Startup succeeded at 4096 context tokens, but three benchmark requests exceeded the input-plus-output budget. **8192 is the tested working context.** No package upgrades or replacement models were used.

### Connect and manage the server

```powershell
# The supplied 8080 mapping reaches Jupyter. Add the separate model API mapping:
ssh -p 48453 root@79.112.26.222 -L 8080:localhost:8080 -L 18080:127.0.0.1:18000

# Or run an API-only tunnel if port 8080 is already forwarded:
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:18080:127.0.0.1:18000 -p 48453 root@79.112.26.222
```

The helper is uploaded as `/workspace/deploy_qwen30b.py`. In the remote shell:

```bash
/venv/main/bin/python /workspace/deploy_qwen30b.py inspect
/venv/main/bin/python /workspace/deploy_qwen30b.py start
/venv/main/bin/python /workspace/deploy_qwen30b.py stop

# Controlled context change; the service must be stopped first:
/venv/main/bin/python /workspace/deploy_qwen30b.py stop
/venv/main/bin/python /workspace/deploy_qwen30b.py set-context --context 8192
/venv/main/bin/python /workspace/deploy_qwen30b.py start

curl -s http://127.0.0.1:18000/v1/models
nvidia-smi
supervisorctl status qwen30b-prototype
```

Full startup logs are saved on Vast under `/workspace/qwen30b-prototype/logs/`. The launcher is `/workspace/qwen30b-prototype/serve.sh`, supervised as `qwen30b-prototype`, with automatic restart disabled to avoid repeated failed downloads/startups. Initial inspection and previous 9B launch records are in timestamped subdirectories of the same directory. Copying full startup logs to this computer was rejected by the approval system; local diagnostics and benchmark logs are in `results/qwen30b-deployment/`.

For a fresh instance, upload `scripts/deploy_qwen30b.py`, inspect the host, then run `install --context 8192` and `start`. The explicit `--remove-9b-cache` option deletes only the named 9B cache and its unshared blobs; use it only with permission. It was authorized and used in this session to free disk space. Restoring 9B requires another download. The previous template service `vllm` is stopped but retains its original boot configuration: after an instance reboot, inspect it before starting the prototype. Do not start competing models.

### Run the existing agent

The ignored `.env` and `.env.example` now select the new model. The PowerShell profile also overrides stale shell variables:

```powershell
. .\scripts\use_vast.ps1
Invoke-RestMethod http://127.0.0.1:18080/v1/models
uv run python scripts/smoke_vllm.py --output results/api-smoke-new-session.json
uv run sparql-agent doctor
uv run sparql-agent ask --mode deterministic "Write a SPARQL query to retrieve human proteins encoded by the LCT gene from UniProt."
uv run sparql-agent ask --mode autonomous "Write a SPARQL query to retrieve human proteins encoded by the LCT gene from UniProt."
uv run sparql-benchmark --limit 3 --repeats 1 --warmups 0 --modes deterministic autonomous --output results/new-session-paired.jsonl
uv run sparql-benchmark --limit 3 --repeats 3 --warmups 1 --modes deterministic autonomous --output results/new-session-repeated.jsonl
```

Choose new output names; scripts refuse to overwrite benchmark files. `smoke_vllm.py` verifies the exact model and parses a native `tool_choice=auto` response through the existing Python adapter. UniProt benchmarks use the unchanged public SIB MCP pipeline. Execution is still a separate, opt-in CLI command.

### SPHN examples: separate local retrieval diagnostic

The supplied schema URL is an ontology, not an MCP endpoint. Its downloaded version was verified as **2026.1**. Local inputs are preserved under `data/sphn/`: `sphn-2026.1.ttl` and `queries-example.md`. To fetch the schema again:

```powershell
Invoke-WebRequest -Uri 'https://biomedit.ch/rdf/sphn-schema/sphn' -Headers @{Accept='text/turtle'} -OutFile data/sphn/sphn-2026.1.ttl
```

`scripts/benchmark_sphn.py` temporarily serves two retrieval tools on loopback port 18888 using the existing MCP SDK. It reuses the unchanged agent/client and performs lexical retrieval over 239 OWL class summaries and organizer examples 1–10. **Each evaluated example is excluded from the retrieval corpus server-side.** Deterministic mode also retrieves three class hints selected from the question; autonomous mode chooses its own tools. This is a local adapter, not the SIB public vector index or a complete clinical retrieval system.

```powershell
. .\scripts\use_vast.ps1
# Completed in this session:
uv run python scripts/benchmark_sphn.py --examples data/sphn/queries-example.md --schema data/sphn/sphn-2026.1.ttl --output results/sphn-new-smoke --limit 1

# Prepared but NOT executed: approval for the 15-example run was rejected.
uv run python scripts/benchmark_sphn.py --examples data/sphn/queries-example.md --schema data/sphn/sphn-2026.1.ttl --output results/sphn-new-full
```

The adapter has **no execution tool**. `http://example.invalid/sphn/sparql` is only a generated-query label, not a database. Ontology imports/terminology graphs are not downloaded. The `shex` compatibility field contains a readable OWL restriction summary, not formal ShEx. RDFLib cannot validate Virtuoso's `OPTION (inference ...)` extension; syntax failures there must be distinguished from invalid Virtuoso syntax. The clinical privacy checker remains unimplemented, including for examples 11–15.

The server and SSH tunnel were left running at the last successful observation. Stop `qwen30b-prototype` when inference is no longer needed; stopping the GPU instance itself is a separate Vast billing action.

## 10. Local SPHN VoID retrieval backend

For the main application's `prefetch`/`agentic` comparison and the new-start
vLLM CUDA/prefix-cache options in `start_remote.sh`, see the
[inference performance guide](../docs/guides/inference-performance.md).
Existing processes keep their launch options until deliberately restarted.

The SPHN-only backend reads `metadata/sphn-schema-void.ttl` offline. It uses SIB's `get_schema_for_endpoint()` when its optional dependencies are installed, with an RDFLib parser for the same VoID relationships otherwise. The MCP adapter indexes SPHN class/predicate descriptions and schema-derived aggregate query patterns in memory. It never reads the 15 benchmark reference queries; privacy counterexamples 11–15 are not indexed. The patterns are starting points, not validated clinical or privacy-compliant queries. No Virtuoso or other data endpoint is contacted.

Start the retrieval-only adapter in one terminal:

```powershell
.\.venv\Scripts\python.exe scripts\serve_sphn_void.py
```

Then select it explicitly in another terminal. The flag forces the loopback MCP URL, the placeholder SPHN target label, and disabled execution; it leaves the LLM settings unchanged.

```powershell
.\.venv\Scripts\python.exe -m sparql_agent.cli doctor --retrieval-backend sphn-void --mcp-only
.\.venv\Scripts\python.exe -m sparql_agent.cli ask "Once someone is diagnosed with cancer, what usually happens next: surgery, radiotherapy, both, or nothing? And how long do they typically wait for their first treatment?" --retrieval-backend sphn-void --mode deterministic --classes OncologyDiagnosis OncologySurgery RadiotherapyProcedure
```

`--mode autonomous` remains available with the same backend. Omit `--retrieval-backend` to retain the public SIB configuration, or set `RETRIEVAL_BACKEND=sphn-void` in the environment. The benchmark script also accepts `--retrieval-backend sphn-void|legacy-lexical` (VoID is its default) and `--void-file`; its legacy mode retains the prior per-example holdout behavior. Run the two tool checks before generation. The new backend uses a local lexical index over SIB-compatible VoID relationships, not SIB's Qdrant vector index, and the schema-derived patterns do not encode the full cancer-treatment analysis.
