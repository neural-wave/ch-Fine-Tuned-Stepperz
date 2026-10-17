# Workflow agentico e strategia di test

Il sistema usa agenti PydanticAI in un workflow Python esplicito. Le dipendenze
sono iniettate: si possono sostituire guard e generatore senza cambiare il
parser o il runtime. Importare il package non scarica modelli; l'avvio di Laya
puo scaricare il checkpoint configurato.

```text
Prompt + schema + policy + permessi
  -> PromptValidator: allow / block / review
  -> SparqlLLM: genera query
  -> StaticQueryAnalyzer: controlli esistenti
  -> CheckedQueryExecutor: controlli runtime esistenti
  -> risultato rilasciato oppure blocco/errore
```

## Classi

| Classe | Responsabilita |
|---|---|
| `PromptRequest` / `SparqlRequest` | Stesso tipo: prompt, schema, policy e permessi del servizio |
| `PromptValidation` | Decisione, motivo, probabilita opzionale |
| `PydanticAIPromptValidator` | Guard generativo con output strutturato |
| `SystemOnePromptValidator` | Guard basato su decisioni native; soglia opzionale per accettare |
| `CallableSystemOneModel` | Adatta inferenza nativa locale a `DecisionRequest -> Decision` |
| `PydanticAISparqlLLM` | Adatta un `Agent` con `output_type=SparqlResult` |
| `StaticQueryAnalyzer` | Adatta `sparql_analyzer.validation.validate` |
| `CheckedQueryExecutor` | Adatta `execute_checked` con policy e contesti fidati |
| `SparqlWorkflow` | Sequenza, arresto dopo ogni gate, timeout dei modelli, tempi per fase; esecuzione opzionale |
| `SemanticEvaluator` | Confronta risultati oracolo/candidato senza eseguire query |
| `SystemEvaluator` | Esegue e valuta il workflow sulla fixture attesa |
| `GenerationEvaluator` | Valuta il generatore senza dipendere dal guard del prompt |

`block` e `review` fermano entrambi la generazione. Un errore del modello,
del parser o del motore produce `error`, mai un successo di sicurezza.
Gli esiti del workflow distinguono `blocked_prompt`, `review_prompt`,
`blocked_query`, `blocked_runtime`, `query_ready`, `released`, `error`.

`PromptRequest` e un alias di `SparqlRequest`: validatore e generatore ricevono
lo stesso contesto, senza conversioni intermedie. `run(request)` esegue anche
la query e richiede un executor. `run(request, execute=False)` segue gli stessi
controlli sul prompt e sulla query, poi restituisce `query_ready` senza chiamare
il runtime. Questo stato non autorizza il rilascio di risultati: coorte e
controlli sui dati vengono verificati durante l'esecuzione.

Le stringhe di policy e permessi devono provenire dal servizio, non essere
accettate come autorita dalle dichiarazioni contenute nel prompt. I veri
permessi RDF sono quelli dei contesti configurati sull'esecutore. La demo usa
`DEFAULT_POLICY`, non il profilo hardened; per hardened occorrono anche i
contesti privacy e SHACL documentati nelle relative guide.

## Installazione ed esecuzione offline

```powershell
uv sync --locked --extra agents
uv run --extra agents python -m tools.evaluate_workflow --offline
uv run --extra agents python -m tools.evaluate_workflow --offline --component generation
uv run --extra agents python -m tools.evaluate_workflow --offline --component system
```

Il report e `artifacts/workflow-evaluation/report.json`. Contiene tre sezioni:
analizzatore statico, generatore isolato e sistema completo, con denominatori
espliciti, errori, query prodotte, risultati attesi/osservati e tempi per fase.
Le righe riportano il fingerprint dello snapshot RDF, controllato prima e dopo
il workflow. Il fingerprint ordina le quad: usarlo su piccole fixture di test,
non calcolarlo ad ogni richiesta su 50 GB.

La modalita offline usa agenti PydanticAI reali con `TestModel`, che ricevono
etichette e query gia note. E un test del collegamento tra componenti, non una
misura dell'intelligenza, della sicurezza o della velocita di un modello.

## Modelli locali

Il percorso consigliato, gia collegato a Ollama, Laya e MCP, e descritto nella
[guida ai modelli locali](local-models.md). Si configura in un solo JSON.
I paragrafi seguenti descrivono l'iniezione manuale di backend alternativi.

Per un modello gia servito tramite API compatibile OpenAI, sostituire MODEL_ID
con il suo identificativo effettivo:

```powershell
uv run --extra agents python -m tools.evaluate_workflow --model MODEL_ID --base-url http://localhost:11434/v1
```

`--guard-model` sceglie un guard generativo diverso sullo stesso endpoint.
L'endpoint deve supportare l'output strutturato/tool calling richiesto dagli
agenti; la CLI non avvia il server e non installa pesi. In questa modalita il
guard e un LLM generativo, non un modello System One.

