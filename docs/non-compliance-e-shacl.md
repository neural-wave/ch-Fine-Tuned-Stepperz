# Non compliance SPARQL: teoria, controlli e ruolo di SHACL

## Scopo e stato del progetto

Il sistema deve rispondere a domande su coorti senza esporre informazioni
individuali. Una query puo essere sintatticamente valida ma violare la privacy,
usare un modello clinico sbagliato o essere troppo costosa.

Le cinque regole applicative sono definite in [Query_Compliance.md](../Query_Compliance.md).
Le etichette R1-R5 sono convenzioni del nostro validatore, non codici dello
standard SPARQL o SHACL. API_specification.md ammette alcune forme read-only
che Query_Compliance.md vieta: attualmente prevale il secondo documento.

Questo documento descrive scenari da verificare, non certifica che ogni esempio
aggiri il codice attuale. Dove il validatore non supporta una struttura, la blocca.
I test coprono esempi finiti e non provano l'assenza di altri casi.

## Quattro verifiche diverse

| Livello | Domanda | Stato |
|---|---|---|
| Sintassi | Il parser comprende la query? | RDFLib, SPARQL standard |
| Policy e autorizzazione | La richiesta e consentita per utente e dataset? | Controlli statici e ACL locale con contesto fidato; vedi profilo hardened |
| Modello e qualita dei dati | Classi, relazioni e valori rispettano lo schema clinico? | Policy SHACL locale implementata, opt-in nel default e attiva in adequacy/hardened |
| Risultati e privacy runtime | Cosa viene davvero restituito e quanti pazienti contribuiscono? | COUNT/SUM/AVG anche annidati, provenienza, coorti e storico opzionale |

Una risposta positiva a uno di questi livelli non sostituisce gli altri.
Configurazione e perimetro implementato sono nella
[policy di adeguatezza SHACL](adequacy-shacl.md) e nelle [policy privacy](privacy-policies.md).

## R1: selezione di un paziente identificabile

Un conteggio non e sicuro solo perche non mostra il nome del paziente.
Se il filtro riguarda una persona nota, il risultato puo confermare una diagnosi.

Esempio con identificatore fittizio:

```sparql
PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>
SELECT (COUNT(?dx) AS ?diagnoses)
WHERE {
  GRAPH ?g {
    ?dx a sphn:BilledDiagnosis ; sphn:hasSubjectPseudoIdentifier ?subject .
    ?subject sphn:hasIdentifier ?id .
  }
  BIND(STR(?id) AS ?alias)
  FILTER(?alias = "SYNTH-0042")
}
```

**Limite dei controlli semplici:** cercare solo un GRAPH costante o il nome
di una variabile non rileva necessariamente VALUES, alias, filtri o sottoquery.
Anche una combinazione di eta, data e diagnosi rara puo identificare una persona
senza alcun identificatore esplicito.

**Difese:** propagazione della sensibilita attraverso le espressioni, scope delle
sottoquery, vocabolario completo degli identificatori e conteggio della coorte
reale. La policy attuale segue alcuni alias, ma non comprende tutta la semantica
clinica o tutti i predicati possibili.

## R2: risultati individuali invece di statistiche di coorte

Una query puo contenere COUNT e restituire comunque una riga per paziente:

```sparql
PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>
SELECT ?g (COUNT(?dx) AS ?diagnoses)
WHERE { GRAPH ?g { ?dx a sphn:BilledDiagnosis . } }
GROUP BY ?g
```

**Limite semplice:** cercare la parola COUNT senza verificare GROUP BY e le
colonne finali. Un'aggregazione in una sottoquery non garantisce che l'output
della query esterna sia aggregato. DISTINCT elimina duplicati, non anonimizza.

**Difese:** verificare ogni proiezione finale, i gruppi e la provenienza dei valori
per ciascuno scope. I raggruppamenti per categorie cliniche possono essere
legittimi; vanno distinti da quelli individuali e verificati gruppo per gruppo.
Attualmente i gruppi per categoria sono bloccati come non supportati.

