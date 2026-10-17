# Analizzatore SPARQL e controllo dei risultati

La policy corrente e `numeric-aggregates-v5-nested`. Parser e algebra sono in
sparql_analyzer/parser.py, i controlli statici in compliance.py e il runtime
locale in runtime.py. Il sistema non usa LLM per decidere la compliance.

[Teoria e SHACL](non-compliance-e-shacl.md), [attacchi](attacchi-all%27anonimato.md)
e [operazioni disponibili](operazioni.md) approfondiscono ambito e limiti.

## Comandi

Dalla radice del progetto:

```powershell
uv sync --locked
uv run pytest -v
uv run python -m sparql_analyzer.compliance tests/numeric/queries/average.rq
uv run python -m sparql_analyzer.demo
uv run python -m sparql_analyzer.demo --query queries/classes.rq --out tests/results/manual
uv run python -m tests.generate_synthetic_data --patients 12 --seed 42
uv run python -m tests.demo_runtime
uv run python -m tests.export_results
```

Il CLI di compliance termina con codice 0 solo per query approvate staticamente,
1 per query bloccate. Una query approvata staticamente richiede comunque il
controllo runtime prima di restituire dati. Il demo con --query produce gli
alberi ma non esegue il file; senza --query verifica un conteggio in memoria.
Gli alberi sono quelli RDFLib, non i piani di esecuzione Virtuoso.

## Risultati statici

`validate(query_text)` restituisce is_compliant, status, violations, findings,
forbidden_operators e policy. status distingue compliant, non_compliant e
unsupported. FORBIDDEN_OPERATOR indica un divieto esplicito; UNSUPPORTED una
struttura non verificata, comunque bloccata. R1-R5 sono le regole del progetto:
singolo paziente, output non aggregato, scansione libera, forme non SELECT e
identificatori in uscita. La policy segue Query_Compliance.md anche dove
API_specification.md ammette forme read-only piu ampie.

La propagazione delle variabili sensibili segue gli alias e le aggregazioni.
COUNT puo contare identificatori senza esporli, ma un'espressione dentro COUNT
che dipende da identificatori o risorse individuali viene bloccata.
SUM/AVG richiedono variabili di misura provenienti dai predicati numerici
approvati, inizialmente sphn:hasValue, o da aritmetica verificata su tali variabili.
Non e sufficiente avere un datatype numerico: un ID numerico resta un ID.

I grafi costanti non autorizzati, i soggetti fissi e i filtri sugli identificatori
vengono bloccati conservativamente. Il filtro sul namespace completo dei grafi
paziente resta consentito. Pattern interamente variabili vengono rifiutati anche
se un altro pattern potrebbe limitarli. I falsi positivi sono intenzionali.

## Divieti espliciti

Restano vietati GROUP_CONCAT, SAMPLE, MIN, MAX, SERVICE, FROM, FROM NAMED,
ASK, CONSTRUCT, DESCRIBE e tutte le operazioni SPARQL Update. Questi divieti
sono una scelta conservativa di policy; non significano che ogni uso teorico
di MIN o MAX riveli necessariamente dati individuali.

Il controllo usa l'AST originale: funziona con operatori annidati, HAVING e
ORDER BY, senza vietare parole presenti solo in commenti, stringhe, URI, prefissi
o variabili. Un SAMPLE introdotto internamente dal traduttore per GROUP BY
non viene confuso con SAMPLE scritto dall'utente.

## Runtime locale

```python
from sparql_analyzer.runtime import execute_checked, ResultBlocked

try:
    response = execute_checked(dataset, query_text, min_patients=5)
except ResultBlocked:
    response = None  # Non restituire il risultato grezzo.
```

Sono supportati COUNT/SUM/AVG globali, DISTINCT sui valori, aritmetica e
funzioni numeriche verificate sulle statistiche. Il runtime considera il
pattern WHERE prima dell'aggregazione, ricalcola gli aggregati, segue le
espressioni finali e confronta i valori con la risposta del backend.
Verifica colonne, singola riga, datatype numerici e valori finiti. I conteggi
mantengono il contratto di interi non negativi; somme e medie possono essere
negative o decimali. Errori numerici e risposte inattese bloccano il rilascio.

Per ogni aggregato viene verificata una coorte distinta; i valori non legati
non contribuiscono. Anche un aggregato usato solo in HAVING/ORDER BY richiede
la soglia: puo influenzare la risposta. Una colonna OPTIONAL con contributi di
un solo paziente blocca tutta la risposta. check_payload da solo controlla la
forma e non autorizza il risultato.

La soglia predefinita 5 e dimostrativa. Il runtime conta grafi distinti assumendo
un grafo per paziente: questa corrispondenza deve essere garantita dal dataset.
Il limite di verifica e 100000 righe di supporto; non sostituisce un timeout.
SUM/AVG sui valori degli eventi danno piu peso ai pazienti con piu eventi;
non sono automaticamente medie delle medie individuali. Non vengono convertite
unita di misura, che devono essere selezionate coerentemente dalla query.

