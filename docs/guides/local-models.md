# Modelli locali e MCP condiviso

Il processo principale usa Laya per classificare, un LLM tramite API chat
compatibile per generare, PydanticAI per le chiamate agli strumenti e il runtime
RDFLib per controllare l'esecuzione. Il server MCP SPHN appartiene a
`LLM_ENGINE` ed e condiviso via HTTP, con dipendenze in un ambiente separato.

## Avvio

Dalla radice su Linux, con uv, curl e Python 3.12 disponibili, primo terminale:

```bash
bash start-mcp.sh
```

Avvia `LLM_ENGINE/scripts/serve_sphn_void.py` su `127.0.0.1:18888`, usando
VoID e ontologia del progetto principale in `schemas/`. Non serve Docker;
il server non legge pazienti, non interroga Virtuoso e non scarica embedding.
Il primo avvio installa le dipendenze del sottoprogetto nel suo ambiente.
Si arresta con Ctrl+C. `--port` cambia porta: aggiornare anche `mcp_url`.

In un secondo terminale:

```bash
uv run --extra agents --extra mcp sparql-run --check-mcp
bash start-ollama.sh
uv run --extra local sparql-run --prompt "Conta i pazienti distinti con diagnosi fatturata" --dataset tests/fixtures/synthetic/cohort.trig
```

`--check-mcp` scopre gli strumenti senza caricare Laya o chiamare l'LLM.
Il comando con `--dataset` usa modelli reali e dati sintetici. Senza quel flag,
si ferma alla query analizzata. Stati e output sono nella [guida dei comandi](commands.md).

Il file RDF viene caricato in memoria con RDFLib e controllato con il profilo
predefinito. Non e l'adattatore al database Virtuoso da 50 GB. Per dati reali
servono anche policy e contesti fidati del servizio.

## Configurare modelli e server

Modificare [models.json](../../config/agents/models.json):

| Campo | Ruolo |
|---|---|
| `model`, `base_url` | LLM e indirizzo chat; Ollama nel preset |
| `laya.model_id`, `subfolder`, `device` | Checkpoint e dispositivo del classificatore nativo |
| `mcp_url` | MCP SPHN di LLM_ENGINE, `http://127.0.0.1:18888/mcp` nel preset |

Il collegamento HTTP non importa l'SDK MCP 2 del sottoprogetto nel processo
principale, che usa il proprio SDK MCP 1. I due ambienti restano indipendenti.
Le variabili LLM del prototipo non vengono ereditate: modello e indirizzo
rimangono quelli del JSON del progetto principale.

Il server SPHN espone `search_sparql_examples` e `search_sparql_classes`.
Il generatore vede solo strumenti di recupero schema/esempi; quelli di
esecuzione sono esclusi. L'esecuzione resta nell'executor verificato.
Il server pubblico SIB e il compose `LLM_ENGINE/compose.local.yml` sono
configurati per UniProt e non sono il server SPHN avviato qui.

Per un MCP gia attivo cambiare soltanto `mcp_url`. Per il vecchio avvio stdio,
rimuovere `mcp_url` e impostare `mcp_settings: "sparql-mcp.json"`: avvia
`uvx sparql-llm` con i tool `search_sparql_docs` e `get_classes_schema`.
URL e settings non possono essere attivi insieme. Per disattivare MCP,
omettere entrambi o impostarli a null e fornire `--schema-file`.

## Scegliere e riusare i modelli

`qwen3:14b` e un esempio da adeguare alla GPU. `start-ollama.sh` installa
Ollama se manca (root o sudo), riusa il server attivo o lo avvia in background
e prepara il modello del JSON. Log e PID sono in `artifacts/ollama/`;
un nuovo processo usa `artifacts/ollama/models` oppure `OLLAMA_MODELS`.
Un server gia attivo conserva la propria configurazione.

Un LLM diverso deve supportare tool calling e output strutturato.
Per un altro server chat compatibile cambiare `base_url` e `model`;
`MODEL_API_KEY` specifica la chiave se richiesta.
Laya non e un modello chat: un classificatore diverso richiede lo stesso
formato load/predict o una funzione adattata con `CallableSystemOneModel`.

```python
from agent_orchestration import SparqlWorkflow, StaticQueryAnalyzer
from agent_orchestration.local_models import open_models

async with open_models() as (guard, generator):
    workflow = SparqlWorkflow(guard, generator, StaticQueryAnalyzer(), executor)
    result = await workflow.run(request)
```

Tenere il contesto aperto per riusare Laya e la connessione MCP.
Laya rifiuta troncamento delle opzioni e usa `answer_confidence`, non la
confidenza basata sull'entropia. L'accuratezza di sicurezza va misurata.
Policy e permessi di esempio si sostituiscono con `--policy-file` e
`--permissions-file`; le autorizzazioni effettive appartengono al runtime.

## Verifiche e valutazione

```bash
uv run --extra local python -m tools.evaluate_workflow --models-config config/agents/models.json
```

Il benchmark esegue su fixture sintetiche, escludendo il gruppo usato
nell'esempio RAG. Il test `tests/agents/test_shared_mcp.py` avvia il vero server
SPHN e verifica HTTP, classi, esempi ed esecuzione controllata, con inferenza
sostituita. Inferenza GPU e indicizzazione SIB/Qdrant restano da provare
sull'istanza. Dettagli nella [guida ai test](../../tests/README.md).
