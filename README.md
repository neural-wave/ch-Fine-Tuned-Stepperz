# Fine-Tuned Stepperz

Workflow da linguaggio naturale a SPARQL: validazione del prompt, generazione
della query, analisi statica ed esecuzione verificata su un Dataset RDFLib locale.
I modelli sono sostituibili; i controlli sulla query e sui risultati sono
deterministici. Virtuoso ha un percorso di gestione separato.

Servono **Python 3.12+** e [uv](https://docs.astral.sh/uv/getting-started/installation/).
Eseguire i comandi dalla radice del repository.

## Inizia offline

Non servono GPU, Ollama o pesi. La demo usa modelli fittizi e dati sintetici:

```bash
uv sync --locked --extra agents --extra mcp
uv run python -m examples.fake_workflow
uv run --extra agents --extra mcp pytest -m offline_workflow -q
```

Il gruppo di test include gli agenti PydanticAI, il client HTTP con risposte
controllate e un MCP locale di test. Verifica collegamenti, blocchi, errori e
oracoli; non misura l'accuratezza dei modelli reali.
Per le strategie fittizie vedere la [guida](docs/guides/fake-models.md);
per selezione dei test e report vedere [tests/README.md](tests/README.md).

## Usa i modelli reali

Scegli LLM, indirizzo del server e checkpoint Laya in
[config/agents/models.json](config/agents/models.json).
Su un'istanza Linux con `curl` e `python3`:

```bash
bash start-ollama.sh
uv sync --locked --extra local
uv run --extra local python -m agent_orchestration --prompt "Conta i pazienti distinti con diagnosi fatturata"
```

Lo script installa Ollama se manca (root o sudo), avvia il server se necessario
e prepara il modello configurato. Laya viene caricato da Python; l'MCP fornisce
schemi ed esempi. La CLI genera e analizza la query, **senza eseguirla**.
Per configurazione, permessi e integrazione nel programma vedere
[modelli locali](docs/guides/local-models.md) e [workflow](docs/guides/agent-workflow.md).

## Usa solo l'analizzatore

La libreria SPARQL funziona anche senza dipendenze agentiche:

```bash
uv run sparql-check tests/fixtures/cases/00_compliant.rq --policy config/policies/default.json
```

`sparql-check` e `validate` applicano i controlli statici. L'esecuzione verificata
passa da `execute_checked`; i profili `adequacy` e `hardened` richiedono anche
i contesti fidati documentati nelle [guide alle policy](docs/policies/configuration.md).

## Dove trovare le cose

| Percorso | Contenuto |
|---|---|
| `src/sparql_analyzer/` | Parser, analisi, controlli di esecuzione, privacy e SHACL |
| [src/agent_orchestration/](src/agent_orchestration/README.md) | Modelli, adattatori, workflow e valutazione |
| [config/](config/README.md) | Modelli, MCP, policy e permessi di esempio |
| [schemas/](schemas/README.md) | Schemi sorgenti, shape SHACL e VoID derivato |
| [tests/](tests/README.md) | Suite, fixture e profili verificati |
| [examples/](examples/README.md) | Demo del workflow e del controllore |
| [tools/](tools/README.md) | Benchmark, generazione di fixture, export e verifiche documentali |
| [infra/virtuoso/](infra/virtuoso/README.md) | Gestione del triplestore con Bash e Docker |
| [docs/](docs/README.md) | Guide, architettura, sicurezza e specifiche |
| `artifacts/` | Log, cache e report generati, esclusi da Git |

La [mappa del codice](docs/architecture/project-layout.md) descrive le dipendenze.
Gli script Virtuoso interrogano direttamente il database: il collegamento al
runtime verificato Python resta da realizzare. Inferenza reale e compatibilita
con la GPU richiedono una prova sull'istanza; shape e test non certificano
l'anonimato generale delle risposte.
