# Fine-Tuned Stepperz

Analisi deterministica delle query SPARQL, controllo dei risultati e validazione
SHACL dei dati RDF. Il repository include anche gli strumenti per il triplestore
Virtuoso e uno spazio separato per la futura orchestrazione degli agenti.

## Struttura

```text
src/
  sparql_analyzer/       Libreria e API pubbliche
    configuration/      Policy, dipendenze dei toggle ed export
    parsing/            Parser, scope e analisi dell'algebra
    static/             Regole e validazione statica
    execution/          Esecuzione verificata, aggregazioni e provenienza
    governance/         ACL, storico, snapshot e adeguatezza SHACL
    shared/             Vocabolario, espressioni e contratto dei risultati
  agent_orchestration/  Spazio riservato agli agenti, ancora senza workflow
config/policies/        Profili JSON: default, adequacy, hardened, unrestricted
schemas/shacl/          Shape SPHN
infra/virtuoso/         Script Docker, query e manuale operativo
tests/                  Suite per area, fixture e supporto
tools/                  Generazione fixture ed export di sviluppo
examples/               Demo eseguibili ed esempi clinici
docs/                   Architettura, guide, policy, sicurezza e specifiche
artifacts/              Output generati, esclusi da Git
```

`patients/`, `ontologies/` e `.ontology_cache/` conservano i percorsi dei dati
locali gia usati dai mount Docker. I dati non vengono spostati dalla riorganizzazione.

La [guida alla struttura](docs/architecture/project-layout.md) spiega le dipendenze
e dove aggiungere codice. Per presentare il progetto al gruppo:
[diagrammi e spiegazione](docs/architecture/overview.md).

## Ambiente Python

Python 3.12 o superiore e [uv](https://docs.astral.sh/uv/getting-started/installation/).
Eseguire dalla radice del repository:

```powershell
uv sync --locked
uv run sparql-check tests/fixtures/cases/00_compliant.rq --policy config/policies/default.json
uv run pytest -q
```

Il progetto viene installato in modalita editable da `src/`. Restano disponibili
i comandi e gli import pubblici principali:

```powershell
uv run python -m sparql_analyzer.compliance tests/fixtures/cases/00_compliant.rq
uv run python -m sparql_analyzer.demo
uv run python -m examples.diagram_walkthrough
uv run python -m examples.runtime_demo
```

```python
from sparql_analyzer import Policy, ExecutionContext, ReleaseHistory, ShaclContext
from sparql_analyzer.compliance import validate
from sparql_analyzer.runtime import execute_checked, ResultBlocked
```

`validate` e `sparql-check` applicano solo i controlli statici. L'esecuzione con
controlli sui dati, risultati e storico passa da `execute_checked`.
Hardened richiede sia il contesto privacy fidato sia `shacl_context`.

## Virtuoso

Eseguire con Bash e Docker dalla radice del repository:

```bash
./infra/virtuoso/scripts/start.sh
./infra/virtuoso/scripts/load-patients.sh
./infra/virtuoso/scripts/query.sh infra/virtuoso/queries/count-per-graph.rq
```

Configurazione e gestione dei dati sono nel [manuale Virtuoso](infra/virtuoso/README.md).
Gli script interrogano direttamente il database: non attraversano il runtime
verificato Python. L'integrazione tra i due percorsi resta da realizzare.

## Documentazione

- [Indice delle guide](docs/README.md)
- [Policy e toggle](docs/policies/configuration.md), [catalogo](docs/policies/checks.md)
- [Controlli privacy](docs/policies/privacy.md) e [adeguatezza SHACL](docs/policies/adequacy-shacl.md)
- [Attacchi e limiti della copertura](docs/security/anonymity-attacks.md)
- [Test e profili verificati](tests/README.md)
- [Tool di manutenzione](tools/README.md) ed [esempi](examples/README.md)

Le shape e i test non certificano l'anonimato generale delle risposte.