## R3: lettura indiscriminata del grafo

```sparql
PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>
SELECT (COUNT(*) AS ?rows)
WHERE {
  { GRAPH ?g { ?dx a sphn:BilledDiagnosis . } }
  UNION
  { GRAPH ?other { ?s ?p ?o . } }
}
```

**Limite semplice:** trovare almeno una condizione clinica nel testo e concludere
che restringa tutta la query. Il secondo ramo UNION puo leggere qualsiasi tripla.
Lo stesso problema puo comparire in OPTIONAL, sottoquery e percorsi molto ampi.
LIMIT limita l'output, non garantisce un costo basso o una scansione ristretta.

**Difese:** analizzare ogni ramo e la correlazione delle variabili; usare grafi
autorizzati, limiti di tempo, memoria e righe intermedie. Il codice attuale blocca
i pattern completamente variabili, con falsi positivi intenzionali, ma non stima
il costo completo della query. Un predicato fisso puo comunque leggere moltissimi dati.

## R4: operazioni o canali non autorizzati

SELECT, ASK, CONSTRUCT e DESCRIBE sono forme di query; INSERT, DELETE, LOAD,
CLEAR e altre operazioni appartengono a SPARQL Update. La nostra policy permette
solo SELECT. Essere read-only non equivale a rispettare la policy di privacy.

**Limite semplice:** controllare il primo token o cercare DELETE con una regex.
PREFIX, BASE, commenti e stringhe rendono questi controlli fragili; query e update
devono essere riconosciuti mediante la grammatica appropriata.

Anche SELECT puo contenere SERVICE, che coinvolge un endpoint esterno, o FROM
e FROM NAMED, che cambiano il dataset descritto dalla richiesta. Questi elementi
richiedono una policy di rete e dataset, indipendente dall'assenza di scritture.

**Difese:** selezionare le forme ammesse dall'AST, bloccare rete e dataset non
autorizzati, usare credenziali database di sola lettura e non esporre endpoint
alternativi che aggirino i controlli. SERVICE e clausole dataset sono attualmente
bloccati come non supportati; il runtime non e ancora collegato a Virtuoso.

## R5: identificatori o valori sensibili nell'output

```sparql
PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>
SELECT (GROUP_CONCAT(DISTINCT ?alias; separator="|") AS ?summary)
WHERE {
  GRAPH ?g { ?subject sphn:hasIdentifier ?id . }
  BIND(STR(?id) AS ?alias)
}
```

**Limite semplice:** vietare colonne chiamate id o patient. Il nome summary non
cambia la provenienza del dato. GROUP_CONCAT concatena, MIN/MAX/SAMPLE possono
selezionare un identificatore; non sono automaticamente anonimizzazioni.
Hash, sottostringhe e codifiche non garantiscono anonimato e possono conservare
la possibilita di collegare record o riconoscere un identificatore noto.

**Difese:** seguire la provenienza attraverso espressioni e aggregazioni;
approvare trasformazioni specifiche invece di fidarsi dei nomi. Verificare anche
la risposta serializzata, inclusi metadati ed errori. Regex su email o identificatori
sono un controllo aggiuntivo, non una prova: una data o un numero possono essere
sensibili senza avere un formato speciale.

Il runtime predefinito accetta aggregati numerici verificati e controlla la
corrispondenza con il ricalcolo interno. check_payload da solo non controlla la provenienza.

## Ulteriori rischi non coperti dalle cinque regole

### Coorti piccole e confronti tra query

Dieci esami di una sola persona non equivalgono a dieci pazienti. Va verificato
il numero di pazienti distinti che contribuiscono a ciascun aggregato, anche nei
rami OPTIONAL. Questa verifica e presente nel prototipo runtime locale.

