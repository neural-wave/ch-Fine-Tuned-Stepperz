# Experimental Results — NL → SPARQL Agent

> **Latest experiment:** section 9 records the completed Qwen3-30B-A3B-GPTQ-Int4 deployment and UniProt comparison on an RTX 4090, plus the partial SPHN experiment. The original 9B baseline below is preserved.

**Updated:** 17 October 2026  
**Status:** Initial working baseline established for **Qwen3.5-9B**; no valid 14B comparison yet.  
**Important:** These are **UniProt smoke tests**, **not** clinical/SPHN benchmark results.

## 1. Experimental setup

| Item | Observed configuration |
| --- | --- |
| GPU / deployment | Vast.ai RTX 3090 (24 GB); vLLM |
| Working model | `Qwen/Qwen3.5-9B` |
| Model API | OpenAI-compatible `/v1` via remote `127.0.0.1:18000`, SSH tunnel to Windows `127.0.0.1:18080` |
| Retrieval | Public SIB MCP `https://chat.expasy.org/mcp/` |
| Modes | Deterministic RAG vs. autonomous MCP tool selection |
| Query target | Public UniProt SPARQL endpoint |
| Local runner | Windows PowerShell; `uv run sparql-agent` and `uv run sparql-benchmark` |
| Automated generation check | SPARQL syntax, tool completion, timings, token accounting |
| Separate execution check | SIB `execute_sparql_query`, including endpoint-schema checks |
| Clinical privacy/compliance check | **Not implemented/verified in this prototype** (`compliance_checked: false` in execution output) |

The working `doctor` run with **Qwen3.5-9B** reported:

- `ok: true`; LLM response `OK` in **1.16 s** (16 prompt, 2 completion tokens).
- MCP tool discovery in **0.096 s**.
- `search_sparql_examples` succeeded in **0.049 s** with nonempty results.
- `search_sparql_classes` succeeded in **0.039 s** with nonempty results.
- Doctor record: `results/doctor-ca65ed4e91e5413bac5903c9a973f2e3.json`.

This confirms successful **model connectivity and retrieval calls**, not correctness of generated answers.

## 2. Initial controlled comparison

Benchmark command:

```powershell
uv run sparql-benchmark --limit 3 --repeats 1 --warmups 0 --modes deterministic autonomous
```

Question IDs: `uniprot_lct`, `uniprot_gene_names`, `uniprot_review_status`. Each was evaluated once in both modes (six measured runs total; no warmups).

| Metric | Qwen3.5-9B deterministic | Qwen3.5-9B autonomous |
| --- | ---: | ---: |
| Measured runs | 3 | 3 |
| Mean latency | **3.30 s** | **5.95 s** |
| Median latency | 3.22 s | 5.61 s |
| Reported p95 latency | 4.01 s | 7.28 s |
| Reported generation success | **100%** | **100%** |
| Reported tool success | **100%** | **100%** |
| Mean total tokens per request | **1,989** | **8,166** |

**On this tiny sample**, deterministic mode was approximately **44.5% faster** in mean end-to-end generation time and used **75.6% fewer tokens**. Autonomous mode used about **4.1×** as many tokens. These are descriptive differences, **not statistical conclusions** (only three samples per mode).

**Crucial metric distinction:** the benchmark's **100% generation success** must **not** be labeled "100% correct SPARQL". Subsequent execution of the LCT queries found a schema error in the deterministic version and an omitted question constraint in the autonomous version.

Saved benchmark artifacts (in the original project):

```text
results/benchmark-cc2cd07664104dc28608e3ba88c1819f.jsonl
results/benchmark-cc2cd07664104dc28608e3ba88c1819f.summary.json
```

## 3. Case study: human proteins encoded by LCT

**Input question:**

> Write a SPARQL query to retrieve human proteins encoded by the LCT gene from UniProt.

### 3.1 Deterministic retrieval

Generation trace:

| Observed metric | Value |
| --- | --- |
| Generation status | `success` |
| SPARQL syntax | `True` |
| Total generation time | **4.34 s** |
| MCP retrieval time | 0.05 s |
| LLM-request time | 4.01 s |
| Tokens | 1,680 prompt + 133 completion = **1,813** |
| Model iterations | 1 |
| Tools | `search_sparql_examples` |
| Generated query | `results/c921f735279f4f1981bc1a7352226437.rq` |

Problematic fragment:

```sparql
?protein a up:Protein ;
         up:organism taxon:9606 ;
         up:gene ?gene .
FILTER(?gene = "LCT")
OPTIONAL { ?protein up:organismName ?organismName . }
```

**Execution/schema result: FAILED.** The SIB executor rejected the query before running it (approximately **0.267 s**) because `up:Protein` does **not** support `up:gene` or `up:organismName` at the UniProt endpoint. The comparison `?gene = "LCT"` would also be incorrect when `?gene` is a resource URI.

The relevant supported relationship is `up:encodedBy` from protein to gene; the gene's name can be matched using `skos:prefLabel`.

Execution record reported:

```text
ok: false
truncated: false
compliance_checked: false
```

**Interpretation:** syntax-only validation missed real schema errors. Low-latency generation is not useful if the resulting query cannot execute.

### 3.2 Autonomous tool selection

Generation trace:

| Observed metric | Value |
| --- | --- |
| Generation status | `success` |
| SPARQL syntax | `True` |
| Total generation time | **9.69 s** |
| MCP retrieval time | 0.22 s |
| LLM-request time | 9.20 s |
| Tokens | 13,055 prompt + 295 completion = **13,350** |
| Model iterations | 3 |
| Tools | `search_sparql_examples`, `search_sparql_classes` |
| Generated query | `results/01a826357c5042048b9804cbee7e7ce3.rq` |

Key fragment:

```sparql
?protein a up:Protein ;
         up:encodedBy ?gene .
?gene skos:prefLabel ?geneName .
FILTER(?geneName = "LCT")
```

**Execution/schema result: PASSED.** The SIB executor returned UniProt rows in approximately **6.71 s**. The response was marked **`truncated: true`** by the client, after many matching entries had been returned.

However, the generated query had **no `up:organism taxon:9606` restriction**. It therefore did not enforce the user's requirement to retrieve **human** proteins only.

Execution record reported:

```text
ok: true
truncated: true
compliance_checked: false
```

**Interpretation:** autonomous MCP usage discovered a valid gene relationship, but a database query can execute successfully while still being **semantically incomplete**.

### 3.3 Manually corrected reference candidate

We created `results/lct_human_fixed.rq` with the correct UniProt gene relationship and human-organism filter:

```sparql
#+ endpoint: https://sparql.uniprot.org/sparql/
PREFIX up: <http://purl.uniprot.org/core/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX taxon: <http://purl.uniprot.org/taxonomy/>

SELECT DISTINCT ?protein ?proteinName
WHERE {
  ?protein a up:Protein ;
           up:organism taxon:9606 ;
           up:encodedBy ?gene .

  ?gene skos:prefLabel "LCT" .

  OPTIONAL {
    ?protein up:recommendedName/up:fullName ?proteinName .
  }
}
LIMIT 10
```

**Actual execution result:**

```text
ok: true
seconds: 6.403
returned rows: 5
truncated: false
compliance_checked: false
```

One returned entry was **UniProt P09848 — Lactase/phlorizin hydrolase**. Other returned entries included proteins with no optional name or a `beta-glucosidase` name. This demonstrates a practical, schema-valid way to express the human + LCT conditions on the endpoint; it does **not** establish formal completeness of all results.

**Takeaway:** the manually corrected query worked, while neither initially generated version fully satisfied the request. Adding endpoint-schema checking **and** an explicit check that all user constraints appear in the query is the highest-value next improvement.

