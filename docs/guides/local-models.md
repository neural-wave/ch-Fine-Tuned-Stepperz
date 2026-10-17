# Modelli locali e MCP condiviso

Il processo principale usa Laya per classificare, un LLM tramite API chat
compatibile per generare, PydanticAI per le chiamate agli strumenti e il runtime
RDFLib per controllare l'esecuzione. Il server MCP SPHN appartiene a
`LLM_ENGINE` ed e condiviso via HTTP, con dipendenze in un ambiente separato.

## Avvio

Dalla radice su Linux, con uv, curl e Python 3.12 disponibili, primo terminale:

```bash
bash LLM_ENGINE/start_remote.sh
```

Avvia o riusa vLLM e MCP in sessioni tmux, leggendo modello e indirizzi da
`config/agents/models.json`. Richiede vLLM installato, tmux, curl e ss.
MCP recupera lo schema e non interroga i dati paziente.
Per avviare soltanto MCP in primo piano resta disponibile `bash start-mcp.sh`.

In un secondo terminale:

```bash
uv run --extra agents --extra mcp sparql-run --check-mcp
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
| `model`, `base_url` | LLM e indirizzo chat; vLLM nel preset |
| `laya.model_id`, `subfolder`, `device` | Checkpoint e dispositivo del classificatore nativo |
| `mcp_url` | MCP SPHN di LLM_ENGINE, `http://127.0.0.1:18888/mcp` nel preset |
| `generation_mode` | `prefetch` nel preset; `agentic` lascia gli strumenti al modello |
| `retrieval_classes` | Suggerimenti opzionali per le classi del prefetch, massimo sei |

Il collegamento HTTP non importa l'SDK MCP 2 del sottoprogetto nel processo
principale, che usa il proprio SDK MCP 1. I due ambienti restano indipendenti.
Lo script remoto deriva le variabili per la propria CLI dal JSON condiviso.
Non crea un secondo JSON e non usa `.env.remote` per scegliere i modelli.

Il server SPHN espone `search_sparql_examples` e `search_sparql_classes`.
Il retrieval normalizza i plurali inglesi regolari e collega il lessico clinico
alle classi dichiarate: per esempio hospital/stay ad Admission e Discharge,
births a Birth, gestation a GestationalAgeAtBirth. Non legge le risposte del benchmark.
Se il MCP non restituisce classi, la generazione si ferma; il log riporta prompt,
hints effettivi, numero di esempi e risposta MCP. Per vocaboli non riconosciuti
si possono indicare nomi o IRI esatti in `retrieval_classes`. Dopo modifiche al
retrieval occorre riavviare il processo MCP: riavviare solo l'API non basta.
In `prefetch` il codice recupera il contesto e il generatore riceve solo i dati;
in `agentic` il generatore vede gli strumenti di recupero schema/esempi.
L'esecuzione resta nell'executor verificato. Configurazione vLLM e confronto
dei tempi sono nella [guida alle prestazioni](inference-performance.md).
Il server pubblico SIB e il compose `LLM_ENGINE/compose.local.yml` sono
configurati per UniProt e non sono il server SPHN avviato qui.

Per un MCP gia attivo cambiare soltanto `mcp_url`. Per il vecchio avvio stdio,
rimuovere `mcp_url` e impostare `mcp_settings: "sparql-mcp.json"`: avvia
`uvx sparql-llm` con i tool `search_sparql_docs` e `get_classes_schema`.
In questo caso impostare anche `generation_mode: "agentic"`.
URL e settings non possono essere attivi insieme. Per disattivare MCP,
omettere entrambi o impostarli a null e fornire `--schema-file`.

## Scegliere e riusare i modelli

Il preset usa `daniel-dona/sparql-model-era-lora-128-qwen3-8b` su vLLM.
Per cambiare modello modificare `model` nel JSON, fermare la sessione del vecchio
modello (`tmux kill-session -t '=sphn-qwen'`) e rilanciare lo script remoto.
Il riavvio interrompe le richieste attive. Poi riavviare API o debugger.
Ollama resta un'alternativa manuale: richiede un nome modello Ollama e il suo
`base_url` nel medesimo JSON; non usare `start_remote.sh` per quel backend.

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
