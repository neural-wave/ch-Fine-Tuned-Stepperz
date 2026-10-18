# Validazione end to end

Package separato da `src/`. Chiama l'API HTTP reale, misura il verdetto rispetto
a prompt etichettati e, opzionalmente, usa Virtuoso per i tempi delle query benigne approvate.
Non carica modelli: API e modello possono essere su un'altra macchina.
Le metriche sono informative, senza assert, soglie o esito pass/fail.

## Controllare l'infrastruttura

Dalla radice del repository, sulla macchina che raggiunge i servizi:

```bash
# Stato di API, modello configurato e recupero schema MCP; nessuna inferenza
uv run --locked --extra validation --extra agents --extra mcp python -m system_validation check
# Anche una traduzione reale: classificatore Laya e generatore tramite API
uv run --locked --extra validation --extra agents --extra mcp python -m system_validation check --inference
# Anche Virtuoso: ricevuta di preparazione, sorgenti e inventario dei dati caricati
uv run --locked --extra validation --extra agents --extra mcp python -m system_validation check --inference --with-virtuoso
```

Il controllo ordinario legge `config/agents/models.json` per modello e MCP e
`system_validation/config.json` per `api_url`. Verifica `/health`, la presenza
del modello in `/v1/models` e le risposte reali dei tool MCP per una domanda
sui pazienti. Non avvia server e non carica modelli nel processo di controllo.
Il quick check non prova l'inferenza di Laya; per questo usare `--inference`,
che chiama l'API gia attiva senza caricare una seconda copia dei pesi.
Un verdetto `block` o `review` puo superare questo health check: qui si verifica
il funzionamento del sistema, non la correttezza della classificazione.

Ogni servizio produce `[OK]` o `[FAIL]`. Vengono controllati tutti anche se uno
non risponde; il comando restituisce 0 solo se tutti i controlli richiesti
riescono, altrimenti 1. Salva `health-<timestamp>.json` in
`artifacts/system-validation/` e il log ordinario in `artifacts/logs/`.
Le opzioni non richieste non sono verificate. `--with-virtuoso` richiede
`prepare` gia completato, Docker e accesso locale alle sorgenti come il runner.
Non modifica o carica dati.

Per avviare i servizi sull'istanza Linux:

```bash
# Avvia o riusa vLLM e MCP; i servizi restano in tmux
bash LLM_ENGINE/start_remote.sh
# Avvia l'API in primo piano: lasciare questo terminale aperto
bash start-api.sh --host 0.0.0.0 --port 8000
```

In un secondo terminale eseguire `check`. Se l'API usa 10100 (come il debugger),
impostare `api_url` a `http://127.0.0.1:10100` nel JSON di validazione.
Su Linux sono utili anche `tmux ls`, `ss -ltnp` e `nvidia-smi` per ispezionare
sessioni, porte e GPU. Una porta aperta o un processo presente non dimostrano
che il servizio risponda correttamente: usare `check` per quello.

## Valutare tutti i prompt

Con API, generatore e MCP gia attivi, dalla radice del repository:

```bash
# Smoke test: tre prompt, senza richiedere Virtuoso
uv run --locked --extra validation python -m system_validation run --api-only --limit 3 --label smoke
# Tutto il corpus, senza caricare o interrogare il database
uv run --locked --extra validation python -m system_validation run --api-only --label qwen-prefetch
```

`--api-only` esercita il percorso HTTP completo: classificatore del prompt,
generazione SPARQL e analisi statica. Non verifica esecuzione o risultati della
query. Per aggiungere Virtuoso omettere quel flag, dopo `prepare` come sotto.
Non avvia modelli o servizi: il server API deve essere gia raggiungibile su
`api_url` di [config.json](config.json), porta 8000 nel preset. Se l'API usa
10100, modificare quell'indirizzo.

Ogni avvio crea una cartella in `artifacts/system-validation/<timestamp>/`:

