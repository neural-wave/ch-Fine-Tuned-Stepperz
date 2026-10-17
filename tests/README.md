# Test

Questa suite verifica il progetto principale. Per scegliere tra esecuzione di
un prompt, demo, benchmark e test vedere la [guida dei comandi](../docs/guides/commands.md).
Il sottoprogetto [LLM_ENGINE](../LLM_ENGINE/README.md) ha una propria suite e
un proprio ambiente, non inclusi dal `testpaths` del progetto principale.

`tests/agents/test_shared_mcp.py` verifica anche il vero server SPHN di quel
progetto, avviato temporaneamente su loopback. Per abilitarlo preparare prima
l'ambiente con `uv sync --locked --project LLM_ENGINE --python 3.12`;
altrimenti quel test viene saltato. L'inferenza e sostituita, i dati sintetici.

Tutti i comandi partono dalla radice del repository. Le suite offline usano dati
RDF sintetici e risposte controllate, senza scaricare pesi o contattare servizi
di inferenza. I test `model_health` richiedono invece un consenso esplicito da CLI.

## Health check dei modelli reali (solo sulla macchina adatta)

Sulla VM Linux, per preparare dipendenze, avviare i servizi e lanciare tutte le
suite e gli health check con un comando:

```bash
bash start-and-test.sh
```

Richiama direttamente [LLM_ENGINE/start_remote.sh](../LLM_ENGINE/start_remote.sh),
che avvia o riusa vLLM/Qwen e MCP SPHN e ne verifica il funzionamento.
Non installa o avvia Ollama. Richiede `uv` e i prerequisiti dello script remoto:
`tmux`, `curl`, `ss` e vLLM nell'ambiente GPU; dettagli nella
[guida remota](../LLM_ENGINE/README_REMOTE.md).

Gli health check usano modello e indirizzi letti dalla configurazione remota
di `LLM_ENGINE`, con le impostazioni Laya di `config/agents/models.json`.
La configurazione risultante viene scritta in `artifacts/tests/models.remote.json`,
senza modificare il preset principale. Laya viene caricato (e scaricato se non
in cache) dal suo health check. Errori di setup interrompono l'esecuzione.

I servizi restano attivi anche dopo i test. Log dello stack in `/workspace/logs/`;
report in `artifacts/tests/`. Non esegue i test live di `LLM_ENGINE` verso servizi
esterni. Per riusare la stessa configurazione da Test Explorer aggiungere
`--run-model-health` e `--model-config=artifacts/tests/models.remote.json` ai
`python.testing.pytestArgs`.

I test in [health/test_models.py](health/test_models.py) sono saltati per default,
anche selezionandoli in Test Explorer. Solo `--run-model-health` abilita caricamento
e inferenza reali. Leggono `config/agents/models.json`; per cambiarlo usare
`--model-config percorso/models.json`.

Preparare le dipendenze con `uv sync --locked --extra local`. Per il generatore
devono essere attivi il server di inferenza con il modello configurato e l'MCP
se abilitato nella configurazione (vedere [modelli locali](../docs/guides/local-models.md)).

```bash
# Classificatore: carica Laya e verifica una risposta; non apre generatore o MCP.
uv run --extra local pytest tests/health/test_models.py::test_classifier_health --run-model-health -v
# Generatore: usa endpoint e MCP configurati; non carica Laya.
uv run --extra local pytest tests/health/test_models.py::test_generator_health --run-model-health -v
# Entrambi, con tempi e decisione nel report XML.
uv run --extra local pytest tests/health --run-model-health -v --junitxml=artifacts/tests/model-health.xml
```

Il classificatore deve produrre una decisione valida (`allow`, `block`, `review`)
e un'eventuale probabilita tra 0 e 1. Il generatore deve restituire una query
strutturata, non vuota e analizzabile come `SELECT`; la query non viene eseguita.
Errori di dipendenze, caricamento, connessione e inferenza fanno fallire i test.
Il tempo comprende caricamento, connessioni e inferenza, non e un benchmark.
Questi controlli verificano il funzionamento delle integrazioni: non misurano
l'accuratezza del classificatore o la correttezza semantica della query.

