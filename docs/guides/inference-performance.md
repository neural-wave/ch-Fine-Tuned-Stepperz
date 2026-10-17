# Misurare e ridurre la latenza

La configurazione fornita in `config/agents/models.json` usa `generation_mode: prefetch`:
il codice chiede esempi e classi al MCP di `LLM_ENGINE`, poi passa il contesto al
generatore. Qwen non spende turni per scegliere questi due strumenti. Il modello
puo ancora fare retry per correggere l'output strutturato: una sola chiamata non
e garantita. Laya, analizzatore statico e controlli runtime restano attivi.

Impostare `generation_mode: agentic` per lasciare al modello la scelta degli
strumenti e delle classi, come prima. Configurazioni senza il campo mantengono
`agentic`. Con MCP disabilitato viene usato direttamente lo schema fornito.
Il vecchio MCP stdio richiede `agentic`; `prefetch` usa i due strumenti SPHN HTTP.

`retrieval_classes` e una lista facoltativa di massimo sei nomi/IRI di classi,
ad esempio `["BilledDiagnosis", "SubjectPseudoIdentifier", "AdministrativeSex"]`
per una specifica richiesta. Senza suggerimenti vengono usati le classi degli
esempi recuperati e il testo della richiesta. Il recupero lessicale e limitato:
non garantisce tutti i join o i codici clinici necessari. Non lasciare suggerimenti
specifici di una domanda in una configurazione destinata a domande diverse.
Un errore MCP interrompe la generazione; non viene nascosto con un fallback.
Le domande generiche sui pazienti usano gli alias italiani/inglesi verso
`SubjectPseudoIdentifier` nel retrieval MCP. Se una domanda come "How many
patients are in the database?" restituisce esempi e classi vuoti, verificare
di avere aggiornato e riavviato il processo MCP, oltre all'API.
I suggerimenti esatti selezionano solo la classe richiesta. Il prefetch elimina
la copia ShEx quando il MCP fornisce gia gli stessi range in JSON, mantenendo
le note sullo schema: meno testo duplicato da elaborare.

## Avvio vLLM sulla VM

```bash
bash LLM_ENGINE/start_remote.sh
```

Per i nuovi processi lo script abilita prefix caching e lascia disponibili CUDA
graphs e compilazione, rimuovendo il precedente `--enforce-eager`. La cache aiuta
quando il prefisso e condiviso; non accelera la generazione dei token di risposta.
I campi stabili della richiesta precedono ora il prompt per facilitare il riuso.
Riferimenti: [vLLM engine arguments](https://docs.vllm.ai/en/stable/configuration/engine_args/),
[prefix caching](https://docs.vllm.ai/en/stable/features/automatic_prefix_caching/).

Se la GPU/versione non supporta questa combinazione o esaurisce VRAM, prima del
nuovo avvio usare `VLLM_ENFORCE_EAGER=1 bash LLM_ENGINE/start_remote.sh`.
`VLLM_PREFIX_CACHING=0` disabilita esplicitamente la cache per un confronto.
Nessun pacchetto GPU viene aggiornato. Il comando effettivo dei nuovi avvii e
salvato in `/workspace/logs/qwen30b-command.txt`.

Un server gia attivo viene riusato con i suoi vecchi parametri. Per cambiarli,
fermare esplicitamente il servizio che lo gestisce: se e quello creato dallo
script, `tmux kill-session -t '=sphn-qwen'`, poi rilanciare lo script. Questo
interrompe le richieste attive. Se lo gestisce Supervisor, intervenire sul suo
servizio: non avviare una seconda copia. Per i nuovi metadati `class_iri` riavviare
anche il MCP gestito dallo script: `tmux kill-session -t '=sphn-mcp'` e riavviare.
Il client prefetch supporta anche i vecchi risultati senza `class_iri`.

## Confronto ripetibile

Dalla radice, solo sulla VM con i modelli pronti:

```bash
uv run --extra local python -m tools.benchmark_inference \
  --config config/agents/models.json \
  --policy-file config/agents/policy.txt \
  --permissions-file config/agents/permissions.txt \
  --prompt 'Count distinct patients with BilledDiagnosis in their patient graph' \
  --warmup 1 --repeats 3 --label cuda-prefix \
  --out artifacts/benchmarks/cuda-prefix.json
```

Il benchmark usa il JSON condiviso `config/agents/models.json`, come API,
debugger e script remoto. Carica Laya
una volta e confronta `agentic` e `prefetch`, riaprendo il generatore per ogni
modalita. Salva warmup, ogni query, stati di rifiuto/errore, tempi per fase e token
(incluse richieste e cache quando riportate dal backend). Warmup e caricamento
sono separati dalla mediana; la mediana delle sole query accettate e distinta da
quella di tutte le richieste. Un blocco veloce non conta come query accettata.

La modalita predefinita e `generation_mode` nel JSON condiviso.
Il benchmark sovrascrive questa scelta per ciascun confronto.

Per confrontare i parametri vLLM, ripetere con server avviati separatamente e
`--label`/`--out` diversi, conservando GPU, modello, richieste e carico uguali.
Ripetere anche con `--modes prefetch agentic` per rilevare effetti dell'ordine e
della cache. Il report non verifica i parametri del server e non misura TTFT o
token/secondo del solo motore: la latenza include classificazione e controlli.

Il benchmark non esegue le query e non certifica equivalenza semantica:
`query_ready` significa superamento dei gate statici. Prima di adottare la modalita
piu veloce confrontare anche gli oracoli sulle fixture con
`uv run --extra local python -m tools.evaluate_workflow --models-config ...`.
Vedere [tools](../../tools/README.md) e [workflow](agent-workflow.md).