| File | Contenuto |
|---|---|
| `cases.json` | Corpus effettivamente selezionato, etichette e provenienza |
| `execution.log` | Inizio/fine di ogni caso, prompt, risposta con query e analytics, errori e traceback |
| `trials.jsonl` | Una riga per chiamata, warmup inclusi: verdetto, correttezza, token e tempi |
| `trials.csv` | Tabella con giudizio atteso/ottenuto, `correct`, `outcome`, tempi e token |
| `summary.json` | Metriche globali, per categoria e per caso; configurazione e hash dei sorgenti |
| `metrics.log` | Copia leggibile delle metriche |

I report vengono aggiornati durante la valutazione. Il log ordinario dell'API
rimane nella macchina del server, in `artifacts/logs/`; `execution.log` raccoglie
cio che osserva il client, senza acquisire i log interni di un server remoto.
Per confrontare strategie cambiare `--label` e conservare tutti i report.

## Dati di validazione

Il preset `cases_files` unisce i tre JSONL in [benchmark](../benchmark/README.md)
con [data/prompts.json](data/prompts.json) e
[data/clinical-examples.json](data/clinical-examples.json): attualmente 271 prompt
distinti, 151 consentiti e 120 vietati secondo le etichette delle sorgenti.
I JSONL contengono 82 prompt distinti; le versioni
successive ripetono molti degli stessi casi. Si deduplica per testo del prompt
(ignorando solo spazi iniziali/finali), conservando tutte le provenienze.
Non sono 234 osservazioni indipendenti. La prima versione nell'elenco fornisce
i metadati del caso; etichette discordanti interrompono il caricamento e devono
essere risolte prima di valutare. Nessuna etichetta viene corretta automaticamente.

Il corpus locale contiene 178 casi: i 18 iniziali e 160 nuovi prompt in 40
famiglie di confronto. Ogni nuova famiglia include una richiesta consentita e
una vietata in due lingue, con `group`, `language`, `difficulty` e `label_reason`
per ispezionare provenienza e motivazione dell'etichetta. Copre italiano e inglese,
con ulteriori casi in francese e tedesco. Include negazioni, attacchi citati,
SPARQL nel prompt, identificativi mascherati, inferenza di appartenenza,
differencing, esfiltrazione, modifiche ai dati e falsi messaggi di sistema.
La [guida dei casi](data/README.md) descrive copertura e limiti delle etichette.

Sono inclusi anche tutti i 15 prompt originali di
[clinical-examples.md](../examples/queries/clinical-examples.md), con fonte e
query di riferimento conservate senza riscritture. Quattro erano gia nei
benchmark: aggiungono 11 prompt distinti. Il caso clinico 13 mantiene l'etichetta
non conforme della fonte per la scansione libera della query, ma il prompt
chiede totali aggregati: non e un ground truth affidabile di intenzione malevola.
Il caso 3 chiede qualsiasi rango diagnostico, mentre la query fornita filtra
`Principal`: il riferimento non e un oracolo semantico. Le note sono nel dataset.

Per eseguire solo gli esempi clinici:

```bash
uv run --locked --extra validation python -m system_validation run --api-only --cases system_validation/data/clinical-examples.json --label clinical-examples
```

Per eseguire soltanto questo corpus, senza Virtuoso:

```bash
uv run --locked --extra validation python -m system_validation run --api-only --cases system_validation/data/prompts.json --label contrast-prompts
```

Il comando usa il workflow esistente: classificatore, generazione e checker.
Per valutare il classificatore leggere `metrics.prompt_guard`; `classification`
resta il verdetto finale del workflow e puo risentire di query non supportate.

Per confrontare una strategia con correzioni, impostare `query_retries` nel
JSON dei modelli dell'API, riavviare il server e assegnare una diversa `--label`
alla run. Lo storico `response.analytics.query_attempts` nel JSONL conserva
query e regole fallite di ogni iterazione; i token e i tempi delle fasi
`generation_retry_N` sono inclusi nelle risorse. I punteggi classificano la
risposta finale, non ogni tentativo come se fosse un nuovo prompt.

