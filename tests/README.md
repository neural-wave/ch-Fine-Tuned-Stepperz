# Test dell'analizzatore SPARQL

Dalla radice del progetto:

```powershell
python -m pip install -r requirements-test.txt
python -m pytest -v
```

- `test_compliance.py`: 19 regressioni e 32 casi parametrizzati (51 test statici).
- `cases/`: query .rq separate, indice e cases.json con esiti attesi e motivi.
- `export_results.py`: genera alberi e verdetti, senza eseguire le query.
- `results/`: un risultato per caso e report.json riepilogativo, rigenerabili.

Per rigenerare i risultati: `python -m tests.export_results`.
Per un singolo caso: `python -m pytest -v -k identifier_alias`.
In VS Code usare il pannello Testing, che cerca nella cartella tests/.

Regole: R1 singolo paziente; R2 risultati non aggregati; R3 scansione libera;
R4 query diversa da SELECT; R5 identificatori in uscita. Una query puo violare
piu regole. I casi non supportati sono bloccati senza essere approvati.

[Indice delle query](cases/README.md) e [policy e limiti](../docs/sparql.md).

## Pazienti sintetici e runtime

```powershell
python -m tests.generate_synthetic_data --patients 12 --seed 42
python -m tests.demo_runtime
```

- test_runtime.py: 29 test di coorte, risultato, soppressione e tipi inattesi.
- data/synthetic/cohort.trig: fixture generata localmente e riproducibile.
- results/runtime-demo.json: scenari consentiti e bloccati.

La suite completa comprende 80 test. Il runtime locale non e collegato a Virtuoso.