Una soglia k non basta: due query quasi identiche, entrambe sopra soglia, possono
differire per una sola persona. La differenza dei risultati puo rivelarne una
caratteristica. Servono una policy delle interrogazioni ripetute e, secondo il
modello di rischio, controlli di composizione o meccanismi di privacy differenziale
con un budget definito. Lo storico opzionale implementa controlli conservativi
su coorti e snapshot; non e implementato un meccanismo di privacy differenziale.

### Grafo, paziente e autorizzazioni

Il runtime predefinito conta grafi paziente. Il prefisso di un URI non dimostra che
il grafo rappresenti una persona distinta o che l'utente possa accedervi.
Uno stesso paziente in piu grafi puo gonfiare la coorte. Occorre una mappatura
affidabile, deduplicazione e autorizzazioni applicate prima dell'esecuzione.
Questi controlli sono attivi nel profilo hardened con contesto fidato.

### Snapshot, errori e costi

Tra il conteggio della coorte e la query finale i dati possono cambiare. In
produzione le verifiche devono operare sullo stesso snapshot o transazione.
I controlli privacy sullo storico e la nuova policy SHACL confrontano i
fingerprint prima e dopo l'esecuzione; questo non equivale a una transazione
e non rileva modifiche intermedie poi annullate.

Errori, log, messaggi SHACL e risultati intermedi possono contenere dati grezzi.
Devono restare su canali protetti e non diventare risposte pubbliche. Timeout e
limiti di memoria devono valere anche per la query di supporto: il limite attuale
di righe non ferma necessariamente un join costoso prima della prima riga.

### Coerenza semantica e inferenza

Un conteggio puo essere sicuro e clinicamente sbagliato: join tra casi diversi,
duplicazioni, unita incompatibili, codici di versioni diverse o inferenza diversa
tra parser e database. Occorre distinguere conteggi di righe, eventi e pazienti.
Le estensioni Virtuoso non devono essere eliminate dal testo senza verificare
che la semantica resti equivalente. Oggi non sono supportate.

## SHACL: il nome e cosa valida

Il nome e **SHACL**, Shapes Constraint Language. Lo standard descrive vincoli
su un grafo RDF e produce un report di validazione. Non e, di per se, un
controllore di privacy delle query SPARQL.

In questo progetto il file e [shacler_shapes.ttl](../shacl/shacler_shapes.ttl).
Contiene classi destinatarie e vincoli su proprieta, cardinalita, tipi, relazioni
e controlli espressi in SPARQL. Le query dentro sh:select sono parte delle shape:
non sono le query utente da autorizzare con la nostra policy R1-R5.

| Verifica | Esempio | Strumento concettuale |
|---|---|---|
| Conformita del dato | Una diagnosi ha sorgente, codice e collegamento al soggetto? | Motore SHACL sul grafo dati |
| Coerenza del pattern della query | hasCode viene usato per collegare le risorse corrette? | Analisi AST + ontologia/shape, con limiti espliciti |
| Privacy della query | La query espone il soggetto o seleziona una persona? | Policy R1-R5 + controlli runtime |
| Formato della risposta | Sono restituiti solo i conteggi approvati? | Contratto sui risultati |

Una SELECT che legge solo il tipo di una diagnosi non deve ripetere tutti i campi
obbligatori della shape nel WHERE. Sono le istanze del grafo a dover rispettare
quei vincoli. Allo stesso modo, una tabella SPARQL Results JSON non si valida
direttamente contro le shape cliniche delle istanze RDF.

SHACL puo guidare l'analisi dei pattern, ma una proprieta assente da una shape
non e automaticamente vietata: nel file sono presenti shape aperte con
sh:closed false. Per una whitelist serve una decisione applicativa esplicita,
non l'assunzione che tutte le shape siano chiuse.

## Riscontri sul file locale e sulla fixture

L'ispezione del file Turtle ha rilevato 16211 triple, 621 NodeShape e 688
collegamenti sh:sparql. Questi conteggi descrivono il file presente, non un
risultato di validazione. Il file dichiara un regime RDFS e contiene severity
Warning e Info oltre ai vincoli ordinari: la policy li gestisce con toggle distinti.