### Verifica sulla VM: 17 ottobre 2026

L'utente ha confermato il passaggio di entrambi gli health check
(`test_generator_health` e `test_classifier_health`) sulla VM Linux
con `--run-model-health --model-config artifacts/tests/models.remote.json`.
Il precedente tentativo falliva nella connessione HTTP al modello; il test e
passato usando la configurazione remota. Esito riferito dall'utente, senza
report XML o query prodotta acquisiti in questo checkout.

Il passaggio conferma il contratto di risposta del classificatore e una risposta
strutturata del generatore, con query non vuota e parsing come `SELECT`.
Non verifica accuratezza delle decisioni, esecuzione, risultati, correttezza
semantica, sicurezza o chiamate effettive ai tool di retrieval. Questo esito
non riguarda l'intera suite.

## Esecuzione

Ogni sessione pytest del progetto principale salva automaticamente i log in
`artifacts/logs/pytest-<data UTC>-<PID>.log`, anche da Test Explorer. Il percorso
appare nell'intestazione di pytest. I file contengono eventi del workflow e
dei modelli, messaggi delle librerie Python, esiti dei test e traceback degli
errori. Non serve un wrapper. Si aggiungono ai report XML; `SPARQL_LOG_DIR` e
`SPARQL_LOG_LEVEL` cambiano destinazione e livello. Dettagli nella
[guida dei comandi](../docs/guides/commands.md).

Comando locale unico per entrambi i progetti, senza GitHub Actions:

```bash
bash test.sh
```

Richiede `uv` e Bash (Git Bash su Windows). Prepara `LLM_ENGINE/.venv`, poi
esegue le due suite nelle rispettive directory, con Python 3.12 e i lock
esistenti (`--locked`). Include il vero MCP temporaneo con inferenza simulata;
esclude health check reali e test live di `LLM_ENGINE`. Il primo setup puo
scaricare Python e dipendenze, ma non pesi dei modelli.

I report XML sono `artifacts/tests/main.xml` e `artifacts/tests/llm-engine.xml`.
Un errore restituisce un codice diverso da zero. Sulla VM, con i servizi
configurati gia attivi, `bash test.sh --with-models` aggiunge gli health check
reali e `model-health.xml`. Lo script non avvia i servizi permanenti e aggiorna
solo i report delle suite effettivamente eseguite.

La variabile `MODEL_CONFIG` puo indicare un altro JSON per gli health check:
`start-and-test.sh` la imposta automaticamente sul preset remoto generato.

Per la suite completa, incluse le integrazioni PydanticAI e MCP:

```bash
uv sync --locked --extra agents --extra mcp
uv run --extra agents --extra mcp pytest -q
```

Per lavorare soltanto sul workflow offline prima del deployment:

```bash
uv run --extra agents --extra mcp pytest -m offline_workflow -q --junitxml=artifacts/tests/offline-workflow.xml
```

Il marker comprende contratti dei modelli, strategie fittizie, combinazioni tra
classificazione e generazione, arresto dopo un blocco, propagazione del contesto,
output invalidi e retry, errori, timeout, cancellazione, riuso e concorrenza.
Verifica anche gli oracoli sulle fixture e il collegamento HTTP/MCP con risposte
controllate. Il client HTTP usa un trasporto simulato; il server MCP è un processo
stdio minimale locale, non il server upstream. Laya è sostituito nei test.

Senza gli extra si possono eseguire i controlli deterministici e i modelli fittizi:

```bash
uv sync --locked
uv run pytest -q
uv run pytest tests/agents/test_offline_workflow_interactions.py -q
```

I moduli che richiedono PydanticAI o MCP vengono saltati quando la dipendenza
manca: controllare il riepilogo degli skip prima di dichiarare completa una prova.
Per filtrare un caso: `uv run pytest -k identifier_alias -v`.

## Dove trovare i test

