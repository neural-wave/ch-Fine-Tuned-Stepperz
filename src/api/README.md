# API NL-to-SPARQL

`POST /nl-to-sparql` traduce un prompt, valuta la conformita e restituisce query
e token consumati. Il flusso e **controllo del prompt → generazione → analisi
statica**. L'esecuzione della query resta al client; l'API non richiede Virtuoso.

Tutti i comandi seguenti partono dalla **radice del repository**, non da questa
cartella. Servono Python 3.12+, uv e il servizio di inferenza gia avviato.
Su Linux, `start-api.sh` avvia il MCP SPHN locale in una sessione tmux se non
risponde, poi ne verifica gli strumenti prima di avviare l'API. Gli avvii
diretti con Uvicorn o debugger richiedono invece il MCP gia attivo.
L'API carica Laya all'avvio e riusa i backend tra le richieste.

## Avvio

Su Linux:

```bash
bash start-api.sh
```

Su Windows, direttamente da PowerShell senza Bash/WSL:

```powershell
uv run --locked --extra local --extra api python -m uvicorn api.server:app --host 127.0.0.1 --port 8000
```

Con `start-api.sh`, aprire la [frontpage](http://127.0.0.1:10100/) per inserire
una domanda in linguaggio naturale e vedere query, verdetto e tempi; con il
comando Windows sopra, usare la porta `8000`. La pagina usa
`POST /study/nl-to-sparql` sullo stesso host dell'API. Aprire anche
[Swagger](http://127.0.0.1:10100/docs) per provare direttamente le richieste.
`GET /health` restituisce `{"status":"ok"}` senza fare inferenza.
Lo schema OpenAPI e disponibile su `/openapi.json`.

Per controllare anche modello e schema MCP:

```bash
uv run --locked --extra validation --extra agents --extra mcp python -m system_validation check
```

Aggiungere `--inference` per una chiamata reale attraverso l'API gia attiva.
Impostare `api_url` in `system_validation/config.json` alla porta effettiva
dell'API. Dettagli nella [guida dell'infrastruttura](../../system_validation/README.md).

Per esporre l'API su un'istanza Linux:

```bash
bash start-api.sh --host 0.0.0.0 --port 8000
```

Il client deve usare l'IP dell'istanza e la porta pubblica corrispondente a 8000.
Modello e MCP possono restare raggiungibili soltanto dalla macchina dell'API.
L'API attuale non include autenticazione: per prove private usare un tunnel SSH
o limitare l'accesso di rete ai client previsti.

## Configurazione

| File | Cosa configurare |
|---|---|
| [models.json](../../config/agents/models.json) | Modello da avviare con lo script remoto, indirizzo chat, Laya, MCP e modalita `prefetch`/`agentic` |

All'avvio l'API legge `base_url` + `/models` (nel preset,
`http://127.0.0.1:18000/v1/models`) e usa l'`id` servito. Se il server espone piu modelli, sceglie
quello presente in `model`; senza una corrispondenza interrompe l'avvio. Il JSON
rimane la sorgente del modello che `LLM_ENGINE/start_remote.sh` deve avviare.
| [policy.txt](../../config/agents/policy.txt) | Policy testuale fornita ai modelli |
| [permissions.txt](../../config/agents/permissions.txt) | Permessi forniti al controllo del prompt |

Non serve un `.env`. L'unica variabile specifica dell'API, facoltativa, e
`NL2SPARQL_CONFIG`: sceglie un JSON dei modelli diverso da quello predefinito.
Policy e permessi restano nei file sopra; i controlli statici usano `DEFAULT_POLICY`.

Sulla VM, dopo `bash LLM_ENGINE/start_remote.sh`:

```bash
bash start-api.sh --host 0.0.0.0 --port 8000
```

Per scegliere un altro JSON da PowerShell, prima del comando di avvio:

```powershell
$env:NL2SPARQL_CONFIG = "percorso/models.json"
```

## Debugger Python in VS Code

Aprire la radice del repository in VS Code, scegliere **API: Python debugger**
nel pannello **Run and Debug** e premere **F5**. La configurazione condivisa e
in [.vscode/launch.json](../../.vscode/launch.json): avvia Uvicorn sulla porta
`10100` usando `.venv`, sia su Windows sia su Linux/Remote SSH.
Servono l'estensione Python Debugger e l'ambiente gia preparato con
`uv sync --locked --extra local --extra api`; il debugger carica Laya e si collega a vLLM e MCP gia attivi.

Impostare i breakpoint in `server.py` o `service.py`, poi inviare una richiesta.
Il debugger usa lo stesso `config/agents/models.json` di API, CLI e test.
Non occorre un JSON remoto o una variabile per il percorso standard.
Non e necessario avviare prima `start-api.sh`.

## Richiesta e risposta

Il corpo contiene soltanto il testo della richiesta:

```json
{"text":"Count distinct patients with at least one BilledDiagnosis. Return patients."}
```

Da PowerShell:

```powershell
$body = @{ text = "Count distinct patients with at least one BilledDiagnosis. Return patients." } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/nl-to-sparql" -ContentType "application/json" -Body $body
```

Da Bash:

```bash
curl http://127.0.0.1:8000/nl-to-sparql \
  -H 'Content-Type: application/json' \
  -d '{"text":"Count distinct patients with at least one BilledDiagnosis. Return patients."}'
```

La risposta contiene:

| Campo | Significato |
|---|---|
| `sparql_query` | Testo originale della query generata |
| `tokens_consumed` | Token totali di classificazione e generazione, inclusi i retry conteggiati dai backend |
| `is_compliant` | `true` solo se controllo del prompt e analisi statica approvano |
| `compliance_reason` | Motivazione presente soltanto quando `is_compliant` e `false` |

Una query non conforme viene restituita con **HTTP 200** e verdetto negativo.
Anche se il classificatore blocca il prompt, viene prodotta una query da valutare:
non viene eseguita ne trasformata in una richiesta diversa per renderla conforme.
Gli errori tecnici sono risposte di errore, non verdetti di non conformita.

Se la ricerca MCP risponde correttamente ma non trova ne esempi ne classi,
e non sono configurate `retrieval_classes`, l'API restituisce **HTTP 400** con
un messaggio che chiede di specificare l'entita clinica o fornire suggerimenti
esatti. Per esempio, «conteggio aggregato sul dataset clinico» non specifica
cosa contare; «conta i pazienti» rende esplicita l'entita. Il retrieval attuale
usa corrispondenze lessicali: anche termini non riconosciuti possono produrre
una ricerca vuota. Non viene scelta una classe arbitraria e il generatore
non viene chiamato.
L'endpoint `/study/nl-to-sparql` conserva nelle analytics il verdetto originale
del classificatore, i token conosciuti e `generation_metadata.retrieval` con
`status: "no_match"` e gli hints usati; `model_called` e `false`.
Connessioni MCP fallite, risposte malformate o schemi mancanti nonostante
suggerimenti espliciti restano **HTTP 502**. Nessuno di questi casi costituisce
un'approvazione o un rifiuto di sicurezza.

## Correzione della query con feedback

In [models.json](../../config/agents/models.json) impostare `query_retries` e
riavviare l'API. Il preset contiene `0`, che mantiene una sola generazione.
Con `2` si consentono al massimo tre generazioni: la prima e due correzioni.
Il valore deve essere un intero non negativo; non e controllato dal prompt.

Per ogni query rifiutata, il generatore riceve il prompt originale, schema,
policy e permessi invariati, piu `feedback` con query precedenti, stato e
finding del checker (`check`, `code`, `reason`, operatori vietati). Non vengono
disattivate regole. Il ciclo si ferma al primo esito statico positivo o al
limite configurato. Anche `unsupported` puo generare feedback per una correzione.
Errori tecnici e timeout interrompono la richiesta: non sono retry del checker.

Un prompt `block` o `review` mantiene il verdetto negativo: l'API genera la
query per la valutazione, come prima, ma non tenta di correggerla. Il generatore
riceve l'istruzione di preservare significato, coorte, filtri e output richiesti:
non deve eliminare condizioni o cambiare la domanda per ottenere un'approvazione.
La conformita statica non certifica da sola l'equivalenza semantica o la privacy
runtime; quest'ultima resta responsabilita dell'esecutore.

Nell'endpoint di studio, `analytics.query_attempts` contiene ogni tentativo:
numero, query, `analysis` completo, `failed_checks`, `token_usage`, metadati e
tempi. `analytics.query_retry` riporta budget, retry usati e motivo di arresto
(`accepted`, `retry_limit`, `prompt_not_allowed`, `error`). Con retry abilitati,
anche l'endpoint ordinario restituisce `query_attempts` senza richiedere header.
La query principale e il verdetto riguardano l'ultimo tentativo completato;
se il budget e esaurito resta un verdetto negativo, con HTTP 200.

I token includono il classificatore e tutte le generazioni, senza contare due
volte i tentativi. Le fasi successive si chiamano `generation_retry_1`,
`analysis_retry_1` e cosi via. Il dettaglio resta disponibile anche negli errori
dell'endpoint di studio. Il limite temporale HTTP esistente comprende l'intero
ciclo; aumentare i retry puo richiedere un timeout client adeguato.

## Analytics e log

### Endpoint di studio

`POST /study/nl-to-sparql` accetta lo stesso JSON dell'endpoint ordinario e
restituisce sempre `analytics`, senza richiedere `X-Include-Analytics`.
Usa lo stesso workflow e gli stessi backend gia caricati, con la stessa coda
di inferenza e il budget di correzioni configurato.

```bash
curl http://127.0.0.1:10100/study/nl-to-sparql \
  -H 'Content-Type: application/json' \
  -d '{"text":"How many patients are in the database?"}' \
  -o study.json
python -m json.tool study.json
```

La risposta conserva `sparql_query`, `tokens_consumed`, `is_compliant` ed
eventuale `compliance_reason`. `analytics` contiene:

| Campo | Contenuto |
|---|---|
| `status`, `executed` | Stato del workflow; `executed` e sempre `false`, perche l'API non interroga il database |
| `token_usage` | Totali e dettaglio per fase: input, output, modello, fonte, completezza, richieste/retry, cache e reasoning quando disponibili |
| `timings` | Secondi per `prompt_validation`, `generation`, `analysis`, `total`, attesa del lock `queue` e `request_total` |
| `prompt_assessment` | Decisione, motivazione e probabilita del classificatore, quando disponibile |
| `prompt_decision` | Decisione sintetica, compatibile con il benchmark esistente |
| `query_analysis` | Report completo dell'analizzatore: stato, finding, violazioni, operatori vietati e configurazione delle regole |
| `prompt_metadata`, `generation_metadata` | Metadati prodotti dai backend; in prefetch, `retrieval` riporta numero di classi/esempi, IRI delle classi e tempo del recupero |
| `effective_output_tokens_per_second` | Token output divisi per tempo della fase; `null` se non misurabile |
| `request` | ID, prompt elaborato, `received_at` e `finished_at` in UTC; l'ID e registrato anche nel log |

`total` misura il workflow. `request_total` misura l'handler fino alla
preparazione della risposta, includendo la coda ma escludendo serializzazione
finale e rete verso il client. Il tempo `generation` include il prefetch MCP.
Il throughput e una misura effettiva della fase, non il solo decoder o il TTFT.
La risposta non contiene risultati di esecuzione SPARQL, accuracy o precision:
queste ultime richiedono etichette e si calcolano nel benchmark.

Gli errori tecnici rimangono HTTP 502/504 con il messaggio pubblico generico.
Su questo endpoint includono anche `analytics` parziali, `status: "error"` e,
se il workflow era partito, `failed_stage`. I token dei passi completati e i
contatori parziali del backend sono conservati; quelli sconosciuti rimangono
`null`, con `known_total_tokens` per la somma nota. Un timeout mentre si
attende il lock puo avere solo i tempi della richiesta, senza contatori modello.
Se la query era gia stata generata prima dell'errore, viene restituita anche
`sparql_query`, insieme alle metriche parziali.
Non vengono restituite le stringhe delle eccezioni interne o il contenuto dei
file di log. Input non valido restituisce il normale errore 400 prima dei modelli.

### Endpoint ordinario

Aggiungere l'header `X-Include-Analytics: true` per ottenere anche `analytics`:

```bash
curl http://127.0.0.1:8000/nl-to-sparql \
  -H 'Content-Type: application/json' \
  -H 'X-Include-Analytics: true' \
  -d '{"text":"Count distinct patients with BilledDiagnosis."}'
```

Il campo include `prompt_decision`, `token_usage` con dettaglio per fase/modello
e `timings` in secondi per controllo del prompt, generazione, analisi e totale.
I contatori cache/reasoning sono presenti quando forniti dal backend.
Il [package di validazione](../../system_validation/README.md) usa questi dati
per salvare metriche informative, senza soglie o assert sulle prestazioni.

Query, conteggi dei token ed errori vengono registrati in `artifacts/logs/`.
I log dei servizi vLLM/MCP rimangono separati da quelli dell'API.

All'avvio l'API stampa `API logging file=...` con il percorso assoluto del file
`sparql-api-<timestamp>-<PID>.log`. I messaggi del workflow sono visibili anche
nel terminale. Ogni richiesta HTTP registra metodo, percorso, stato e durata,
incluse `/health`, richieste non valide ed errori prima dell'inferenza.
Il file riceve anche i messaggi e gli access log di Uvicorn. Query e token sono
registrati indipendentemente dall'header `X-Include-Analytics`, che controlla
solo il contenuto della risposta HTTP.

Se un'altra configurazione di logging rimuove o chiude il gestore del file,
la richiesta successiva lo ripristina mantenendo il contenuto gia scritto.
Il ripristino riabilita anche i logger applicativi eventualmente disattivati
da `dictConfig` e ripristina la propagazione e il livello centralizzato.
Se il file non esiste piu, viene ricreato sullo stesso percorso alla richiesta
successiva. Il ripristino del solo gestore root non basta: un logger nominato
con `disabled=True` scarta i messaggi prima che raggiungano il file.
`SPARQL_LOG_DIR` cambia directory e `SPARQL_LOG_LEVEL` cambia livello;
il valore predefinito `INFO` include richieste, query e token.
Per seguire il file usare il percorso stampato all'avvio:

```bash
tail -F /percorso/assoluto/stampato/dal/server.log
```

## Errori e limiti

| HTTP | Significato |
|---|---|
| 400 | JSON non valido o `text` non stringa, vuoto o oltre 16384 caratteri |
| 502 | Errore dei backend/controlli o contatori token assenti, incompleti o stimati |
| 504 | Superato il timeout di 120 secondi, inclusa la coda delle richieste |
| 500 | Errore interno |

Gli errori hanno forma `{"error":"..."}`. Le richieste vengono servite una alla
volta per processo. Il verdetto riguarda SPARQL standard e il controllo statico:
non verifica risultati, dimensioni delle coorti o equivalenza semantica sul database.
`DEFINE`, `OPTION(inference)` e altre estensioni specifiche dei database sono
segnalate come non supportate, senza rimuoverle dal testo della query.

Se compare `address already in use`, controllare il processo sulla porta scelta:

```bash
ss -ltnp '( sport = :8000 )'
```

Se la porta e libera, avviare con `bash start-api.sh --host 0.0.0.0 --port 8000`.
Se e occupata, scegliere una porta interna libera e verificare la sua mappatura
pubblica nell'istanza. Il nuovo script controlla prima le porte in ascolto quando
`ss` e disponibile, senza caricare i modelli se trova un conflitto. Le opzioni
esplicite prevalgono su eventuali `UVICORN_HOST`/`UVICORN_PORT` dell'immagine.

L'avvio usa l'ambiente `.venv` del progetto anche se la shell ha attivo
`/venv/main`: non occorre usare `uv --active`. Lo script rimuove `VIRTUAL_ENV`
solo dal proprio processo per evitare il warning, lasciando attiva la shell originale.

## Test senza modelli

```bash
uv run --locked --extra api --extra agents --extra mcp pytest tests/api -q
```

I test usano backend simulati. Per configurare lo stack reale vedere la
[guida ai modelli](../../docs/guides/local-models.md); per i dettagli del flusso
e dei vincoli vedere la [guida HTTP](../../docs/guides/http-api.md).
