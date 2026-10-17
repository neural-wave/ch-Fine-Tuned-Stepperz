# Operazioni della policy numeric-aggregates-v3

Non esiste una classificazione universale in cui ogni uso di un operatore e
sicuro. Questa tabella descrive il sottoinsieme implementato, con controlli
sugli argomenti e sui risultati. Gli operatori non verificati restano bloccati.

| Operazione | Supporto corrente |
|---|---|
| SELECT | Solo output di statistiche approvate |
| COUNT, COUNT DISTINCT | Conteggi globali, k per aggregato; COUNT(DISTINCT *) resta escluso |
| SUM, AVG, varianti DISTINCT | Misure numeriche autorizzate e finite, k per aggregato |
| +, -, *, /, segno unario | Su statistiche approvate o misure autorizzate; divisione per zero bloccata |
| ABS, ROUND, CEIL, FLOOR | Su espressioni numeriche verificate |
| IF, COALESCE | Nel risultato o negli aggregati solo quando espressioni e rami sono numerici verificabili |
| FILTER, confronti e operatori logici | Controllo delle variabili sensibili e dei costrutti usati |
| GRAPH, join di triple | Una variabile grafo paziente nel runtime; prefisso autorizzato |
| UNION, OPTIONAL, MINUS | Pattern verificati; coorte distinta per ogni colonna |
| BIND | Alias ed espressioni verificate; la sensibilita viene propagata |
| HAVING | Aggregati verificati, soglia anche per quelli non proiettati |
| ORDER BY, LIMIT, OFFSET, DISTINCT | Non rendono anonimi i dati; non sostituiscono le verifiche sulle colonne |
| Funzioni su stringhe | STR, STRSTARTS, STRENDS, CONTAINS, STRLEN, LCASE, UCASE, STRBEFORE, STRAFTER, REGEX nei contesti ammessi; non autorizzano testo individuale in uscita |
| Funzioni su date | YEAR, MONTH, DAY, HOURS, MINUTES, SECONDS, TZ, TIMEZONE nei contesti ammessi; non autorizzano date individuali in uscita |
| Test di tipo | isNumeric, isIRI/isURI, isBlank, isLiteral, DATATYPE, LANG, LANGMATCHES, sameTerm nei contesti ammessi |
| GROUP_CONCAT, SAMPLE, MIN, MAX | Vietati esplicitamente, anche annidati |
| SERVICE, FROM, FROM NAMED | Vietati esplicitamente |
| ASK, CONSTRUCT, DESCRIBE, SPARQL Update | Vietati esplicitamente |
| GROUP BY per categoria, sottoquery, VALUES, property path | Non ancora supportati dal flusso completo |
| Hash, funzioni per URI arbitrarie, RAND/NOW e funzioni esterne | Non approvati da questa policy |
| DEFINE, OPTION(inference) | Dialetto Virtuoso non supportato |

## Esempio

```sparql
PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>
SELECT (COUNT(DISTINCT ?g) AS ?patients)
       (AVG(?v) AS ?average)
       (SUM(?v) AS ?total)
       (ROUND(AVG(?v)) AS ?rounded_average)
WHERE {
  GRAPH ?g { ?quantity sphn:hasValue ?v . }
}
```

Il runtime verifica separatamente la coorte di ogni aggregato e rifiuta valori
non numerici, non finiti o incoerenti con i risultati ricalcolati.
La classificazione numerica iniziale usa sphn:hasValue, configurata nella
costante NUMERIC_PREDICATES. Nuovi predicati richiedono una revisione del modello
e test: il tipo numerico da solo non distingue una misura da un identificatore.
Non viene provato che il dato esterno usi correttamente quel predicato.

Le unita devono essere omogenee; non sono convertite automaticamente. AVG degli
eventi e AVG delle medie per paziente sono statistiche diverse. La seconda
richiede scope e aggregazioni annidate ancora non supportati.

La soglia k, i tipi numerici e i divieti non impediscono da soli deduzioni tra
query ripetute. Restano le lacune indicate nella suite avversaria.

Riferimento alla semantica degli operatori:
[W3C SPARQL 1.1](https://www.w3.org/TR/sparql11-query/).

## Bypass riprodotti nelle espressioni ammesse

Le [sonde complesse](../tests/adversarial_complex/README.md) mostrano che la policy
v3 rilascia misure individuali tramite SUM/IF, COALESCE, zeri UNION e medie
riscalate, pur superando la soglia formale. Le operazioni elencate sono quindi
supportate tecnicamente, non certificate sicure in tutte le composizioni.
I risultati sono riprodotti su dati fittizi senza modificare il controllore.