## 4. Other models / deployment attempts

### Local Ollama: `qwen3:1.7b`

An earlier local diagnostic succeeded:

- Model: `qwen3:1.7b` at `http://localhost:11434/v1`.
- LLM response `OK.` in **6.44 s**; 23 total tokens for the diagnostic.
- MCP discovery and retrieval tools worked.
- Earlier generation attempts were unsuccessful; no comparable, successful six-run benchmark is documented.

**Do not use the 6.44 s doctor response as a direct speed comparison** with Qwen3.5-9B's multi-step query-generation timings.

### Vast.ai: `Qwen/Qwen3-14B-AWQ`

A larger-model experiment was attempted but **never reached a working inference endpoint**:

1. A second vLLM server initially encountered `Address already in use` because Qwen3.5-9B was still listening on `127.0.0.1:18000`.
2. Starting the 14B model on port 18001 produced `RuntimeError: Engine core initialization failed`.
3. Diagnostics showed the original 9B API server (PID 1520) and `VLLM::EngineCore` (PID 1927) were still alive; **20,798 MiB / 24,576 MiB** of GPU memory was in use even though `nvidia-smi` showed no running processes.
4. Both known 9B processes were terminated; subsequent `nvidia-smi` showed **1 MiB / 24,576 MiB** in use.
5. The user reported that vLLM continued failing. The **earlier engine-specific startup errors after GPU cleanup were not collected**, so the final failure cause is **unresolved**.

**No 14B latency, accuracy, token, or execution results are available.** Its model size alone is not evidence it would outperform Qwen3.5-9B. Avoid spending more GPU rental time on it until the root startup error can be inspected.

## 5. What the findings support (and do not)

**Supported:**

- Qwen3.5-9B can connect to the existing Python agent, use real public SIB MCP tools, and generate syntax-valid SPARQL in both tested modes.
- Deterministic retrieval was faster and used fewer tokens **in the initial three-question sample**.
- Autonomous retrieval produced an executable query for the observed LCT example, but omitted a semantic constraint.
- SIB endpoint-schema checking successfully caught nonexistent UniProt predicates in the deterministic example.
- A manually corrected UniProt query returned five matching rows on the live endpoint.

**Not established:**

- Accuracy on a representative SPHN natural-language dataset.
- Correctness of privacy compliance verdicts (false-allow / false-reject rates).
- Performance on the supplied mocked SPHN RDF graph and Virtuoso 7.2.16.
- The prescribed query-execution performance averaged over **10 isolated runs**.
- A fair 9B-vs-14B comparison.
- A production-grade `POST /nl-to-sparql` REST API.

## 6. Next development priorities

1. **Make correctness measurable.** Record separately `syntax_valid`, `schema_valid`, `execution_ok`, `semantic_constraints_satisfied`, and `privacy_compliant`. Do not collapse them into a single "success" flag.
2. **Use SIB schema evidence during generation.** For the deterministic fast path, fetch relevant class/property schema when necessary, not just example queries.
3. **Add bounded repair.** On schema failure, feed the concrete endpoint-validator error back to the model; record extra model calls, tokens, and repair latency. No unlimited retries.
4. **Introduce SPHN-specific compliance rules** using the **complete constraint set shipped with the hackathon dataset**, not only the examples in the briefing. At minimum, the briefing illustrates aggregate-only outputs, no single identifiable patient requests, and no unrestricted whole-graph matching; these are examples, **not the entire specification**.
5. **Integrate the real evaluation target:** SPHN schema/SHACL, local mocked RDF, Virtuoso 7.2.16, and query runtime averaged over 10 isolated runs. Keep queries and results inside authorized environments.
6. **Implement the required REST API** (`POST /nl-to-sparql`) reporting the query and total tokens across generation plus compliance assessment.
7. **Re-run a larger paired benchmark** with warmups, repeat counts, version-pinned models and identical prompts; compare time **to compliant query**, not time to merely parseable query. Only add 14B after its vLLM startup is reproducibly resolved.