Esempi di requisiti effettivamente presenti:

- BilledDiagnosis: hasSourceSystem, hasCode e hasSubjectPseudoIdentifier richiesti.
- SubjectPseudoIdentifier: hasIdentifier di tipo xsd:string e hasDataProvider richiesti.

La fixture tests/data/synthetic/cohort.trig omette hasSourceSystem e hasCode
nelle diagnosi e hasDataProvider nei soggetti. Non puo quindi essere presentata
come fixture SPHN conforme: e intenzionalmente minimale per i test del filtro
di privacy. Queste fixture restano separate dai dati dedicati ai test SHACL.

I test SHACL usano un secondo insieme di fixture: una valida rispetto alle
shape selezionate, poi varianti che violano un vincolo per volta. Non serve rendere
silenziosamente piu permissive le shape per fare passare i dati esistenti.

## Come integrare SHACL correttamente

1. Scegliere un motore che supporti SHACL Core e i vincoli SHACL-SPARQL usati
   dal file. Definire la versione di shape e ontologie da validare.
2. Definire il grafo dati: paziente per paziente, oppure una vista controllata
   dell'intero dataset. Non usare implicitamente l'unione di tutti i named graph:
   potrebbe nascondere collegamenti mancanti nel grafo di un paziente.
3. Configurare l'inferenza RDFS e le terminologie necessarie. La sola dichiarazione
   sh:entailment non significa che il nostro codice la esegua automaticamente.
4. Validare dati e shape con fixture positive e negative; verificare anche che
   i target trovino le istanze attese. Nessun target attivato non prova la qualita
   del dataset. Un errore del motore non equivale a conformita.
5. Conservare report completi su canali protetti. Il report puo contenere focusNode
   e value sensibili. Definire come l'applicazione tratta Violation, Warning e Info
   senza confondere la sua soglia operativa con sh:conforms dello standard.
6. Eseguire la validazione all'ingestione e quando cambiano dati/shape/ontologie;
   collegare l'esito a uno snapshot. Tenere separato il controllo per ogni query.

Il percorso locale e ora implementato in `sparql_analyzer/adequacy.py` con
pySHACL, copie immutabili delle shape, validazione separata per grafo, target
SPARQL, RDFS e controlli configurabili su target, meta-schema e severita.
Vedi [policy SHACL e test](adequacy-shacl.md). Restano da implementare
validazione all'ingestione con attestazioni persistenti e integrazione con
snapshot/transazioni Virtuoso; nessuna certificazione del dataset completo
deriva dalle fixture sintetiche.

## Priorita consigliate

1. Definire vocabolario autorizzato, predicati sensibili e mappatura grafo/paziente.
   Il controllo attuale sul prefisso SPHN non verifica l'esistenza di una proprieta
   nell'ontologia: anche un nome errato nello stesso namespace richiede controllo.
2. Estendere i test SHACL a dati clinici e ontologie reali; il motore locale e le fixture dedicate sono disponibili.
3. Aggiungere controlli di coerenza dei pattern di query con schema e ontologia,
   senza chiamarli impropriamente validazione SHACL completa della query.
4. Collegare il runtime a Virtuoso con autorizzazioni, snapshot e limiti effettivi.
5. Ampliare i test di scope, alias, predicati alternativi, coorti e risposte malformate.
6. Affrontare query ripetute, inferenze e logging secondo il rischio concordato.

## Riferimenti

- [W3C SHACL: validazione di grafi RDF](https://www.w3.org/TR/shacl/).
- [W3C SHACL: shape aperte e chiuse](https://www.w3.org/TR/shacl/#ClosedConstraintComponent).
- [W3C SHACL: report di validazione](https://www.w3.org/TR/shacl/#validation-report).
- [W3C SPARQL 1.1: grammatica, dataset e operatori](https://www.w3.org/TR/sparql11-query/).
- [Implementazione e limiti attuali](sparql.md).
- [Query di test con aspettative](../tests/cases/README.md).
