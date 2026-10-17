# Esempi

Eseguire i comandi dalla radice del repository.

## Provare il workflow senza modelli

```bash
uv sync --locked --extra agents --extra mcp
uv run python -m examples.fake_workflow
```

La demo mostra rilascio, blocco e revisione usando classificatore e generatore
fittizi con analizzatore e runtime reali.
Le risposte sono predisposte: questa demo verifica il collegamento tra
componenti, non l'accuratezza di un modello.

Per i test automatici vedere [tests](../tests/README.md); per cambiare strategia
vedere i [modelli fittizi](../docs/guides/fake-models.md).
Il benchmark del corpus e nei [tools](../tools/README.md); la CLI applicativa
per i modelli reali e nella [guida ai modelli locali](../docs/guides/local-models.md).

## Altre demo

| Comando | Cosa mostra |
|---|---|
| `uv run python -m sparql_analyzer.demo` | Parser e algebra su un dataset locale |
| `uv run python -m examples.diagram_walkthrough` | Verifica degli esempi numerici nei diagrammi |
| `uv run python -m examples.runtime_demo` | Rilascio e soppressione sulla fixture sintetica; report in `artifacts/tests/runtime-demo.json` |

Le [query cliniche illustrative](queries/clinical-examples.md) includono scelte
progettuali non tutte supportate dal controllore corrente. Le query operative
Virtuoso sono in [infra/virtuoso/queries](../infra/virtuoso/queries).