## 7. Decision at this checkpoint

**Retain Qwen3.5-9B as the known-working baseline.** Favor **deterministic retrieval as the efficiency starting point**, but introduce schema-aware checking and targeted repair before deciding on the production mode. The one LCT case shows why autonomous schema retrieval can improve validity even when it costs more time and tokens.

This is a baseline **research observation**, not a claim that the final hackathon system is secure or compliant.

## 8. Evidence / reproducibility index

| Artifact (original Windows project `results/` directory) | Contains |
| --- | --- |
| `doctor-ca65ed4e91e5413bac5903c9a973f2e3.json` | Successful Qwen3.5-9B connectivity/retrieval test |
| `c921f735279f4f1981bc1a7352226437.json` and `.rq` | Deterministic LCT generation and query |
| `01a826357c5042048b9804cbee7e7ce3.json` and `.rq` | Autonomous LCT generation and query |
| `benchmark-cc2cd07664104dc28608e3ba88c1819f.jsonl` | Per-run initial paired benchmark |
| `benchmark-cc2cd07664104dc28608e3ba88c1819f.summary.json` | Aggregated benchmark table |
| `lct_human_fixed.rq` | Manually corrected query with successful execution |

These named files are **paths from the original user's local repository**, not embedded in this Markdown document or necessarily available in the present working environment. Preserve them alongside the code for reproducibility.

**Source/context:** CLI and benchmark terminal outputs, UniProt executor responses shared during testing, and the organizer-provided *SPHN Hackathon: Secure NL-to-SPARQL over Clinical Knowledge Graphs* problem statement.

## 9. Qwen3-30B-A3B-GPTQ-Int4 — 17 October 2026

### 9.1 Deployment and compatibility

The supplied SSH connection worked: `ssh -p 48453 root@79.112.26.222`. Inspection found an **RTX 4090, 24,564 MiB VRAM**, driver 595.71.05, rather than the expected RTX 3090. vLLM was **0.30.0**, PyTorch **2.13.0+cu130**, Transformers **5.17.0**, Python **3.12**. Installed source registered `Qwen3MoeForCausalLM`, GPTQ/Marlin MoE kernels, and `hermes`; startup confirmed their selection.

