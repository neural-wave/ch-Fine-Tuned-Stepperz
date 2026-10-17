# Virtuoso: avvio e caricamento

Questa cartella gestisce un triplestore Virtuoso tramite Docker. Servono Bash,
Docker attivo e `unzip` se si caricano archivi di ontologie. Eseguire i comandi
dalla radice del repository, su Linux o in un ambiente Bash con accesso a Docker.

Il triplestore e indipendente dal [workflow Python](../../docs/guides/agent-workflow.md):
i test offline non richiedono Docker. Gli script `query.sh` e l'endpoint SPARQL
eseguono query direttamente, senza passare dal controllore privacy Python.

Per valutare la classificazione dei prompt e i tempi delle query su questo
database usare il [package separato system_validation](../../system_validation/README.md).
Il suo comando `prepare` richiama questi loader e verifica il caricamento completo
della cartella selezionata prima del benchmark. Non modifica il workflow dell'API.

## Avvio

Inserire i file paziente Turtle in `patients/`, poi eseguire:

```bash
chmod +x infra/virtuoso/scripts/*.sh
bash infra/virtuoso/scripts/start.sh
bash infra/virtuoso/scripts/load-patients.sh
bash infra/virtuoso/scripts/query.sh infra/virtuoso/queries/count-per-graph.rq
```

`start.sh` crea il container, registra il bulk loader e carica `ontologies/`.
Se il container esiste gia, lo riusa. L'endpoint e
[http://localhost:8890/sparql](http://localhost:8890/sparql).
Il `chmod` serve al primo avvio su Linux: gli script si richiamano anche tra loro.

## Dati e grafi

- Il loader considera soltanto i file `*.ttl` direttamente in `patients/`;
  non visita sottocartelle.
- Ogni file rappresenta un paziente. `patient-42.ttl` diventa il grafo
  `http://example.org/graph/patient-42`, con prefisso configurabile.
- Il caricamento e additivo. Dopo aver modificato o rimosso file, usare
  `load-patients.sh --reset` per eliminare anche le vecchie triple.
- Gli script modificano il database, senza cancellare i Turtle sorgenti.

I file vengono accodati in `DB.DBA.load_list` e caricati da worker paralleli.
Durante il bulk load sono disattivati checkpoint periodici e logging
transazionale; vengono ripristinati all'uscita dello script.

## Comandi disponibili

Tutti gli script sono in [`scripts/`](scripts/).

| Script | Funzione |
| --- | --- |
| `start.sh` | Crea, avvia o riprende il container e carica le ontologie mancanti. |
| `load-patients.sh [--reset]` | Carica i Turtle; `--reset` svuota prima i grafi con `GRAPH_URI_PREFIX`. |
| `load-ontologies.sh [--force]` | Carica le ontologie; `--force` svuota e ricarica il loro grafo. |
| `query.sh <file.rq oppure testo> [--out file]` | Esegue la query e stampa risultati e tempo riportato da Virtuoso. |
| `status.sh` | Mostra stato del container, grafi e triple caricati. |
| `reset-patients.sh` | Svuota i grafi con il prefisso pazienti, mantenendo le ontologie. |
| `stop.sh` | Esegue un checkpoint e ferma il container, conservando il database. |
| `destroy.sh` | Rimuove il container e il database al suo interno. |

I dati persistono tra `stop.sh` e `start.sh`; `destroy.sh` richiede poi un
nuovo caricamento. Non viene configurato un volume separato per il database.

## Ontologie e inferenza

`start.sh` carica i file `ontologies/*.ttl` e i Turtle contenuti negli archivi
`ontologies/*.zip` in un unico grafo, registrato come rule set RDFS.
Gli archivi estratti restano in `.ontology_cache/`. Se si sostituisce un archivio,
aggiornare anche la relativa copia in cache prima di ricaricare.

Il loader legge [`ontologies/`](../../ontologies/), mentre gli schemi per il
generatore sono descritti in [`schemas/`](../../schemas/README.md). Caricare
un'ontologia non esegue la validazione SHACL.

Le query possono richiedere l'inferenza con la sintassi specifica di Virtuoso:

```sparql
?lab_test rdf:type sphn:LabTest
  OPTION (inference "https://biomedit.ch/rdf/sphn-resource/global") .
```

Il rule set deve essere stato caricato e il suo URI deve coincidere con
`RULE_SET_URI`. Gli esempi in [`queries/`](queries/) mostrano conteggi,
classi presenti e inferenza.

## Configurazione

Le variabili di [`config.sh`](scripts/config.sh) si possono impostare
nell'ambiente. Mantenere gli stessi valori tra i comandi:

```bash
export PATIENTS_DIR=/percorso/coorte
export VIRTUOSO_RAM_GB=4
bash infra/virtuoso/scripts/start.sh
bash infra/virtuoso/scripts/load-patients.sh
```

| Variabile | Valore predefinito |
| --- | --- |
| `VIRTUOSO_VERSION` | `7.2.16` |
| `CONTAINER_NAME` | `hackathon-virtuoso` |
| `DBA_PASSWORD` | `dba` (configurazione di esempio) |
| `ISQL_HOST_PORT` / `HTTP_HOST_PORT` | `1111` / `8890` |
| `PATIENTS_DIR` / `ONTOLOGIES_DIR` | `patients/` / `ontologies/` nella radice del progetto |
| `ONTOLOGY_CACHE_DIR` | `.ontology_cache/` nella radice del progetto |
| `GRAPH_URI_PREFIX` | `http://example.org/graph/` |
| `RULE_SET_URI` | `https://biomedit.ch/rdf/sphn-resource/global` |
| `LOAD_WORKER_COUNT` | `8` |
| `VIRTUOSO_RAM_GB` | Budget calcolato dall'80% della RAM riportata da Docker |

Il numero di buffer usa il 65% del budget RAM e i dirty buffer il 75% dei buffer.
Mount, immagine, porte e password sono fissati alla creazione del container:
modificare le variabili non riconfigura un container esistente. Per cambiarli
occorre ricrearlo, perdendo il database caricato; conservare i file sorgenti.

## Problemi comuni

- **Docker assente o fermo:** verificare `docker info` e avviare il daemon.
- **Porte occupate:** impostare `HTTP_HOST_PORT` e `ISQL_HOST_PORT` libere prima
  di creare il container.
- **Caricamento incompleto:** controllare gli errori stampati dal loader e i log
  con `docker logs hackathon-virtuoso` (adattare il nome se configurato).
- **Nessun risultato:** usare `status.sh` e `query.sh infra/virtuoso/queries/classes.rq`
  per confrontare dati caricati e pattern della query.
- **Rule set non definito:** aggiungere le ontologie e rieseguire
  `load-ontologies.sh`; dopo modifiche a ontologie gia caricate usare `--force`.

Le risorse SNOMED CT fornite per l'hackathon restano soggette alle relative
restrizioni: l'uso o la distribuzione fuori dall'hackathon richiedono la licenza
prevista tramite MLDS.
