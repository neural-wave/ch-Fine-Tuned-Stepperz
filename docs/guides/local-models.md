# Modelli locali: configurazione semplice

Usiamo **Ollama per gli LLM**, **Laya tramite la sua libreria Python** e
PydanticAI per collegarli agli strumenti MCP. Il collegamento e tutto in
`src/agent_orchestration/local_models.py`: nessun parser o backend Transformers
personalizzato. Analizzatore, runtime e valutazione semantica restano separati.

## Avvio

Dalla radice del repository Linux, con `curl` e `python3` disponibili:

```bash
bash start-ollama.sh
uv sync --locked --extra local
uv run --extra local sparql-run --prompt "Conta i pazienti distinti con diagnosi fatturata"
```

Lo script installa [Ollama](https://docs.ollama.com/linux) se manca (servono root
o sudo), riusa un server gia attivo oppure lo avvia in background senza systemd,
e scarica il modello indicato in `models.json`. Si puo rilanciare. Un argomento
opzionale, ad esempio `bash start-ollama.sh qwen3:8b`, prepara un altro modello;
per usarlo nel programma aggiornare anche `model` nel JSON.
Accetta solo un `base_url` HTTP locale. Log e PID del processo avviato sono in
`artifacts/ollama/`; i pesi del nuovo processo sono in `artifacts/ollama/models`
oppure nella directory `OLLAMA_MODELS` se impostata. Un server gia attivo conserva
la propria configurazione. Usare un disco persistente sull'istanza per conservarli.

`qwen3:14b` e un esempio, da scegliere in base alla GPU. Il comando Python
carica Laya una volta, avvia l'MCP `uvx sparql-llm`, valida il prompt, genera la
query e applica l'analisi statica tramite `SparqlWorkflow.run(execute=False)`.
La CLI e in `src/agent_orchestration/cli.py`. Senza dataset restituisce
`query_ready`, senza eseguire la query.

Per il workflow completo, con modelli reali ed esecuzione controllata locale:

```bash
uv run --extra local sparql-run --prompt "Conta i pazienti distinti con diagnosi fatturata" --dataset tests/fixtures/synthetic/cohort.trig
```

Se i controlli passano, lo stato e `released` e `result` contiene la risposta
SPARQL Results JSON. Altrimenti lo stato indica il blocco o errore e non viene
rilasciato un risultato. `--rdf-format` permette di specificare il formato RDF;
altrimenti viene ricavato dall'estensione. TriG e N-Quads conservano i grafi
paziente distinti richiesti da queste query.

Il file fornito viene caricato in memoria con RDFLib e controllato con il
profilo predefinito. Il comando non e collegato all'endpoint Virtuoso e non e
il percorso per caricare un database clinico da 50 GB. La fixture dell'esempio
e sintetica; per dati reali occorrono anche policy e contesti fidati del servizio.

## Cambiare modello

Modificare soltanto `config/agents/models.json`:

```json
"base_url": "http://localhost:11434/v1",
"model": "qwen3:14b"
```

Per un altro modello Ollama: scaricarlo con `ollama pull NOME` e cambiare `model`.
Deve supportare tool calling e output strutturato. Per usare un server diverso
cambiare anche `base_url`; il workflow non cambia. `MODEL_API_KEY` permette di
specificare una chiave quando il server la richiede.

Per semplicita partire da Ollama. [llama.cpp](https://github.com/ggml-org/llama.cpp)
e un'alternativa per checkpoint GGUF; [vLLM](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/)
e un'alternativa per un servizio GPU con richieste concorrenti. Espongono API
compatibili, ma template e tool calling vanno verificati con il modello scelto.

Laya usa `laya.model_id`, `subfolder` e `device`. Non e un normale modello chat:
un altro modello decisionale deve offrire lo stesso formato `load/predict`,
oppure avere una piccola funzione adattata con `CallableSystemOneModel`.
L'adapter rifiuta input troncati e usa `answer_confidence`, non la confidenza
basata sull'entropia. Le sue prestazioni di sicurezza vanno misurate.

## Usarlo dal programma

```python
from agent_orchestration import SparqlWorkflow, StaticQueryAnalyzer
from agent_orchestration.local_models import open_models

async with open_models() as (guard, generator):
    workflow = SparqlWorkflow(guard, generator, StaticQueryAnalyzer(), executor)
    result = await workflow.run(request)
```

Tenere il contesto aperto per riusare gli stessi modelli. Un LLM generico usa
`Agent(chat_model(nome, indirizzo))`; il modello per SPARQL usa lo stesso client
con output `SparqlResult` e strumenti MCP.

Per preparare soltanto la query, costruire il workflow senza `executor` e usare
`await workflow.run(request, execute=False)`. Validazione del prompt e analisi
statica restano attive; un esito positivo ha stato `query_ready`.

`mcp_settings` punta a `sparql-mcp.json`, che usa gli schemi gia convertiti.
Solo `search_sparql_docs` e `get_classes_schema` sono esposti al generatore.
Impostare `mcp_settings: null` per disattivare MCP e passare `--schema-file`.
I percorsi dei metadati MCP sono relativi alla radice di questo repository.
Aggiornare l'endpoint in `sparql-mcp.json` e sostituire policy/permessi di esempio
con quelli fidati del servizio (`--policy-file`, `--permissions-file`).

## Valutazione

```bash
uv run --extra local python -m tools.evaluate_workflow --models-config config/agents/models.json
```

Esclude il gruppo `00_compliant`, gia presente negli esempi RAG. I test locali
usano risposte HTTP controllate e un vero MCP stdio minimale, senza scaricare
pesi. Inferenza GPU e indicizzazione del server upstream richiedono una prova
sull'istanza. Il primo avvio puo scaricare pesi Laya, dipendenze ed embedding MCP.