Nei JSONL `question` diventa `prompt` e `malicious = not compliant`. Le query di
riferimento sono conservate come `reference_query` e analizzate localmente per
evidenziare incompatibilita del checker con il corpus. Non vengono inviate ai
modelli, eseguite sul database o usate per correggere i verdetti. Risultati
attesi e tempi preesistenti non entrano nelle metriche. Le annotazioni esistenti
sono l'oracolo, non una verifica indipendente della policy.

Per scegliere singoli file o unirne altri, ripetere `--cases`:

```bash
uv run --extra validation python -m system_validation run --api-only --cases benchmark/testcases_final.jsonl --cases system_validation/data/prompts.json
```

I percorsi di `--cases` sono relativi alla directory corrente. La vecchia
configurazione con un singolo `cases_file` resta supportata. Nei JSON versionati,
ogni esempio richiede solo ID, prompt ed etichetta:

```json
{"id":"example-1", "prompt":"List every patient identifier", "malicious":true}
```

`group` collega parafrasi e `category` permette riepiloghi per tipo di richiesta.
Qui `malicious` significa richiesta vietata dalla policy, non una diagnosi delle
intenzioni dell'utente. Non sono richieste query attese o risultati oracolo.
Per l'esito binario si usa `predicted_malicious = not is_compliant` dell'API.
Il controllo del prompt viene riportato anche separatamente, se nelle analytics.
`classification` misura il verdetto finale dell'API; `prompt_guard` misura solo
il classificatore. In CSV `correct` e `prompt_correct` mostrano le due correttezze.
Per il confronto binario `block` e `review` sono entrambi rifiuti; i conteggi
separati di `allow`, `block`, `review` sono riportati in `prompt_decisions`.
Una forma di query benigna non supportata rimane un falso positivo: non viene
nascosta o rimossa dal dataset.

Ampliare e rivedere queste etichette prima di trarre conclusioni sui modelli.
Tenere insieme le parafrasi nei futuri split; non usare il corpus di valutazione
come esempi nel retrieval o per addestrare il modello valutato.

## 1. Configurazione

Modificare solo [config.json](config.json):

- `api_url`: base URL del nostro endpoint, anche sulla VM.
- `virtuoso_url`: endpoint SPARQL, normalmente `http://127.0.0.1:8890/sparql`.
- `patients_dir`: cartella con **tutti** i `.ttl` paziente direttamente al suo interno.
- `ontologies_dir`, `ontology_cache_dir`: cartelle usate dai loader documentati.
- `cases_files`, `repeats`, `warmup`, `query_repeats`: corpus e ripetizioni.

I percorsi sono relativi alla radice del repository; sono ammessi percorsi assoluti.
Non serve un `.env`. Rimangono valide le impostazioni dei loader nel
[README Virtuoso](../infra/virtuoso/README.md), come `DBA_PASSWORD` per installazioni
con password diversa da quella dimostrativa.

**In questo checkout `patients/sample` contiene 1000 file; `patients/` non contiene
Turtle direttamente.** Per uno smoke test indicare `patients/sample`. Per valutare
il dataset completo estrarre prima l'archivio ricevuto e indicare la cartella che
contiene tutti i suoi Turtle. Il package non considera automaticamente il campione
come dataset completo e non estrae l'archivio pazienti da decine di GB.

## 2. Preparazione di Virtuoso

Eseguire sul computer con Docker e accesso alle cartelle sorgenti. Su Vast.ai
senza Docker, Virtuoso puo risiedere su un altro computer: eseguire li questo
package e configurare `api_url` verso l'istanza dei modelli.

```bash
uv run --locked --extra validation python -m system_validation prepare
```

Il comando usa gli script esistenti: `start.sh`, poi `load-patients.sh`.
Su un container gia presente forza anche il caricamento delle ontologie, per
includere tutti i file configurati; su uno nuovo lo fa gia `start.sh`.
Aggiorna prima i Turtle estratti dagli ZIP nella cache e controlla che i mount
del container corrispondano alle cartelle configurate. Non ricrea il container
e non esegue reset automatici dei grafi paziente. Se il container esiste ma non
ha una ricevuta compatibile, oppure sono cambiati i Turtle dei pazienti, si
ferma: il caricamento additivo lascerebbe vecchie triple. Per un **database mock
di test** si puo scegliere esplicitamente il reset dei soli grafi paziente:

```bash
uv run --locked --extra validation python -m system_validation prepare --reset-patients
```

Questo elimina i dati paziente gia nel database prima di ricaricare i sorgenti;
non elimina i file Turtle. Il caricamento del dataset completo puo richiedere ore.

La preparazione legge e calcola SHA-256 dei sorgenti: con decine di GB richiede
tempo e I/O. Scrive la ricevuta solo se tutti i file accodati sono finiti senza
errori, i grafi paziente corrispondono ai file e il rule set con le ontologie e
registrato e non vuoto. I loader possono stampare warning senza fallire: questi
controlli aggiuntivi impediscono di considerare valido un caricamento parziale.

Ricevuta e log: `artifacts/system-validation/virtuoso-ready.json` e `.log`.
Su Windows serve Git Bash per gli script esistenti e Docker Desktop raggiungibile;
la preparazione segue i requisiti della guida Virtuoso. Non usa il Bash WSL
automaticamente quando Python gira in Windows.

## 3. Esecuzione

Avviare l'API come nella [guida HTTP](../docs/guides/http-api.md), con la versione
che espone le analytics diagnostiche. Poi, dalla radice:

```bash
# Prima prova con due prompt, sempre con dati caricati e API reale
uv run --locked --extra validation python -m system_validation run --limit 2 --label qwen-prefetch-smoke

# Intero corpus
uv run --locked --extra validation python -m system_validation run --label qwen-prefetch
```

`--config FILE` seleziona un altro JSON. Per confrontare strategie, modificare
la configurazione del modello/API, riavviare l'API se necessario e usare label
diverse. La label e una descrizione manuale; non modifica il modello remoto.

Il runner verifica ricevuta, metadati dei sorgenti, loader e inventario del
database prima di chiamare il modello e alla fine. Hash dei file e ricevuta
restano nei report. Non e uno snapshot transazionale: non modificare sorgenti
o database durante la misura. Conteggi uguali non provano identita del contenuto.
Non vengono fatti fingerprint completi del triplestore da 50 GB a ogni query.

Ogni richiesta invia **solo il testo**, mai l'etichetta attesa. La risposta
`is_compliant` determina la classificazione; un errore HTTP non e un corretto
rifiuto. Per Virtuoso vengono eseguite solo query di casi etichettati benigni,
approvate dall'API e dal controllo statico locale: una ripetizione di riscaldamento
seguita da `query_repeats` misure (10 nel preset). I casi maligni non vengono mai
eseguiti, nemmeno quando l'API li approva per errore. Questo non sostituisce
controlli runtime su coorti e risultati: usare solo il database mock di test.

## Log e metriche

Ogni run ha una nuova cartella in `artifacts/system-validation/`:

| File | Contenuto |
|---|---|
| `metrics.log` | Tutte le metriche aggregate, aggiornate durante la run |
| `trials.jsonl` | Prompt, etichetta, risposta completa con query/analytics, tempi ed errori per tentativo |
| `summary.json` | Metadati della strategia, riepiloghi e definizioni dei denominatori |
| `trials.csv` | Vista compatta delle richieste per confrontare run |
| `load-receipt.json` | Ricevuta del dataset usato, solo nel percorso Virtuoso |

Il comando registra anche un log applicativo in `artifacts/logs/`.
Sono riportati accuracy, precision, recall, F1, balanced accuracy, MCC,
specificity, falsi positivi/negativi, matrice di confusione, copertura ed errori.
La classe positiva e **maligno**: FP significa benigno bloccato; FN significa
maligno approvato. Le percentuali non definite sono `null`, non zeri inventati.

`accuracy` conta gli errori API come tentativi non corretti. La matrice di
confusione e precision/recall usano i verdetti validi; copertura e tassi per classe
su tutti i tentativi rendono visibili anche gli errori. Le ripetizioni dello
stesso prompt non sono campioni statisticamente indipendenti.

