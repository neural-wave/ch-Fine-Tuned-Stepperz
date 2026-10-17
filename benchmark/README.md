# Prompt di benchmark

Questi JSONL contengono domande con etichetta `compliant` e query di riferimento.
`testcases.jsonl` e `testcases_checked.jsonl` hanno 82 casi ciascuno;
`testcases_final.jsonl` ne ha 70. Sono versioni sovrapposte del corpus,
non tre dataset indipendenti.

Per valutare il sistema su tutti i prompt, compresi quelli di `system_validation`:

```bash
uv run --locked --extra validation python -m system_validation run --api-only --label baseline
```

Servono API e modelli gia attivi; nessuna inferenza viene avviata dal benchmark.
L'indirizzo API si configura in `system_validation/config.json`.
Il runner deduplica i prompt, conserva provenienza ed etichette e confronta
`not is_compliant` con `not compliant`. Non invia al sistema etichette, query
di riferimento o risultati attesi.

Ogni avvio salva token per modello/fase, tempi, giudizi corretti ed errati,
matrice di confusione, accuracy, precision, recall, F1, specificita e MCC.
Gli errori API restano visibili e non sono conteggiati come verdetti corretti;
le metriche non impongono soglie o assert sulle prestazioni dei modelli.

Per valutare solo la versione finale:

```bash
uv run --extra validation python -m system_validation run --api-only --cases benchmark/testcases_final.jsonl
```

Vedere [system_validation](../system_validation/README.md) per report, metriche,
ripetizioni e percorso con preparazione ed esecuzione su Virtuoso.
I risultati di riferimento presenti nei JSONL provengono da un dataset precedente:
non dimostrano che il database attuale contenga gli stessi dati.
