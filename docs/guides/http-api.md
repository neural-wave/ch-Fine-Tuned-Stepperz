# API HTTP

Per avvio rapido, esempi PowerShell/Bash e campi della risposta vedere il
[README dell'API](../../src/api/README.md).

`POST /nl-to-sparql` riceve `{"text": "..."}` e restituisce:

```json
{
  "sparql_query": "SELECT ...",
  "tokens_consumed": 1287,
  "is_compliant": true
}
```

Se il controllo fallisce, restituisce comunque HTTP 200, la query originale,
`is_compliant: false` e `compliance_reason`. Non esegue query e non si collega
a database: il client decide dove e se eseguirle.

## Avvio

Dalla radice su Linux, con modello e MCP gia avviati:

```bash
bash start-api.sh
```

Per usare la configurazione della VM ed esporre l'API al client:

```bash
NL2SPARQL_CONFIG=artifacts/tests/models.remote.json bash start-api.sh --host 0.0.0.0 --port 8000
```

Il file remoto viene creato da `start-and-test.sh`. In alternativa usare un proprio
JSON con `model`, `base_url`, `laya` e `mcp_url`, come per `sparql-run`.
Il comando equivalente senza script e:

```bash
uv run --locked --extra local --extra api uvicorn api.server:app --host 127.0.0.1 --port 8000
```

Su Windows eseguire direttamente da PowerShell, senza `bash`:

```powershell
uv run --locked --extra local --extra api python -m uvicorn api.server:app --host 127.0.0.1 --port 8000
```

Il `bash` di WSL usa un ambiente diverso e puo non trovare `uv.exe` installato
in Windows. L'avvio dell'API carica i backend reali; per una prova senza pesi
usare il comando `pytest tests/api -q` riportato in fondo alla guida.

Prova da un altro terminale:

```bash
curl http://127.0.0.1:8000/nl-to-sparql \
  -H 'Content-Type: application/json' \
  -d '{"text":"Count distinct patients with BilledDiagnosis"}'
```

Swagger e disponibile su `/docs`, lo schema su `/openapi.json`.
`GET /health` verifica che il processo sia pronto, senza fare inferenza.
`--host` e `--port` cambiano indirizzo e porta (default `127.0.0.1:8000`).
Il timeout e di 120 secondi, inclusa l'attesa delle richieste precedenti.

## Flusso e limiti

L'API riusa Laya e il generatore di `agent_orchestration`, caricandoli una volta
all'avvio. Usa `generation_mode` e MCP del JSON; non importa il codice Python di
`LLM_ENGINE` e non unisce i due ambienti. Le richieste sono serializzate per
riusare il backend. La generazione mantiene i retry strutturati gia presenti
in PydanticAI; l'API non aggiunge un altro ciclo di generazione.

Il flusso e: valutazione del prompt, traduzione fedele, analisi statica. Per
restituire query e verdetto anche nei casi negativi, l'API genera una query
anche quando Laya risponde `block` o `review`, mantenendo il verdetto negativo.
Non modifica una richiesta vietata in una richiesta aggregata apparentemente
sicura. `sparql-run`, che puo eseguire query, continua invece a fermarsi subito
se il controllo del prompt non passa.

`tokens_consumed` somma classificazione e generazione, comprese le chiamate/retry
conteggiate dal backend. L'analisi statica non consuma token. Se i contatori sono
assenti, incompleti o stimati, l'API restituisce un errore: non inventa uno zero.
Il dettaglio per modello e la query sono nei log in `artifacts/logs/`.
Per il [package di validazione](../../system_validation/README.md), l'header
`X-Include-Analytics: true` aggiunge il campo `analytics` con token per fase,
tempi e decisione del classificatore. Senza header il JSON standard resta uguale.

Policy e permessi si modificano in `config/agents/policy.txt` e
`config/agents/permissions.txt`. Lo schema viene recuperato dal MCP configurato
nel JSON. I controlli deterministici usano `DEFAULT_POLICY`.
L'unica variabile specifica dell'API e `NL2SPARQL_CONFIG`, facoltativa, per
scegliere un JSON diverso da `config/agents/models.json`. Non serve un `.env`.

Il parser controlla SPARQL standard: nessuna gestione di `DEFINE`,
`OPTION(inference)` o altre estensioni di database. Queste sono segnalate come
non supportate, senza rimuoverle dalla query. Il client puo aggiungere opzioni
specifiche del proprio database, ma il verdetto non copre la query modificata.

Il verdetto combina il controllo del prompt e quello statico. Non verifica i
risultati, le dimensioni delle coorti o la correttezza semantica sul database.
Il documento dei [vincoli](../specifications/Query_Compliance.md) richiede
`SELECT` aggregate: anche ASK/CONSTRUCT/DESCRIBE sono rifiutate, nonostante la
descrizione piu ampia presente nella [specifica API originale](../specifications/API_specification.md).

| HTTP | Significato |
|---|---|
| 200 | Query generata e valutata; puo essere non conforme |
| 400 | JSON/testo non valido, vuoto o oltre 16384 caratteri |
| 502 | Errore di modello/MCP/controllo o contatori token non utilizzabili |
| 504 | Timeout |
| 500 | Errore interno |

Gli errori hanno sempre forma `{"error": "..."}`; dettagli tecnici nei log.

Test senza modelli o servizi:

```bash
uv run --locked --extra agents --extra mcp pytest tests/api -q
```