## Ambito e limitazioni

UNION, OPTIONAL, MINUS, BIND verificati e filtri deterministici supportati restano
disponibili. Un'operazione ammessa non autorizza automaticamente i suoi argomenti.
GROUP BY per categorie nell'output esterno, VALUES, property path e funzioni non verificate
restano bloccati. DEFINE e OPTION(inference) di Virtuoso non vengono riscritti:
il dialetto non e supportato. Non vengono abilitate funzioni arbitrarie per URI,
rete, numeri casuali o funzioni non deterministiche.

### Sottoquery

Le sottoquery SELECT di selezione sono ammesse, anche annidate, con DISTINCT,
alias, filtri, ordinamento e limiti. Possono produrre valori individuali interni:
solo l'output esterno deve rispettare il contratto di aggregazione. Il parser
rinomina le variabili locali nell'algebra, preservando quelle esportate dalla
proiezione, senza modificare la semantica della query. Un identificatore esportato
rimane sensibile; una variabile privata omonima non cambia la classificazione
delle variabili esterne.

Esempio eseguibile sul dataset sintetico:

```sparql
PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>
SELECT (COUNT(DISTINCT ?g) AS ?patients)
WHERE {
  { SELECT DISTINCT ?g WHERE {
      GRAPH ?g { ?dx a sphn:BilledDiagnosis }
  } }
}
```

Le aggregazioni COUNT/SUM/AVG su piu livelli e i raggruppamenti interni sono
ammessi. Il valutatore locale `sparql_analyzer/nested.py` segue la provenienza
dei valori attraverso gruppi, alias, proiezioni e join. Non impone la soglia k
ai singoli gruppi intermedi: puo calcolare una media per paziente e aggregarla
successivamente. La chiave grafo puo rimanere privata nella sottoquery.

```sparql
PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>
SELECT (AVG(?patientAverage) AS ?cohortAverage)
WHERE {
  { SELECT (AVG(?value) AS ?patientAverage) WHERE {
      GRAPH ?g { ?quantity sphn:hasValue ?value }
    } GROUP BY ?g
  }
}
```

Il risultato finale deve essere una sola riga numerica con una coorte sufficiente
per ciascuna colonna e per le dipendenze di controllo tracciate (FILTER, HAVING,
ORDER BY). Ripetere uno scalare individuale su molti grafi non ne aumenta la
coorte di provenienza. Il confronto con l'esecuzione RDFLib originale verifica
che il calcolo non sia stato appiattito: la media delle medie mantiene il peso
dei pazienti. Il limite di lavoro conta cumulativamente le righe intermedie
nel percorso annidato. SAMPLE generato internamente da RDFLib per le chiavi
di gruppo e ammesso; SAMPLE scritto dall'utente resta vietato.

Il percorso senza aggregati annidati mantiene il requisito della variabile grafo
esportata. Il verdetto statico non sostituisce il controllo runtime e non
certifica l'anonimato. I bypass statistici descritti sotto restano aperti.
I test dedicati sono in `tests/test_subqueries.py` e `tests/test_nested_aggregates.py`.

Il runtime lavora su un Dataset RDFLib locale stabile; il percorso annidato
segue separatamente i grafi di origine delle diverse colonne.
Non e collegato a Virtuoso e non e adatto a caricare 50 GB in Python. In produzione
verifiche e risposta devono essere eseguite nel database sullo stesso snapshot.
Mancano ACL per utente e protezioni delle sequenze di query; le sei lacune della
suite avversaria restano aperte. Le soglie non risolvono inferenze, omogeneita,
differenze e ricostruzioni. Nessuna di queste verifiche certifica l'anonimato.

## Test e fixture

La suite mantiene i 32 casi originali, le regressioni e il corpus avversario.
Le nuove statistiche sono coperte in tests/test_numeric_operations.py con misure
sintetiche: otto grafi, valori da 10 a 17, somma 108 e media 13.5. Esempi .rq
separati sono in tests/numeric/queries/. Queste fixture non sono validate SHACL.

Il generatore originale produce 12 pazienti fittizi: 8 con diagnosi fatturate,
1 con diagnosi oncologica e 10 esami dello stesso paziente. Non usa dati reali.
I risultati rigenerabili sono in tests/results/; export_results include il corpus
avversario. I test risk_demonstration dimostrano rischi osservati; gli xfail strict
registrano requisiti non soddisfatti e non sono protezioni riuscite.

## Esito delle nuove sonde complesse

Il controllo attuale e aggirabile in alcune composizioni di operatori ammessi:
mascheramento con IF, riempimento con COALESCE/UNION e provenienza non correlata
possono produrre valori individuali pur contando almeno k grafi. Non interpretare
la coorte formale come prova di anonimato. Vedi [bypass riprodotti e test](../tests/adversarial_complex/README.md).
