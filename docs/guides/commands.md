# Funzionalita e comandi

Tutti i comandi di questa pagina partono dalla radice del repository, con
Python 3.12+ e `uv` disponibili. `uv run` prepara l'ambiente con gli extra
indicati. I comandi Bash di avvio richiedono Linux o un ambiente equivalente.

## Log automatici nel codice

`sparql-run` e pytest del progetto principale scrivono automaticamente un file
per processo in `artifacts/logs/`, anche quando i test partono da VS Code.
Il percorso viene mostrato all'avvio. Non servono wrapper o redirezioni.
Il nome contiene comando, data UTC e PID; i file precedenti vengono conservati.

Il log contiene caricamento dei modelli, discovery MCP, richieste/risposte del
generatore, decisioni del classificatore, fasi del workflow, query, analisi,
risultati rilasciati, tempi e traceback degli errori. Ogni esecuzione del
workflow ha un `run` distinto, anche nello stesso processo. Pytest registra
gli esiti dei singoli test e il codice finale della sessione. Il JSON della CLI
resta su stdout; i report XML restano separati.

Le query compaiono in blocchi SPARQL con vere interruzioni di riga e separatori,
senza il `repr` Python che mostrava `\n` e apici esterni. Risultati e analytics
sono JSON indentato. La query restituita dalla funzione conserva il testo
originale del generatore. Il riepilogo dell'analisi e visibile a `INFO`; il report
completo con la configurazione dei controlli e disponibile a `DEBUG`.

Nel workflow il riepilogo `INFO` e responsabilita dell'orchestratore: prompt,
decisione, query e usage non vengono ripetuti dagli adapter. Usando un adapter
direttamente (anche negli health check), questo continua a stampare la propria
risposta. `DEBUG` include anche il dettaglio dei backend. Piu richieste HTTP
distinte possono essere normali turni di retrieval/generazione, non log duplicati.

Si usa il modulo standard `logging`, con un handler comune anche per i messaggi
delle librerie Python. `SPARQL_LOG_DIR` cambia cartella; `SPARQL_LOG_LEVEL`
cambia livello (`INFO` predefinito, `DEBUG` per maggior dettaglio). Non si
registra il JSON completo di configurazione o le chiavi API. I file contengono
invece prompt, query, risultati rilasciati e dettagli delle eccezioni.

Le stampe dirette di programmi esterni non passano da `logging`: vLLM e MCP
restano nei rispettivi log di servizio in `/workspace/logs/`. I test propri di
`LLM_ENGINE` usano la configurazione di quel sottoprogetto. Nessun trace dei
tool o del modello viene inventato se la libreria non lo emette al livello scelto.

## Quale percorso usare

| Obiettivo | Ingresso | Modelli | Dati / risultato |
|---|---|---|---|
| Prompt → query → risultato | `sparql-run --prompt ... --dataset ...` | Laya e LLM reali | RDF locale; risultato controllato o blocco |
| Prompt → sola query | `sparql-run --prompt ...` | Laya e LLM reali | Schemi MCP o testo; query analizzata, non eseguita |
| Verificare una query esistente | `sparql-check file.rq` | Nessuno | Analisi statica; nessuna esecuzione |
| Vedere il flusso senza pesi | `python -m examples.fake_workflow` | Fittizi | Fixture sintetica; esempi di rilascio, blocco e revisione |
| Verificare le integrazioni | `pytest -m offline_workflow` | Risposte controllate | Test offline, inclusi client HTTP e MCP locale di test |
| Valutare il corpus | `python -m tools.evaluate_workflow` | Predisposti o reali | Query e risultati confrontati con oracoli su fixture sintetiche |
| Gestire il database | Script in `infra/virtuoso/` | Nessuno | Virtuoso diretto; percorso separato dal runtime verificato |

## 1. Applicazione: dal prompt al risultato

Scegliere i modelli in [models.json](../../config/agents/models.json), poi su Linux:

```bash
bash start-mcp.sh
```

Tenere il server SPHN di `LLM_ENGINE` attivo; in un secondo terminale:

```bash
uv run --extra agents --extra mcp sparql-run --check-mcp
bash start-ollama.sh
uv run --extra local sparql-run --prompt "Conta i pazienti distinti con diagnosi fatturata" --dataset tests/fixtures/synthetic/cohort.trig
```

Percorso: Laya → LLM con recupero schema/esempi MCP → analisi statica →
runtime RDFLib → risultato. Il file dell'esempio e sintetico; i modelli sono
reali. `--dataset` accetta un file RDF locale, caricato in memoria; TriG e
N-Quads mantengono i grafi paziente distinti. `--rdf-format trig` forza il formato.

Omettendo `--dataset`, lo stesso comando si ferma alla query analizzata:

```bash
uv run --extra local sparql-run --prompt "Conta i pazienti distinti con diagnosi fatturata"
```

