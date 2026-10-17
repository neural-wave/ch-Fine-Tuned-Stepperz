# Workflow e modelli

Ingresso applicativo: `uv run --extra local sparql-run --help`.
Per i percorsi pronti all'uso vedere la [guida dei comandi](../../docs/guides/commands.md).

Il flusso è: **validazione del prompt → generazione SPARQL → analisi statica →
esecuzione controllata**. `SparqlWorkflow` si ferma al primo blocco o errore.
Con `run(request, execute=False)` prepara soltanto la query e restituisce
`query_ready`; l'executor serve per l'esecuzione, abilitata per default.
La valutazione semantica confronta i risultati con gli oracoli nei test offline.

## Scegliere i modelli

- **Reali:** modificare [models.json](../../config/agents/models.json) e usare
  `open_models()` da `local_models.py`. Restituisce validatore Laya e generatore
  PydanticAI con strumenti MCP. Istruzioni nella [guida ai modelli locali](../../docs/guides/local-models.md).
- **Fittizi:** assegnare `FakeClassifier` e `FakeSparqlLLM` nel codice, anche
  combinandoli con modelli reali. Strategie ed esempi nella [guida](../../docs/guides/fake-models.md).

La demo pronta per partire senza pesi o server è:

```bash
uv run python -m examples.fake_workflow
```

Il [workflow completo](../../docs/guides/agent-workflow.md) spiega come assemblare
i componenti. [Config](../../config/README.md) raccoglie i file da modificare;
[tests](../../tests/README.md) contiene i comandi per verificarli offline.

## Dove intervenire

| File | Responsabilità |
|---|---|
| `cli.py` | Comando applicativo `sparql-run`, anche tramite `python -m agent_orchestration` |
| `__main__.py` | Avvio del medesimo comando tramite `python -m agent_orchestration` |
| `models.py` | Contratti asincroni `LLM`, `SparqlLLM`, `SystemOneModel` e tipi di richiesta/risposta |
| `adapters.py` | Collegamento a PydanticAI o a una funzione di classificazione personalizzata |
| `local_models.py` | Endpoint chat, Laya e connessione MCP |
| `fakes.py` | Modelli fittizi e strategie di risposta |
| `validation.py` | Validatori del prompt e adattatore dell'analizzatore statico |
| `workflow.py` | Sequenza dei controlli ed executor RDF locale |
| `semantic.py` | Confronto dei risultati di esecuzione |
| `evaluation.py` | Valutazione separata del sistema e della generazione |

La CLI e `sparql-run`: con `--dataset` esegue anche
il runtime locale. Il benchmark e `python -m tools.evaluate_workflow`.
I test agentici sono raggruppati in `tests/agents/`.

Il preset MCP riusa via HTTP il server SPHN di `LLM_ENGINE`, avviabile con
`bash start-mcp.sh`. `sparql-run --check-mcp` verifica i tool senza modelli.
I client dei due progetti mantengono ambienti separati; solo il recupero
di schemi/esempi viene condiviso, non l'esecuzione delle query.

`PromptRequest` e un alias di `SparqlRequest`: guard e generatore condividono
prompt, schema, policy e permessi. Tutti i modelli espongono `await run(request)`.
Il generatore restituisce
`SparqlResult`, il classificatore `Decision`; questi tipi da soli non certificano
la sicurezza. `Decision.probability` è facoltativa e va fornita solo quando il
backend espone una probabilità significativa. Gli executor applicano i controlli
deterministici; non richiedono un modello.
