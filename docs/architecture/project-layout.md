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
| `src/agent_orchestration/` | Futuri agenti, adattatori dei modelli e workflow quando saranno implementati |
| `config/policies/` | Configurazioni JSON del servizio |
| `schemas/shacl/` | Shape RDF versionate |
| `infra/virtuoso/` | Gestione Docker/Virtuoso e query operative |
| `tools/` | Export e generazione di dati sintetici per sviluppo |
| `examples/` | Demo e query di esempio |
| `tests/fixtures/` | Query, indici e dati sintetici versionati |
| `tests/support/` | Costruttori e helper condivisi dai test |
| `artifacts/` | Output rigenerabili non versionati |

## Direzione delle dipendenze

L'orchestrazione chiamera le API pubbliche dell'analizzatore. La libreria
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

Gli script sono ora in `infra/virtuoso/scripts/` e ricavano la radice del
repository dalla propria posizione. I default di `PATIENTS_DIR`,
`ONTOLOGIES_DIR` e `ONTOLOGY_CACHE_DIR` indicano gli stessi percorsi precedenti.
Questo conserva la configurazione dei bind mount esistenti. Non viene
riavviato o ricreato alcun container dalla riorganizzazione.

L'esecuzione diretta degli script Virtuoso non passa dai controlli Python.
Un futuro adattatore del database dovra collegarsi al percorso verificato e
gestire autorizzazioni, snapshot e controlli di supporto nel database.

## Test e manutenzione

Le suite sono raggruppate per `analysis`, `runtime`, `configuration`, `privacy`
e `adequacy`. `tests/paths.py` centralizza fixture e output, evitando percorsi
relativi alla posizione del singolo test.

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
