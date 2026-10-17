# Dove mettere il codice

La libreria SPARQL e l'orchestrazione degli agenti sono package separati in
`src/`. Configurazioni, schemi, infrastruttura e materiale di sviluppo vivono
fuori dal codice applicativo.

| Cartella | Cosa aggiungere qui |
|---|---|
| `src/sparql_analyzer/configuration/` | Nuove policy, toggle, limiti ed export del catalogo |
| `src/sparql_analyzer/parsing/` | Parsing SPARQL, isolamento degli scope e classificazione delle variabili |
| `src/sparql_analyzer/static/` | Regole sulla query prima dell'esecuzione |
| `src/sparql_analyzer/execution/` | Valutatori, provenienza e coordinamento del rilascio |
| `src/sparql_analyzer/governance/` | Contesto fidato, ACL, identita, storico e validazione SHACL |
| `src/sparql_analyzer/shared/` | Vocabolario, algebra, espressioni e contratto numerico condivisi |
| `src/agent_orchestration/` | CLI applicativa, modelli, validazione prompt, workflow e valutatori |
| `src/agent_orchestration/models/` | Contratti, accounting dei token e modelli fittizi |
| `src/agent_orchestration/adapters/` | Backend PydanticAI, classificatori nativi, Laya e MCP |
| `config/agents/` | Modelli, MCP, policy testuale e permessi di esempio |
| `config/policies/` | Profili JSON dei controlli deterministici |
| `schemas/sphn/` | Schemi sorgenti SPHN e terminologie |
| `schemas/shacl/` | Shape operative fornite al runtime |
| `schemas/void/` | VoID strutturale derivato dagli schemi ed esempi MCP |
| `infra/virtuoso/` | Gestione Docker/Virtuoso e query operative |
| `LLM_ENGINE/` | Prototipo sperimentale separato, con proprie dipendenze e CLI |
| `tools/` | Benchmark del workflow, export e generazione di dati sintetici per sviluppo |
| `examples/` | Demo e query di esempio |
| `tests/fixtures/` | Query, indici e dati sintetici versionati |
| `tests/agents/` | Test di modelli, workflow e integrazioni agentiche offline |
| `tests/support/` | Costruttori e helper condivisi dai test |
| `artifacts/` | Output rigenerabili non versionati |

Gli indici di [configurazioni](../../config/README.md) e
[schemi](../../schemas/README.md) spiegano quali file modificare o rigenerare.

## Direzione delle dipendenze

L'orchestrazione chiama le API pubbliche dell'analizzatore. La libreria
`sparql_analyzer` non importa agenti, SDK di modelli, test o tool di sviluppo.
Non e legata a un framework di orchestrazione.

Il servizio di esecuzione coordina validazione statica, controlli sui dati e
valutatori. Le regole statiche dipendono da parsing e configurazione, senza
eseguire query sul dataset. Le funzioni condivise non coordinano richieste.

I moduli `runtime.py`, `parser.py`, `policy.py`, `privacy.py`, `adequacy.py` e
`validation.py` nella radice del package conservano gli import pubblici tramite
esportazioni esplicite. L'implementazione e nelle sottocartelle: per esempio
`sparql_analyzer.runtime.execute_checked` espone la funzione definita in
`execution/service.py`. I nuovi componenti interni devono importare
l'implementazione, senza passare dalle facade di compatibilita.

L'API `compliance.validate` e i comandi `python -m sparql_analyzer.compliance`,
`python -m sparql_analyzer.demo` e `python -m sparql_analyzer.export_policy`
rimangono disponibili. `uv run sparql-check` e l'entry point installabile.

## Dati e infrastruttura

Gli script in `infra/virtuoso/scripts/` ricavano la radice del repository dalla
propria posizione. `PATIENTS_DIR`, `ONTOLOGIES_DIR` e `ONTOLOGY_CACHE_DIR`
configurano i percorsi usati nei bind mount; i dati locali restano in
`patients/`, `ontologies/` e `.ontology_cache/`.

`start-and-test.sh` riusa lo stack vLLM/Qwen e MCP di `LLM_ENGINE` sulla VM;
`start-ollama.sh` resta il percorso alternativo Ollama. I backend sono separati
in `agent_orchestration/adapters/`; `local_models.py` li compone e mantiene gli
import esistenti. La configurazione e in `config/agents/models.json` e, per i test
remoti, nel preset derivato in `artifacts/tests/models.remote.json`.
I contratti, le metriche e i modelli fittizi sono in `models/`; `fakes.py` resta
un modulo di import compatibile. Dettagli nella [guida ai token](../guides/model-usage.md).

`src/agent_orchestration/cli.py` e la CLI applicativa, avviata con
`sparql-run`. Usa lo stesso `SparqlWorkflow` del programma,
con `execute=False` per preparare una query senza eseguirla. Il benchmark e
`tools/evaluate_workflow.py`, avviato con `python -m tools.evaluate_workflow`;
`examples/` contiene soltanto demo.

La [guida dei comandi](../guides/commands.md) e l'ingresso per gli utilizzatori;
questa pagina descrive dove intervenire nel codice. `LLM_ENGINE` non viene
importato dal workflow principale e non ne condivide configurazione o runtime.

L'esecuzione diretta degli script Virtuoso non passa dai controlli Python.
Un futuro adattatore del database dovra collegarsi al percorso verificato e
gestire autorizzazioni, snapshot e controlli di supporto nel database.

## Test e manutenzione

Le suite del controllore sono raggruppate per `analysis`, `runtime`,
`configuration`, `privacy` e `adequacy`; i test agentici sono in
`tests/agents/`. Il marker `offline_workflow` seleziona le interazioni del workflow.
`tests/paths.py` centralizza fixture e output del controllore.

```powershell
uv run pytest -q
uv run python -m tools.export_test_results
uv run python -m sparql_analyzer.export_policy
uv run python -m tools.export_diagrams
uv run python -m tools.check_docs
```

Gli export dei test finiscono in `artifacts/tests/`. Policy e catalogo vengono
rigenerati in `config/policies/` e `docs/policies/checks.md`. Le sorgenti dei
diagrammi seguono la guida `docs/architecture/overview.md`.
