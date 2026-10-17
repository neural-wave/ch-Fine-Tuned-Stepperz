# Configurazione di analisi e restrizioni

Ogni richiesta accetta una `Policy` immutabile. Non ci sono flag globali da
modificare e due chiamate possono usare configurazioni diverse. Senza argomenti
aggiuntivi rimane attivo il comportamento precedente.

## Modificare gli interruttori

Il file [policies/default.json](../policies/default.json) contiene tutti gli
interruttori e i limiti numerici. I controlli storici sono a `true`; le sette
nuove opzioni `privacy_*` sono opt-in e abilitate nel profilo
[hardened](../policies/hardened.json). Vedi [protezioni e contesto richiesto](privacy-policies.md).
Copialo e cambia i booleani oppure scrivi solo le differenze:

```json
{
  "checks": {
    "runtime_cohort": false,
    "runtime_control_cohort": false,
    "forbid_min": false
  },
  "limits": {
    "min_patients": 10,
    "max_query_chars": 200000,
    "max_support_rows": 500000
  }
}
```

I nomi e i tipi vengono verificati: un nome errato o `"false"` al posto del
booleano `false` produce un errore. Il [catalogo completo](policy-checks.md)
riporta effetto e dipendenze di ogni interruttore.

I divieti sono indipendenti. Per esempio, disattivare `forbid_min` elimina il
divieto sintattico di MIN, ma restano attivi `supported_aggregates` e
`runtime_aggregates`: per eseguire MIN su misure numeriche, disattiva tutti e tre.
Analogamente, `runtime_global_group` e `result_single_row` sono due controlli
distinti sulla cardinalita finale.

## Python

```python
import json
from pathlib import Path
from sparql_analyzer import Policy
from sparql_analyzer.compliance import validate
from sparql_analyzer.runtime import execute_checked

policy = Policy.from_dict(json.loads(Path("policies/default.json").read_text()))
policy = policy.with_checks(runtime_cohort=False)

verdict = validate(query, policy=policy)
result = execute_checked(dataset, query, policy=policy)
```

Per cambiare un limite da Python:

```python
from dataclasses import replace

policy = replace(policy, min_patients=10, max_support_rows=500000)
```

Gli argomenti preesistenti `min_patients=` e `max_support_rows=` di
`execute_checked` restano disponibili e prevalgono sui limiti della policy.
Anche `analyze(query, policy=policy)` rispetta gli interruttori delle analisi.

## CLI del validatore statico

```powershell
uv run python -m sparql_analyzer.compliance --list-checks
uv run python -m sparql_analyzer.compliance query.rq --policy policies/default.json
uv run python -m sparql_analyzer.compliance query.rq --disable sensitive_filter
uv run python -m sparql_analyzer.compliance query.rq --disable sensitivity_analysis
uv run python -m sparql_analyzer.compliance query.rq --enable sensitive_output
```

La CLI valida e non esegue query. I flag runtime del file vengono applicati
quando lo stesso oggetto `Policy` viene passato a `execute_checked`.

Ogni finding contiene `check`, il nome dell'interruttore che lo ha prodotto,
oltre al precedente codice R1/R2/... . La risposta include `configuration`, con
gli interruttori effettivi e i limiti. I codici delle violazioni e gli import
precedenti da `compliance` e `runtime` restano disponibili.

## Dipendenze delle analisi

Disattivare un'analisi disattiva anche i controlli che ne dipendono. Per esempio,
`support_analysis=false` salta il calcolo di coorti e provenienza, disattivando
le soglie e il confronto con il ricalcolo. Rimangono attive le regole statiche
e i controlli del payload, salvo disattivazione separata.

Attivare un controllo riattiva le analisi necessarie. Non riattiva gli altri
controlli che erano stati disattivati. Una richiesta contemporanea come
`support_analysis=False, runtime_cohort=True` e contraddittoria e viene rifiutata.
`policy.to_dict()` mostra sempre la configurazione effettiva, incluse le
disattivazioni dipendenti. Il catalogo elenca le dipendenze.

`syntax_analysis` governa la visita dell'AST; `algebra_analysis` governa l'albero
serializzato e le analisi statiche; `scope_analysis` governa la separazione delle
variabili locali. Parsing e traduzione necessari per preparare una query restano
operazioni del motore, anche quando queste analisi sono spente.

## Esecuzione senza controlli

[policies/unrestricted.json](../policies/unrestricted.json) disattiva tutti gli
interruttori. L'equivalente Python e `Policy(enabled_checks=frozenset())`.
Il percorso originale RDFLib puo cosi restituire anche SELECT individuali e ASK,
senza il contratto di output numerico o il calcolo delle coorti.

Disattivare un divieto non implementa un operatore mancante nel motore. Il
valutatore con provenienza supporta un sottoinsieme dell'algebra: per delegare
al motore RDFLib originale si puo disattivare `support_analysis`. Sintassi
SPARQL invalida e dialetti non riconosciuti dal parser restano errori. Il
runtime restituisce SPARQL Results JSON per SELECT/ASK; non esegue Update e non
esporta grafi CONSTRUCT/DESCRIBE. Questi limiti sono distinti dalle restrizioni
di policy tramite `UnsupportedExecution`, sottoclasse di `ResultBlocked`.

La configurazione predefinita conserva le protezioni precedenti. Il profilo
hardened aggiunge i controlli per i bypass noti con contesto fidato; nessuno
dei due certifica l'anonimato generale.

## Organizzazione del codice

| Modulo | Responsabilita |
|---|---|
| `policy.py` | Catalogo dei toggle, limiti e dipendenze |
| `parser.py`, `algebra.py` | Parsing, scope e visite dell'algebra |
| `analysis.py` | Classificazione numerica, sensibilita e dipendenze da aggregati |
| `rules.py`, `validation.py` | Regole statiche e orchestrazione della validazione |
| `runtime.py` | API e scelta del percorso di esecuzione |
| `flat.py`, `nested.py` | Valutazione delle query semplici e annidate |
| `provenance.py` | Righe interne e provenienza dei valori |
| `privacy.py` | Contesto fidato, ACL, identita, snapshot e storico dei rilasci |
| `results.py` | Contratto dei risultati, numeri ed eccezioni |
| `vocabulary.py` | Vocabolario RDF e operatori riconosciuti |
| `cli.py`, `compliance.py` | CLI e compatibilita dell'API precedente |

Per aggiornare gli esempi e il catalogo dopo una modifica al registro:
`uv run python -m sparql_analyzer.export_policy`. Il comando sovrascrive i
file di esempio e il catalogo; conserva le configurazioni personalizzate in file separati.
