# Validatore deterministico SPARQL

Implementazione: `sparql_analyzer/compliance.py`. Non usa LLM, non esegue query, non
contatta endpoint. Analizza sintassi e algebra con RDFLib e applica regole
statiche. A parita di query, policy e versioni delle dipendenze restituisce
lo stesso risultato.

```powershell
uv run python -m sparql_analyzer.compliance tests/cases/00_compliant.rq
uv run python -m sparql_analyzer.compliance tests/cases/07_identifier_alias.rq --out verdict.json
uv run python -m tests.export_results
uv run pytest -v
```

Il CLI restituisce exit code 0 solo per query approvate, 1 per query bloccate.
In Python: `from sparql_analyzer.compliance import validate`, poi `validate(query_text)`.

Ogni risultato contiene:

- `is_compliant`: true solo se tutti i controlli passano.
- `status`: compliant, non_compliant o unsupported.
- `violations`: regole R1-R5 riconosciute.
- `findings`: motivazioni, comprese sintassi o strutture non supportate.
- `policy`: versione della policy, conservative-count-v1.

I casi non supportati vengono bloccati; non sono automaticamente considerati
violazioni dimostrate. Se esistono anche violazioni riconosciute, lo status
e non_compliant e findings conserva anche i motivi di mancato supporto.

## Controlli

- R1: grafi fissi non autorizzati, riferimenti al namespace pazienti,
  soggetti fissi, identificatori costanti, filtri e raggruppamenti su risorse
  individuali, BIND costanti verso variabili individuali.
- R2: proiezioni non derivate esclusivamente da aggregazioni e gruppi individuali.
- R3: pattern con soggetto, predicato e oggetto tutti variabili, anche nei rami
  o nelle sottoquery. Per prudenza il blocco vale anche se un altro pattern
  potrebbe restringere la scansione.
- R4: qualunque forma diversa da SELECT, compresi gli update.
- R5: variabili grafo, soggetti e valori dei predicati identificatore esposti
  in uscita. La propagazione segue alias/BIND e aggregazioni come GROUP_CONCAT;
  COUNT interrompe la propagazione dell'identificatore.

## Ambito approvato e limiti

La prima policy approva conteggi globali COUNT/COUNT DISTINCT con pattern
SPHN/rdf:type, incluse combinazioni supportate di pattern e filtri.
Il filtro STRSTARTS sul namespace completo dei grafi paziente e consentito.
Il namespace pazienti, il grafo ontologie autorizzato e i predicati identificatore
sono configurati come costanti in sparql_analyzer/compliance.py, coerenti con il progetto.

SUM/AVG/MIN/MAX, raggruppamenti per categoria, sottoquery, VALUES, property path,
SERVICE, FROM/FROM NAMED, funzioni e operatori non verificati vengono bloccati.
Le estensioni Virtuoso DEFINE e OPTION(inference) non vengono riscritte:
producono un blocco per sintassi non supportata.

Questa scelta produce falsi positivi intenzionali. Un filtro su una risorsa
puo essere innocuo ma viene bloccato. Il riconoscimento degli identificatori
dipende dal vocabolario configurato; aggiungere nuovi predicati richiede
aggiornare la policy e i test. Non si puo dedurre dalla sola sintassi se una
coorte clinica identifica indirettamente una persona, ne se contiene almeno k
pazienti. Qui non viene applicata una soglia minima di coorte.

Non e una prova completa di privacy o una soluzione per ogni offuscazione.
Prima di usarlo come controllo di accesso occorre definire dataset autorizzati,
vocabolari, soglie e dialetto Virtuoso, ed estendere la verifica degli scope.
Le regole applicate sono quelle piu restrittive di ../Query_Compliance.md,
anche dove ../API_specification.md ammette altre forme read-only.

I test pytest comprendono 19 regressioni e i 32 file .rq, ciascuno come test
separato tramite @pytest.mark.parametrize. Per eseguirne uno: 

```powershell
uv run pytest -v -k identifier_alias
```

Dipendenze dei test: `uv sync --locked`.

## Alberi e demo locale

Dalla radice del progetto:

```powershell
uv run python -m sparql_analyzer.demo
uv run python -m sparql_analyzer.demo --query queries/classes.rq --out tests/results/manual
uv run python -m tests.export_results
```

Il demo senza --query esegue una query di conteggio in memoria su dati fittizi
(il risultato atteso e 2). Con --query analizza il file senza eseguirlo.
Il parser riutilizzabile e in sparql_analyzer/parser.py; la libreria non dipende
dai test. Gli alberi JSON sono quelli RDFLib, non i piani Virtuoso.
I risultati separati dei 32 casi sono in tests/results/<nome>/; report.json
contiene il riepilogo. Sono rigenerabili con il comando export_results.

## Controllo runtime locale

```powershell
uv run python -m tests.generate_synthetic_data --patients 12 --seed 42
uv run python -m tests.demo_runtime
uv run pytest -v
```

Il generatore locale tests/generate_synthetic_data.py crea esclusivamente dati
fittizi in tests/data/synthetic/cohort.trig: 12 pazienti, 8 con diagnosi fatturate,
1 con diagnosi oncologica e 10 esami appartenenti allo stesso singolo paziente.
Identificatori, nomi ed email sono inventati; example.invalid non e un dominio
reale di contatto. La fixture e piccola, non e una simulazione clinica validata.
Il tool generate-patients.sh citato dal README originale non era presente;
questo e un nuovo generatore locale, non quel tool e non un servizio esterno.

```python
from sparql_analyzer.runtime import execute_checked, ResultBlocked
try:
    response = execute_checked(dataset, query_text, min_patients=5)
except ResultBlocked:
    # Non inviare il risultato grezzo; restituire solo un messaggio di blocco.
    response = None
```

execute_checked applica prima la policy statica, poi misura i pazienti distinti
che contribuiscono a ciascun COUNT usando il pattern WHERE prima dell'aggregazione.
Un ramo OPTIONAL con contributi di un solo paziente blocca l'intera risposta,
anche quando il conteggio principale coinvolge una coorte abbastanza grande.
La soglia 5 e dimostrativa e configurabile, non una garanzia di privacy.

Prima della restituzione controlla colonne, singola riga, tipi xsd:integer,
valori interi non negativi e corrispondenza con i conteggi ricalcolati internamente.
URI, stringhe, colonne aggiuntive, metadati inattesi e valori incoerenti bloccano
l'intera risposta. I messaggi di blocco non includono valori grezzi del risultato.
check_payload da solo verifica solo la forma: non sostituisce execute_checked.

La policy runtime e piu stretta di quella statica: solo COUNT globali diretti
con argomento variabile o *, alias diretti e una sola variabile grafo paziente.
COUNT(DISTINCT *) ed espressioni aritmetiche in uscita sono bloccati. Il controllo
ha un limite di 100000 righe interne di supporto; il superamento blocca la risposta.

Questa implementazione lavora solo su un Dataset RDFLib locale stabile.
Non e ancora collegata all'endpoint Virtuoso. Non modificare il dataset durante
la verifica: in produzione risultati e coorti devono provenire dallo stesso
snapshot/transazione con una mappatura affidabile tra grafi e pazienti.
La soglia non risolve attacchi per differenza tra query, inferenze o selezioni
cliniche identificanti. I test non costituiscono una prova completa di privacy.

Il report dimostrativo e in tests/results/runtime-demo.json.