The target was exactly `Qwen/Qwen3-30B-A3B-GPTQ-Int4`, revision `9b534e4318b7ebc3c961a839f13eb18b1833f441`: roughly 30B total parameters / 3B active, GPTQ 4-bit, with float16 activations. The official checkpoint is approximately 16.9 GB ([model files](https://huggingface.co/Qwen/Qwen3-30B-A3B-GPTQ-Int4/tree/9b534e4318b7ebc3c961a839f13eb18b1833f441)).

Initial conditions and controlled changes:

1. The template was already serving Qwen3.5-9B, using about 21,046 MiB GPU memory. Disk had only 5.7 GB free. The user explicitly authorized removing its cached weights after preserving launch details and logs.
2. Stopping supervisor's `vllm` wrapper left API PID 1710 and EngineCore PID 2227 alive. The deployment guard stopped rather than launching another model. Only those identified model processes were then terminated; GPU usage fell to **431 MiB**. Unrelated services remained running.
3. The helper removed the approved 9B cache and its four unshared weight blobs. No other model cache was deleted. The target weights downloaded once in approximately **82 seconds**; disk later showed **7.9 GB free**.
4. Startup **succeeded** with utilization 0.85, max context 4096, max sequences 1, eager execution, float16, `hermes`, and thinking disabled. API binds only `127.0.0.1:18000`; Windows uses SSH `127.0.0.1:18080/v1`.
5. Three of six benchmark requests received explicit HTTP 400 context-budget errors: the prompt plus the reserved 2048 output tokens exceeded 4096. This was **not an OOM or engine initialization failure**. The only serving adjustment was context **4096 → 8192**, retaining the same checkpoint and all other flags. An initial helper call needed correction because `supervisorctl pid` returns exit code 7 for a stopped service; it did not trigger a model download or engine failure.
6. The same cached model started successfully at 8192 and completed both subsequent UniProt benchmarks. No package/version changes, model substitution, or repeated weight download occurred.

Full startup logs are on Vast at `/workspace/qwen30b-prototype/logs/`; their local copy request was rejected. Local installation/diagnostic logs are in `results/qwen30b-deployment/`. No additional engine failure was observed.

### 9.2 API and native tools

Before SPARQL generation, `/v1/models` returned the exact target ID. Through the existing Python `LLMClient`, basic chat returned `OK.` in **0.477 s** (19 tokens), and `tool_choice=auto` returned a structured `lookup_gene` call with JSON arguments `{"gene":"LCT"}` in **0.884 s** (191 tokens). The response parsed and passed JSON-schema validation. Evidence: `qwen30b-deployment/api-smoke-4k.json`.

`sparql-agent doctor` passed LLM connectivity, discovery of 12 public SIB tools, example retrieval, and class retrieval. Evidence: `doctor-f791ffb563124c3180785a772f854322.json`. Persistent `.env`, `.env.example`, and `scripts/use_vast.ps1` select the 30B model, dummy key `EMPTY`, explicit thinking disable, and execution off.

Every measured autonomous UniProt run used a **native model-generated** `search_sparql_examples` call in iteration 1, then generated a query in iteration 2. It did not choose `search_sparql_classes`. Deterministic mode made one application-selected example call and one model request. The complete assistant tool-call objects, arguments, returned context, and final queries are saved per run. No Python fallback fabricated an autonomous tool call.

### 9.3 Latency and generation comparison

The paired run uses the same three questions, both modes, one repeat, and no benchmark warmups. API/doctor/LCT smoke tests had already run; therefore “no warmups” does not mean a cold GPU. The repeated experiment adds one first-question warmup per mode, excluded from nine measured runs per mode. All times are generation end-to-end, excluding later database execution.

| Experiment | Mode | N | Mean s | Median s | p95 s | Syntax/generation success |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Previous 9B / RTX 3090 | Deterministic | 3 | 3.30 | 3.22 | 4.01 | 3/3 |
| Previous 9B / RTX 3090 | Autonomous | 3 | 5.95 | 5.61 | 7.28 | 3/3 |
| 30B / RTX 4090 / 4096 | Deterministic | 3 | 2.68 | 3.06 | 4.58 | 2/3 |
| 30B / RTX 4090 / 4096 | Autonomous | 3 | 2.22 | 1.44 | 3.64 | 1/3 |
| 30B / RTX 4090 / 8192 paired | Deterministic | 3 | 3.73 | 2.96 | 5.20 | 3/3 |
| 30B / RTX 4090 / 8192 paired | Autonomous | 3 | 3.74 | 3.85 | 4.15 | 3/3 |
| 30B / RTX 4090 / 8192 repeated | Deterministic | 9 | 3.29 | 2.90 | 4.21 | 9/9 |
| 30B / RTX 4090 / 8192 repeated | Autonomous | 9 | 3.87 | 3.81 | 4.51 | 9/9 |

The 4096 averages include early failures and must not be interpreted as faster successful inference. Its average token values include only runs with complete usage; failed requests have incomplete accounting.

| Experiment | Mode | Mean prompt tokens | Mean completion tokens | Mean total tokens | Mean model requests | Actual tool calls across measured runs |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Previous 9B paired | Deterministic | 1881 | 108 | 1989 | 1 | 3 examples |
| Previous 9B paired | Autonomous | 7957.7 | 208 | 8165.7 | 2.33 | 3 examples + 1 classes |
| 30B 8192 paired | Deterministic | 1869.7 | 116 | 1985.7 | 1 | 3 examples |
| 30B 8192 paired | Autonomous | 2997.7 | 134.3 | 3132 | 2 | 3 examples |
| 30B 8192 repeated | Deterministic | 1869.7 | 115.3 | 1985 | 1 | 9 examples |
| 30B 8192 repeated | Autonomous | 2997.7 | 134 | 3131.7 | 2 | 9 examples |

All attempted retrieval calls succeeded with nonempty results. In the paired comparison, autonomous generation was about **37% faster** and used **62% fewer tokens** than the recorded 9B baseline. This compares **configurations**, not isolated model quality: GPU, model architecture/quantization, context, eager/graph execution, concurrency, tool parser, and thinking settings differ. The earlier server used a 32000 context and max sequences 8; the new one uses 8192 and 1. Small samples and endpoint/cache variation also limit conclusions.

### 9.4 Correctness and public UniProt execution

All six 8192 paired queries were independently submitted to SIB's public UniProt execution tool. Clinical execution remained disabled.

| Question / mode | Schema check | Execution | Rows | All question constraints by manual review |
| --- | --- | --- | ---: | --- |
| LCT / deterministic | Fail: `up:gene` unsupported on Protein | Rejected, 0.264 s | — | No |
| LCT / autonomous | Pass | Completed, 0.347 s | 0 | No |
| Preferred gene names / autonomous | Pass | Timeout after 10 s | — | Yes in query; execution not demonstrated for this attempt |
| Preferred gene names / deterministic | Pass | Completed, 1.861 s | 20 | Yes |
| Review status / deterministic | Pass | Completed, 0.316 s | 20 | Yes |
| Review status / autonomous | Pass | Completed, 0.295 s | 20 | Yes |

The autonomous gene-name query was textually identical to the successful deterministic query. One requested retry was rejected by the approval system, so the timeout remains a failure in the execution record.

The deterministic LCT query again invented `up:gene` and `up:geneName`. The autonomous 8192 query correctly used `taxonomy/9606`, but joined `up:encodedBy` directly to `http://identifiers.org/geneid/3973`, rather than matching the UniProt gene resource and its label; it returned no rows. The earlier 4096 LCT smoke also used the incorrect `/taxon/9606` namespace. The known manually corrected reference from section 3 was not rerun in this session.

Thus, for the six paired outputs: **6/6 syntax-valid, 5/6 passed the endpoint-schema stage, 4/6 executions completed (including one empty result), and 4/6 encode the requested constraints by manual inspection.** The historical 9B file likewise has four correct gene-name/review-status outputs and two incorrect LCT outputs. **No improvement in semantic correctness was demonstrated.** Repeated-run outputs are preserved; repeated database execution was not performed.

### 9.5 Supplied SPHN examples and schema comparison

The user supplied 15 question/reference pairs and `https://biomedit.ch/rdf/sphn-schema/sphn#`. Content negotiation retrieved Turtle whose `owl:versionIRI` is `https://biomedit.ch/rdf/sphn-schema/sphn/2026/1`, consistent with the [official 2026.1 release](https://git.dcc.sib.swiss/sphn-semantic-framework/sphn-schema/-/tags/2026-1). Copies and hashes are preserved locally. No patient dataset or terminology imports were downloaded.

Because the URL is an ontology rather than a retrieval API, a local MCP adapter was added for this diagnostic. It exposes the two existing retrieval tool shapes and reuses the unchanged agent and clients. It lexically searches 239 schema class summaries and reference examples 1–10. The evaluated example is excluded server-side, including after a model rephrases its search. Deterministic mode also retrieves three class hints selected from the natural-language question. This is **not the SIB public vector index**, and its performance is not directly comparable to UniProt retrieval.

**Only example 1, Cancer treatment pathways, ran in both modes.** The full 30-run command was rejected by the approval system before execution. Examples 2–15 have no generated-model results; they are explicitly marked `not_run_approval_rejected`.

| Example 1 | Seconds | Tokens | Model requests | Actual retrieval | RDFLib syntax | Schema/semantics |
| --- | ---: | ---: | ---: | --- | --- | --- |
| Deterministic | 23.01 | 5651 | 2 | examples + classes | Pass after one repair | Fail |
| Autonomous | 9.45 | 2707 | 2 | model-selected examples | Pass | Fail |

Deterministic retrieval returned other examples 8 and 6; autonomous returned 8 and 3. The audit verified that neither received reference example 1. Both invented a `sphn:Patient` structure and unsupported treatment/diagnosis links. They missed the reference's per-patient named graphs, first treatment after incidence, mutually exclusive surgery/radiotherapy/both/none categories, and treated-only waiting-time average. No clinical query was executed, and no privacy verdict was produced.

All 15 **references** were inspected offline, separately from model generation:

- Example 3 asks for **any diagnosis rank**, but the reference restricts to `Principal`.
- `hasRank` in examples 3, 6, and 12 is absent as a declared term in the downloaded main schema; it declares `hasRankCode` instead. Example 7's `hasAdmissionDateTime`/`hasDischargeDateTime` and example 8's `hasGeneticVariation` are also absent. This is a schema-file compatibility finding, not proof about what triples the organizer's database contains. Resolve with the organizers before scoring those references as ground truth.
- References 2, 3, 6, 12, and 15 use Virtuoso `OPTION (inference ...)`, which RDFLib rejects. This does not establish invalid Virtuoso syntax.
- Examples 11–15 are privacy counterexamples (single-patient selection, individual rows, unrestricted graph matching, CONSTRUCT export, identifiers). They were preserved for later evaluation; no compliance checker or false-allow/false-reject rate was tested.

### 9.6 Artifacts, commands, verification, and remaining work

Raw artifacts under `results/`:

- `qwen3-30b-a3b-int4-4k-paired.{jsonl,summary.json}` — initial context-limited run, including failures.
- `qwen3-30b-a3b-int4-8k-paired.{jsonl,summary.json}` — six paired requests.
- `qwen3-30b-a3b-int4-8k-repeated.{jsonl,summary.json}` — 2 warmups + 18 measurements.
- Per-run UUID `.json`/`.rq` files and `executions.jsonl` — full model/tool traces and execution responses.
- `qwen3-30b-sphn-smoke/` — two clinical traces, generated queries, references, hashes, and summary.
- `qwen30b-deployment/comparison-metrics.json`, `uniprot-correctness.json`, `clinical-reference-comparison.json` — detailed metrics and separately labeled correctness assessments.
- `qwen30b-deployment/commands.md` — operational commands, including rejected requests clearly marked as not executed.

Created scripts: `deploy_qwen30b.py`, `smoke_vllm.py`, `use_vast.ps1`, `benchmark_sphn.py`; added `tests/test_sphn_adapter.py`. Updated README, this results file, `.env.example`, and the ignored `.env`. **No existing `src/sparql_agent/` implementation was changed.** Original results were preserved.

Ruff passed for the added scripts. Actual API/native-tool, doctor, UniProt, and clinical MCP smoke tests ran as described above. The two focused adapter unit tests could not start because pytest's sandbox temporary directory was unavailable; the requested outside-sandbox test run was rejected. **Do not count those unit tests as passed.** Downloading the full remote startup logs was also rejected; they remain on Vast.

Remaining work: run the prepared full clinical benchmark when authorized; reconcile reference/schema differences; add clinical schema-aware repair and the organizer's complete privacy rules; evaluate against the approved Virtuoso dataset. The current evidence supports a working larger-model tool-calling deployment, **not improved SPARQL correctness or clinical compliance**. The GPU model service and tunnel were left running at the last successful observation; manage them with README section 9.
