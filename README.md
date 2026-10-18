# Fine-Tuned Stepperz

Da un prompt a una query SPARQL e al risultato controllato:
**validazione del prompt → generazione → analisi statica → runtime RDFLib**.

Il progetto principale espone due comandi: **`sparql-run`** per il workflow e
**`sparql-check`** per analizzare una query gia scritta.
Servono Python 3.12+ e [uv](https://docs.astral.sh/uv/getting-started/installation/).
I comandi seguenti partono dalla radice del repository.

## Funzionalita disponibili

| Cosa vuoi fare | Ingresso | Risultato |
|---|---|---|
| Controllare API, modello e MCP | `python -m system_validation check` | [Stato e diagnostica](system_validation/README.md), inferenza e Virtuoso opzionali |
| Valutare tutti i prompt etichettati | `python -m system_validation run --api-only` | [100 casi unificati](system_validation/README.md), token, tempi e metriche di classificazione |
| Aggiungere esecuzione su Virtuoso | `python -m system_validation prepare`, poi `run` | [Verifica dati e tempi delle query](system_validation/README.md), senza soglie pass/fail |
| Esporre traduzione e verdetto via HTTP | `bash start-api.sh` | [README API](src/api/README.md): query, token totali e conformita, senza esecuzione |
| Studiare una singola esecuzione | `POST /study/nl-to-sparql` | [Query, verdetti e analytics complete](src/api/README.md#endpoint-di-studio): tempi, token e metadati |
| Prompt → risultato su RDF locale | `sparql-run --prompt ... --dataset ...` | Risultato JSON oppure blocco/errore |
| Prompt → sola query | `sparql-run --prompt ...` | Query analizzata, non eseguita |
| Controllare una query esistente | `sparql-check file.rq` | Verdetto statico |
| Provare il flusso senza pesi | `python -m examples.fake_workflow` | Demo con modelli fittizi e runtime reale |
| Verificare il sistema offline | `pytest -m offline_workflow` | Test delle integrazioni |
| Valutare il corpus con oracoli | `python -m tools.evaluate_workflow` | Report di sistema e generazione |

**[Guida dei comandi](docs/guides/commands.md)**: istruzioni complete, dipendenze,
input/output, stati restituiti e differenze tra questi percorsi.

Il workflow restituisce anche token per modello e fase in `analytics.token_usage`;
contratti, contatori e struttura dei backend nella [guida ai token](docs/guides/model-usage.md).

## Avvio dell'applicazione

Sulla VM Linux, per avviare lo stack vLLM/Qwen e MCP di `LLM_ENGINE` e poi i test
dei modelli reali: `bash start-and-test.sh`. Setup, log e report nei
[test](tests/README.md).

Scegliere LLM, endpoint e checkpoint Laya in
[models.json](config/agents/models.json). Su Linux:

```bash
bash LLM_ENGINE/start_remote.sh
```

Lo script avvia o riusa vLLM e MCP. Poi:

```bash
uv run --extra agents --extra mcp sparql-run --check-mcp
uv run --extra local sparql-run --prompt "Conta i pazienti distinti con diagnosi fatturata" --dataset tests/fixtures/synthetic/cohort.trig
```

Usa modelli reali e un dataset sintetico. Omettendo `--dataset` si ferma alla
query analizzata. Se i controlli passano, `status` e `released` e `result`
contiene la risposta. Il file RDF viene caricato in memoria; il runtime usa
il profilo predefinito. Setup e opzioni nella [guida locale](docs/guides/local-models.md).

## Prova offline

Per automatizzare localmente le due suite e il collegamento MCP, senza modelli:

```bash
bash test.sh
```

Ambienti, report e health check opzionali sono descritti nei [test](tests/README.md).

Senza GPU, Ollama o pesi:

```bash
uv run python -m examples.fake_workflow
uv run --extra agents --extra mcp pytest -m offline_workflow -q
```

Le risposte controllate verificano integrazioni e oracoli, non l'accuratezza
dei modelli. Per strategie e report: [modelli fittizi](docs/guides/fake-models.md)
e [test](tests/README.md).

## Organizzazione

| Percorso | Responsabilita |
|---|---|
| `src/sparql_analyzer/` | Libreria deterministica e comando `sparql-check` |
| [system_validation/](system_validation/README.md) | Package separato per corpus etichettato, preparazione Virtuoso e log delle metriche HTTP end to end |
| [src/agent_orchestration/](src/agent_orchestration/README.md) | Workflow, modelli e comando `sparql-run` |
| [config/](config/README.md) / [schemas/](schemas/README.md) | Configurazioni, schemi e metadati MCP |
| [tools/](tools/README.md) | Benchmark, generazione fixture ed export |
| [examples/](examples/README.md) | Sole demo eseguibili |
| [tests/](tests/README.md) | Test del progetto principale e fixture sintetiche |
| [infra/virtuoso/](infra/virtuoso/README.md) | Gestione del database con Bash e Docker |
| [LLM_ENGINE/](LLM_ENGINE/README.md) | Server MCP SPHN condiviso e prototipo con proprio ambiente |
| `artifacts/` | Log, cache e report generati, esclusi da Git |

[Indice delle guide](docs/README.md) e [mappa del codice](docs/architecture/project-layout.md).

Il runtime verificato lavora su RDFLib locale: il collegamento a Virtuoso resta
da implementare. Gli script del database e il prototipo `LLM_ENGINE` seguono
percorsi separati. Inferenza e GPU vanno provate sull'istanza; shape e test non
certificano l'anonimato generale delle risposte.