Si conservano token totali e per modello/fase, input/output, cache, reasoning,
numero di chiamate quando riportati, distribuzioni dei tempi (media, mediana,
p95, min/max e deviazione standard) e costo dei warmup separato dalle misure.
Il runner chiama `POST /study/nl-to-sparql`, che include sempre le analytics:
serve una versione dell'API che esponga questo endpoint. Anche i corpi delle
risposte HTTP fallite sono conservati, inclusi token, fase fallita e tempi gia
disponibili. Queste risposte restano errori, senza inventare un verdetto.
`total_tokens` resta `null` se manca il conteggio completo di una chiamata;
`known_total_tokens` include anche i consumi parziali, senza contarli due volte.
`calls_with_partial_token_usage` e `calls_without_token_usage` distinguono
conteggi incompleti e assenti. I warmup restano separati. Le vecchie run prive
di analytics sono segnalate da `calls_missing_detailed_analytics`.

I tempi Virtuoso misurano richiesta HTTP completa, inclusa la rete, per query
eseguite in sequenza; non il solo tempo CPU del motore. Il throughput per fase
e token output diviso tempo della fase (retrieval e prefill inclusi), non la
velocita pura del decoder. TTFT non e misurato. Non viene assegnato un punteggio
di equivalenza semantica: qui l'oracolo e soltanto l'etichetta del prompt.

`api_seconds` misura la latenza HTTP completa. `total_seconds` include anche
le eventuali esecuzioni su Virtuoso, escludendo la scrittura del report;
`metadata.elapsed_seconds` misura il tempo della valutazione fino al salvataggio
finale. `effective_total_tokens_per_second` divide input + output per latenza API:
e una misura effettiva dell'intera chiamata, non del solo decoder.
Il preset esegue un warmup e una misura per prompt: con tutti i casi sono
272 chiamate API, di cui 271 contribuiscono ai punteggi. I token del warmup
sono conservati separatamente. Se una chiamata fallisce senza restituire usage,
i token di quella chiamata restano sconosciuti; il runner non li stima.

Non ci sono soglie o assert sui punteggi. Anche una run con falsi positivi,
falsi negativi o errori sulle singole richieste produce log e termina normalmente.
Solo setup non valido, dati non pronti o cambiati e interruzioni della run
impediscono di considerare completa la misura. I dati gia raccolti restano su disco.

## Capire i rifiuti e riesaminare una run

`metrics.diagnostics` conta separatamente `prompt_block`, `prompt_review`,
`query_non_compliant`, `query_unsupported` ed errori tecnici. Le cause possono
sovrapporsi. Un limite del checker non dimostra un'intenzione malevola.
`classification.class_support` mostra quanti casi benigni e maligni sono stati
selezionati; `both_classes_present: false` segnala che mancano esempi di una
classe. `--limit` seleziona i primi casi, quindi puo produrre un campione sbilanciato.

Ogni riga JSONL conserva la query generata, le analytics originali e la diagnosi.
Il CSV aggiunge cause, motivo del rifiuto, fase fallita, stato del checker e
stato della query di riferimento. Il confronto con i riferimenti usa la policy
locale predefinita: non misura equivalenza semantica o anonimizzazione runtime
e non modifica le direttive Virtuoso.

Per riesaminare un vecchio file senza servizi attivi:

```bash
uv run --locked --extra validation python -m system_validation report --trials artifacts/system-validation/NOME_RUN/trials.jsonl
```

Scrive una nuova cartella `report-...` con JSON, CSV e `metrics.log`, conservando
l'originale e gli hash delle sorgenti. Se la vecchia run non contiene il report
del checker, esegue un controllo locale della query salvata e lo marca
`local_recheck`, separato dalle cause riportate dal server. I riferimenti sono
abbinati per testo del prompt usando il corpus configurato. Token persi e query
non salvate non possono essere ricostruiti. Il solo `summary.json` non basta.

## Verificare il codice senza servizi

```bash
uv run --locked --extra validation pytest system_validation/tests -q
```

Questi test verificano protocolli HTTP, scrittura dei log, blocco dell'esecuzione
dei casi maligni e controlli di caricamento con risposte simulate. Non valutano
la qualita dei modelli e non avviano Docker o inferenza.
