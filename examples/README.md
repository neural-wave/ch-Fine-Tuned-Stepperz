# Esempi

```powershell
uv run python -m sparql_analyzer.demo
uv run python -m examples.diagram_walkthrough
uv run python -m examples.runtime_demo
```

La prima demo mostra parser e algebra su un Dataset locale. La seconda
verifica gli esempi numerici dei diagrammi. La terza esegue scenari di rilascio
e soppressione sulla fixture `tests/fixtures/synthetic/cohort.trig` e scrive
`artifacts/tests/runtime-demo.json`.

Le [query cliniche illustrative](queries/clinical-examples.md) sono esempi
progettuali, non una lista di query tutte supportate dal controllore corrente.
Le query operative Virtuoso sono in [infra/virtuoso/queries/](../infra/virtuoso/queries).