| Percorso | Copertura |
|---|---|
| [`analysis/`](analysis/) | Parsing, regole statiche, operatori e sottoquery |
| [`runtime/`](runtime/) | Coorti, risultati, soppressione e aggregazioni numeriche |
| [`configuration/`](configuration/) | Profili, toggle e prerequisiti delle policy |
| [`privacy/`](privacy/) | Attacchi, risposte alterate e regressioni hardened |
| [`adequacy/`](adequacy/) | SHACL Core/SPARQL e interazione con privacy |
| [`agents/`](agents/) | Contratti, modelli fittizi e integrazioni del workflow |
| [`health/`](health/) | Health check dei modelli reali, abilitati solo con `--run-model-health` |
| [`test_system_dataset.py`](test_system_dataset.py) | Dataset sintetico iniziale di sistema |
| [`fixtures/`](fixtures/) | Query, associazioni prompt-query e dati versionati |
| [`support/`](support/) | Costruttori di fixture e server MCP di test |

[`paths.py`](paths.py) centralizza i percorsi. Gli output rigenerabili vanno
in `artifacts/`, non accanto alle fixture.

## Valutare prompt, generazione e sistema

```bash
uv run --extra agents python -m tools.evaluate_workflow --offline
```

Il report è `artifacts/workflow-evaluation/report.json`. `TestModel` riceve
etichette e query già note: il report verifica collegamenti e oracoli, non
l'accuratezza di un modello. L'uguaglianza dei risultati sulle fixture non prova
equivalenza semantica universale.

La [guida al workflow](../docs/guides/agent-workflow.md) descrive associazioni,
split e confronto dei risultati. Per cambiare modelli usare le guide ai
[modelli fittizi](../docs/guides/fake-models.md) e
[modelli locali](../docs/guides/local-models.md). Il
[dataset di sistema iniziale](../docs/system-dataset.md) resta uno smoke test
separato dal corpus principale.

## Leggere i test di sicurezza

La suite usa configurazioni diverse: un risultato verde non significa che tutti
i casi siano stati eseguiti con il profilo hardened.

| Gruppo | Profilo e significato |
|---|---|
| Controlli deterministici e osservazioni avversarie | Predefinito, salvo override nel test |
| Marker `security_gap` | Verifica il blocco degli scenari generali e delle varianti complesse con hardened, contesto fidato e SHACL disattivato sulle fixture privacy minimali |
| Regressioni complesse e controlli positivi privacy | Disattivano anche `privacy_normalize_errors`, così un crash imprevisto non vale come blocco riuscito |
| Marker `risk_demonstration` | Riproduce un rischio sul profilo predefinito: il test passa quando osserva quel rischio |
| Suite adequacy | Usa configurazioni e contesti SHACL espliciti; non presume che le fixture privacy rispettino tutte le shape SPHN |

```bash
uv run pytest tests/privacy -m security_gap -v
uv run pytest tests/privacy/test_privacy_policies.py -q
uv run pytest tests/adequacy -q
```

Le regressioni `security_gap` sono test ordinari, non `xfail`. Il loro blocco
non dimostra la copertura di ogni attacco o l'accettazione di ogni query lecita;
alcune regole sono conservative. Dettagli e limiti nelle guide a
[privacy](../docs/policies/privacy.md) e [SHACL](../docs/policies/adequacy-shacl.md).

I test offline non verificano l'accuratezza dei modelli reali, la GPU, Virtuoso,
ACL e isolamento del deployment, né garantiscono anonimato sui dati reali.

## Corpus e report

- [Query di compliance](fixtures/cases/README.md): query `.rq` con aspettative statiche.
- [Corpus avversario](fixtures/adversarial/README.md): attacchi singoli, sequenze e risposte alterate.
- [Sonde complesse](fixtures/adversarial_complex/README.md): osservazioni sul profilo predefinito e regressioni hardened.

Per rigenerare alberi, verdetti e osservazioni dei corpus:

```bash
uv run python -m tools.export_test_results
```

Output in `artifacts/tests/`; gli export descrivono il profilo usato dal relativo
tool e non sostituiscono le regressioni hardened di pytest.

Per rigenerare la fixture RDF sintetica e provare il runtime locale:

```bash
uv run python -m tools.generate_synthetic_data --patients 12 --seed 42
uv run python -m examples.runtime_demo
```

La fixture è `tests/fixtures/synthetic/cohort.trig`; il report è
`artifacts/tests/runtime-demo.json`.