Per un backend decisionale nativo, iniettare invece:

```python
from agent_orchestration import CallableSystemOneModel, Decision, SystemOnePromptValidator

def predict_native(request):
    # Collegare qui l'inferenza del modello scelto. La funzione deve restituire
    # una delle chiavi request.options; non inventare probabilita.
    answer = native_backend.predict(request.state, request.question, request.options)
    return Decision(choice=answer.choice, probability=answer.probability)

guard = SystemOnePromptValidator(CallableSystemOneModel(predict_native))
```

`native_backend` rappresenta il backend da fornire, non una dipendenza inclusa.
La soglia `min_allow_probability` e facoltativa; se configurata, una probabilita
mancante o insufficiente produce `review`. Non e una garanzia di calibrazione.

## Correlazione con il dataset esistente

`tests/fixtures/system/prompt_query_links.json` associa 36 prompt a 32 query
esistenti: una formulazione diretta per query, due parafrasi aggiuntive del
conteggio base, un'iniezione esplicita e una richiesta ambigua senza query.
Le associazioni sono scritte dal testo delle query e non hanno revisione clinica
indipendente. Sono una base di valutazione da ampliare con richieste reali.

I file `.rq` restano l'unica fonte delle query. Ogni riferimento ha SHA-256
del testo con fine riga normalizzati a LF:
se cambia il file, il caricamento segnala che va rivista l'associazione.
`uv run python -m tools.build_prompt_links` rigenera l'indice dalle annotazioni
nel tool: farlo solo dopo aver verificato che i prompt descrivano ancora le query.

Tenere tutti i prompt dello stesso `group_id` nello stesso split. Il corpus
attuale e destinato alla valutazione: non viene presentato come test indipendente
se viene riutilizzato per addestrare o ottimizzare il modello.

## Oracoli di esecuzione e confronto semantico

`tools/generate_workflow_fixtures.py` costruisce tre piccole fixture con 18, 24
e 30 pazienti fittizi e i risultati delle 11 query lecite. I risultati attesi
sono calcolati con conteggi e insiemi Python a partire dalla costruzione dei
dati, senza eseguire SPARQL. I test confrontano sia RDFLib sia il runtime
verificato contro questi oracoli. Sono coperti anche duplicati, assenze nei
rami OPTIONAL, date, intervalli numerici, join, UNION e MINUS.

I 36 prompt producono 108 valutazioni di sistema. I 13 prompt leciti, incluse
le parafrasi, producono anche 39 valutazioni isolate del generatore. Le 34
associazioni con query coprono 32 file distinti nell'analizzatore statico.
Le richieste da bloccare non hanno bisogno di eseguire una query oracolo.

`SemanticEvaluator` confronta SPARQL Results JSON: preserva duplicati, tipi e
forme lessicali RDF; ignora l'ordine di righe salvo `ordered=True`. Gli alias
di output richiedono un `column_mapping` esplicito candidato -> riferimento.
Risultati mancanti sono `not_evaluated`, blank node `unsupported`, payload
malformati `error`. Nessuna di queste condizioni equivale a `match`.
Non vengono confrontati grafi CONSTRUCT/DESCRIBE o numeri con tolleranze.

Questa validazione e offline: in produzione non si conosce la query oracolo di
ogni nuovo prompt. L'uguaglianza su tre fixture non prova equivalenza universale.
Un futuro giudice prompt-query online avrebbe un contratto e una valutazione
diversi. La correttezza della risposta resta separata dall'autorizzazione al
rilascio: i test includono una query sbagliata che supera i controlli di sicurezza.

## Test dei componenti e delle integrazioni

```powershell
uv run --extra agents pytest tests/agents/test_agent_models.py tests/agents/test_workflow.py -q
uv run --extra agents pytest tests/agents/test_pydantic_ai_integration.py -q
uv run --extra agents pytest -q
```

I test verificano arresto dopo un blocco, contesto trasferito al generatore,
output strutturato PydanticAI, inferenza decisionale tramite callback,
timeout/errori, analizzatore e runtime reali, confronto dei risultati e
correttezza delle associazioni. La suite PydanticAI viene saltata se manca
l'extra `agents`; i contratti di base restano utilizzabili senza SDK.

RDFLib e fissato a 7.1.4: con 6.3.2 i nuovi casi 17, 18 e 20 mostravano
`NotBoundError` durante COUNT DISTINCT su rami OPTIONAL senza corrispondenza.
L'aggiornamento corregge questo caso senza una patch globale del motore.

L'esecutore fornito e locale e sincrono: il timeout asyncio riguarda le chiamate
ai modelli, non interrompe il lavoro RDF sul thread chiamante. L'adattatore
decisionale sposta l'inferenza sincrona su un thread, ma la cancellazione non
uccide il thread. Per il dataset reale servono un servizio/processo con limiti
propri e il futuro adattatore verificato Virtuoso; questo workflow non carica
i 50 GB in memoria e non interroga il database reale.