| Stato JSON | Significato |
|---|---|
| `released` | Esecuzione completata e risultato rilasciato nel campo `result` |
| `query_ready` | Query generata e analizzata; nessun controllo runtime sui dati eseguito |
| `blocked_prompt` / `review_prompt` | Generazione fermata dal validatore del prompt |
| `blocked_query` | Query rifiutata prima dell'esecuzione |
| `blocked_runtime` | Risultato soppresso dai controlli runtime |
| `error` | Errore di un componente; non equivale a un blocco di sicurezza riuscito |

La CLI stampa JSON; termina con 0 per `released` o `query_ready`, 1 per gli
altri esiti del workflow. `--help` elenca le opzioni. L'avvio puo fallire prima
del workflow se configurazione, file o servizi non sono disponibili.

`blocked_query` comprende anche funzionalita non supportate: controllare
`analysis.status` e `analysis.findings`. `unsupported` non significa che la
query abbia intenzioni malevole. I raggruppamenti esterni per categoria non
sono ancora eseguibili dal runtime predefinito; il solo toggle `category_group`
non estende il motore. Un caso concreto e nella [revisione della query per sesso](../security/query-by-sex-review.md).

Il JSON include `analytics.token_usage` e `analytics.timings`: token per modello
e fase, totale, conteggi parziali e tempi. Un totale `null` indica usage mancante
o incompleto, non consumo nullo. Vedere la [guida ai token](model-usage.md).

Questa CLI usa il profilo deterministico predefinito. I contesti fidati richiesti
dai profili privacy/SHACL piu restrittivi si collegano tramite l'API Python.
Il runtime non e ancora collegato a Virtuoso: `--dataset` non e un ingresso
per un database clinico da 50 GB. Setup e opzioni nella [guida locale](local-models.md).

## 2. Query gia disponibile

```bash
uv run sparql-check tests/fixtures/cases/00_compliant.rq --policy config/policies/default.json --out artifacts/query-check.json
uv run sparql-check --list-checks
```

Legge un file `.rq`, stampa il verdetto statico e puo salvarlo con `--out`.
Non esegue la query. Per provare anche il runtime su scenari predisposti:

```bash
uv run python -m examples.runtime_demo
```

Per un proprio dataset e una propria query, usare `execute_checked` nell'API
Python: [guida SPARQL](sparql.md).

## 3. Demo e test offline

```bash
uv run python -m examples.fake_workflow
uv run --extra agents --extra mcp pytest -m offline_workflow -q
```

La demo usa modelli fittizi e runtime reale su dati sintetici. I test coprono
anche errori, timeout, retry e concorrenza, senza pesi o servizi di inferenza.
Per la suite completa e un report XML:

```bash
uv run --extra agents --extra mcp pytest -q --junitxml=artifacts/tests/all.xml
```

Selezione delle suite in [tests/README.md](../../tests/README.md);
strategie di risposta nella [guida ai modelli fittizi](fake-models.md).

## 4. Benchmark con oracoli

Per verificare prima che i modelli reali configurati rispondano:

```bash
uv run --extra local pytest tests/health --run-model-health -v --junitxml=artifacts/tests/model-health.xml
```

Richiede una macchina adatta ai modelli e i servizi configurati attivi. Questi
test sono saltati nelle esecuzioni normali; non eseguono la query generata.
Comandi separati per classificatore e generatore in [tests/README.md](../../tests/README.md).

```bash
uv run --extra agents python -m tools.evaluate_workflow --offline
uv run --extra agents python -m tools.evaluate_workflow --offline --component generation
```

`--component` accetta `system`, `generation` o `all` (default). Il report JSON e
in `artifacts/workflow-evaluation/report.json`; `--out` cambia destinazione.
Il modo offline fornisce gia le risposte ai modelli: verifica il collegamento
tra componenti e oracoli, non l'accuratezza del modello.

Con Ollama attivo, per misurare invece i modelli configurati:

```bash
uv run --extra local python -m tools.evaluate_workflow --models-config config/agents/models.json
```

Anche questa valutazione esegue sui dataset sintetici, non sul database clinico.
Esclude il gruppo presente nell'esempio RAG. Per oracoli, split e denominatori
vedere la [guida al workflow](agent-workflow.md).

## 5. Configurazione, manutenzione e altri progetti

- [Configurazione](../../config/README.md): modelli, server, metadati MCP, policy e permessi.
- [Tools](../../tools/README.md): generazione fixture, associazioni prompt-query ed export.
- [Virtuoso](../../infra/virtuoso/README.md): avvio, caricamento e query dirette con Docker.
- [LLM_ENGINE](../../LLM_ENGINE/README.md): prototipo separato con proprio ambiente e comandi; non e il workflow verificato descritto sopra.

`sparql-run` e `sparql-check` appartengono al progetto principale.
`sparql-agent` e `sparql-benchmark` appartengono al sottoprogetto sperimentale
`LLM_ENGINE`: configurazioni, dipendenze e risultati non sono intercambiabili.
Il suo server MCP SPHN viene invece riutilizzato dal workflow via HTTP;
`start-mcp.sh` lo avvia nell'ambiente separato. `--check-mcp` esegue solo
discovery degli strumenti, senza caricare modelli o inviare query cliniche.
