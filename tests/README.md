# Test dell'analizzatore SPARQL

Dalla radice del progetto:

```powershell
uv sync --locked
uv run pytest -v
```

- `test_compliance.py`: 19 regressioni e 32 casi parametrizzati (51 test statici).
- `cases/`: query .rq separate, indice e cases.json con esiti attesi e motivi.
- `export_results.py`: genera alberi e verdetti, senza eseguire le query.
- `results/`: un risultato per caso e report.json riepilogativo, rigenerabili.

Per rigenerare i risultati: `uv run python -m tests.export_results`.
Per un singolo caso: `uv run pytest -v -k identifier_alias`.
In VS Code usare il pannello Testing, che cerca nella cartella tests/.

Regole: R1 singolo paziente; R2 risultati non aggregati; R3 scansione libera;
R4 query diversa da SELECT; R5 identificatori in uscita. Una query puo violare
piu regole. I casi non supportati sono bloccati senza essere approvati.

[Indice delle query](cases/README.md) e [policy e limiti](../docs/sparql.md).

## Pazienti sintetici e runtime

```powershell
uv run python -m tests.generate_synthetic_data --patients 12 --seed 42
uv run python -m tests.demo_runtime
```

- test_runtime.py: 29 test di coorte, risultato, soppressione e tipi inattesi.
- data/synthetic/cohort.trig: fixture generata localmente e riproducibile.
- results/runtime-demo.json: scenari consentiti e bloccati.

La suite originaria comprende 80 test. Il runtime locale non e collegato a Virtuoso.

## Casi avversari avanzati

Vedi [corpus, matrice e lacune](adversarial/README.md): 45 casi singoli con query
separate, 12 test di risposte alterate e 10 scenari con 6 lacune riprodotte come
xfail strict e 4 dimostrazioni di rischio. Con i divieti espliciti e le statistiche numeriche, la suite precedente comprende 241 test:
235 passano e 6 sono fallimenti attesi, non protezioni riuscite.

```powershell
uv run pytest -v
uv run python -m tests.export_results
uv run pytest -m security_gap --runxfail -v
```

L'ultimo comando rende visibili i sei fallimenti di sicurezza ancora aperti.

La policy v2 ha test dedicati in `test_forbidden_operators.py`: divieti espliciti,
operatori annidati, parole innocue nel testo e conservazione di UNION/OPTIONAL.

## Statistiche numeriche v3

`test_numeric_operations.py` aggiunge 55 test su SUM/AVG, DISTINCT, aritmetica,
arrotondamenti, IF/COALESCE numerici, filtri, dati non numerici, coorti piccole,
aggregati nascosti in HAVING e risposte alterate. Esempi separati in
`numeric/queries/`. Il corpus avversario r04 e ora bloccato prima dell'esecuzione;
r05 e diventato un controllo positivo dell'aritmetica su conteggi.

## Query complesse che aggirano il controllo

Vedi [sonde complesse e bypass riprodotti](adversarial_complex/README.md).
La nuova suite aggiunge 25 query separate e 36 test: 25 osservazioni, di cui 11
riproducono esposizioni, e 11 requisiti di blocco ancora falliti (xfail strict).
Sono varianti di alcune famiglie di lacune, non 11 vulnerabilita indipendenti.

Suite complessiva: 277 test, 260 passati e 17 fallimenti attesi. I test marcati
risk_demonstration non sono prove di protezione. Il controllore non e stato
modificato per questa aggiunta: si sta misurando il suo comportamento attuale.

```powershell
uv run pytest tests/test_complex_attacks.py -v
uv run python -m tests.complex_attacks
```
