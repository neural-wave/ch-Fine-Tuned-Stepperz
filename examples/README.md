# Demo

Questa cartella contiene esempi dimostrativi. Il comando applicativo e
`uv run --extra local sparql-run`; il benchmark e nei [tools](../tools/README.md).
Per scegliere il percorso vedere la [guida dei comandi](../docs/guides/commands.md).

Tutti i comandi partono dalla radice del repository:

| Comando | Cosa esegue | Cosa osservare |
|---|---|---|
| `uv run python -m examples.fake_workflow` | Workflow con classificatore e generatore fittizi, analizzatore e runtime reali | Rilascio, blocco del prompt e revisione su dati sintetici |
| `uv run python -m examples.runtime_demo` | Query predisposte sul runtime, senza modelli | Rilascio/soppressione e report `artifacts/tests/runtime-demo.json` |
| `uv run python -m sparql_analyzer.demo` | Parser, algebra e piccolo conteggio di verifica | Alberi RDFLib e conteggio atteso |
| `uv run python -m examples.diagram_walkthrough` | Scenari numerici dei diagrammi | Verifica degli esempi di privacy |

`runtime_demo` legge la fixture gia presente in
`tests/fixtures/synthetic/cohort.trig`. `fake_workflow` crea i suoi dati in memoria.
Nessuna di queste demo richiede pesi, Ollama o un database remoto.

Per cambiare le risposte della prima demo vedere i
[modelli fittizi](../docs/guides/fake-models.md); per le verifiche automatiche
vedere [tests](../tests/README.md). Le risposte predisposte dimostrano i
collegamenti tra componenti, non la capacita di un modello.

Le [query cliniche illustrative](queries/clinical-examples.md) includono scelte
progettuali non tutte supportate. Le query operative Virtuoso sono in
[infra/virtuoso/queries](../infra/virtuoso/queries).
