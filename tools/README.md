# Strumenti di sviluppo

Questa cartella ospita benchmark e manutenzione. L'applicazione si avvia con
`sparql-run`: la [guida dei comandi](../docs/guides/commands.md) distingue
esecuzione di un prompt, valutazione del corpus, demo e test.

Eseguire dalla radice del repository dopo `uv sync --locked`.
Questi comandi generano fixture, report o documentazione e possono sostituire
i file nella destinazione indicata.

## Benchmark del workflow

Per confrontare latenza e richieste al modello tra recupero agentico e prefetch:
`uv run --extra local python -m tools.benchmark_inference --help`.
Comandi VM, parametri vLLM e limiti nella [guida alle prestazioni](../docs/guides/inference-performance.md).

Per valutare il corpus prompt-query con risposte predisposte, senza modelli:

```bash
uv run --extra agents python -m tools.evaluate_workflow --offline
```

Il report e `artifacts/workflow-evaluation/report.json`. `--component generation`
e `--component system` isolano le due parti. Per usare i backend di `models.json`:

```bash
uv run --extra local python -m tools.evaluate_workflow --models-config config/agents/models.json
```

Questo benchmark usa sempre fixture sintetiche locali. Il comando applicativo
`sparql-run --dataset ...` esegue invece una singola richiesta sul file fornito.
Per conservare report diversi usare `--out`: il percorso predefinito viene riusato.

L'offline verifica i collegamenti tra componenti; la misura dei modelli richiede
i backend reali. Oracoli e limiti sono nella [guida al workflow](../docs/guides/agent-workflow.md).
La CLI per una singola richiesta e `sparql-run`; istruzioni
nella [guida ai modelli locali](../docs/guides/local-models.md).

## Dataset e prompt

| Comando | Risultato |
|---|---|
| `uv run python -m tools.generate_synthetic_data --patients 12 --seed 42` | Rigenera `tests/fixtures/synthetic/cohort.trig`; `--out` cambia destinazione |
| `uv run python -m tools.build_prompt_links` | Rigenera le associazioni prompt-query in `tests/fixtures/system/prompt_query_links.json` |
| `uv run python -m tools.generate_system_dataset` | Crea il piccolo benchmark sintetico in `artifacts/system-dataset/`; `--out` cambia destinazione |

Dopo aver modificato query o prompt, rivedere le associazioni e le etichette.
`generate_workflow_fixtures.py` è una libreria usata da test e valutazione:
non serve eseguirla separatamente. Per scegliere il dataset adatto vedere la
[guida ai dataset](../docs/system-dataset.md).

## Report e documentazione

| Comando | Risultato |
|---|---|
| `uv run python -m tools.export_test_results` | Alberi, verdetti e osservazioni avversarie in `artifacts/tests/` |
| `uv run python -m tools.export_adversarial` | Sottocorpus avversario in `artifacts/tests/adversarial/` |
| `uv run python -m sparql_analyzer.export_policy` | Rigenera i profili in `config/policies/` e il catalogo dei controlli |
| `uv run python -m tools.export_diagrams` | Rigenera i sei file Mermaid dai diagrammi della guida |
| `uv run python -m tools.check_docs` | Verifica i percorsi locali dei collegamenti Markdown |

Le osservazioni avversarie possono dimostrare un rischio: un esito atteso non
significa sempre che l'attacco sia stato bloccato. I comandi per eseguire i test
sono in [tests](../tests/README.md); le demo sono in [examples](../examples/README.md).
