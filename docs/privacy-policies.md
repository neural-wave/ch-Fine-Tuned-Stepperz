# Policy per i bypass di anonimato noti

Le sette opzioni `privacy_*` implementano controlli per i 17 scenari storici.
Sono disattivate nel profilo predefinito per conservare l'API senza contesto.
Il file [policies/hardened.json](../policies/hardened.json) o `Policy.hardened()`
le abilita tutte. Ogni opzione rimane attivabile separatamente tramite
`with_checks` o JSON, con le dipendenze indicate nel [catalogo](policy-checks.md).

## Cosa verifica ogni opzione

| Opzione | Controllo implementato |
|---|---|
| `privacy_effective_contributors` | Segue il ramo effettivamente valutato di IF/COALESCE; i riempimenti costanti e gli zeri artificiali non gonfiano la coorte. Mantiene separata la coorte di ogni aggregato usato nell'espressione finale, anche in rapporti e riscalamenti. |
| `privacy_correlated_patterns` | Rifiuta pattern non vuoti nel default graph: un valore o una condizione non correlata non puo essere associata artificialmente a molti grafi paziente. |
| `privacy_distinct_persons` | Converte le origini dei valori in identita canoniche da un mapping fidato: piu grafi della stessa persona non soddisfano la soglia. |
| `privacy_authorization` | Prima di interrogare il backend verifica che tutti i grafi non vuoti del Dataset siano compresi nell'ACL fornita per il principal. |
| `privacy_query_history` | Raffina le partizioni delle coorti gia rilasciate e blocca piccole differenze/intersezioni; rifiuta inoltre query diverse che rilasciano statistiche sulla stessa coorte. |
| `privacy_temporal_history` | Fissa lo snapshot al primo rilascio e rifiuta modifiche successive; verifica anche che il dataset non cambi durante i controlli. |
| `privacy_normalize_errors` | Sostituisce le eccezioni impreviste con un messaggio pubblico fisso, senza riportare dati o messaggi del backend nella catena di traceback visualizzata. |

## Contesto di esecuzione

Identita, ACL e storico devono provenire dal servizio, non dalla query o dal
client che invia la domanda. Il modulo non inventa autorizzazioni a partire
dal prefisso del grafo e non considera automaticamente fidati gli identificatori
contenuti nei dati RDF.

```python
from sparql_analyzer import Policy, ExecutionContext, ReleaseHistory
from sparql_analyzer.runtime import execute_checked

# Una sola istanza condivisa dal servizio, conservata tra le richieste.
history = ReleaseHistory(max_records=1000)

context = ExecutionContext(
    principal_id=authenticated_user_id,
    dataset_id=protected_population_id,
    allowed_graphs=authorized_graph_uris,
    graph_patients=trusted_graph_to_canonical_patient,
    history=history,
)

result = execute_checked(
    authorized_dataset,
    query,
    policy=Policy.hardened(),
    context=context,
)
```

`allowed_graphs` contiene anche eventuali grafi di ontologia/default non vuoti
presenti nel Dataset. Il controllo ACL e conservativo: il chiamante deve
fornire un Dataset gia delimitato all'utente; non viene costruita una vista
filtrata su un backend remoto. Un solo grafo fuori dall'ACL blocca la richiesta
prima di `dataset.query`. Il mapping canonico deve coprire ogni grafo paziente
effettivamente usato, comprese le copie della stessa persona.

Contesto, mapping o storico mancanti producono un blocco esplicito quando la
rispettiva policy e attiva. Non esiste un fallback al conteggio dei grafi.
L'ACL e il mapping vengono copiati in contenitori immutabili alla costruzione
del contesto. Nessuno di questi metadati viene aggiunto al payload restituito.

## Storico e snapshot

Lo storico e condiviso per `dataset_id`, anche tra principal diversi. Lo stesso
`dataset_id` deve identificare la stessa popolazione protetta: non va generato
per richiesta per evitare il confronto tra query. Per lo stesso insieme di
persone una query diversa viene bloccata in modo conservativo; la ripetizione
della stessa query e ammessa sullo stesso snapshot. Anche cambiare soltanto la
formattazione del testo produce un digest diverso. Le query grezze non vengono
conservate: si registrano digest, coorti canoniche e fingerprint.

Le coorti vengono confrontate anche con le intersezioni cumulative delle
richieste precedenti, non solo a coppie. Il lock copre esecuzione, verifica e
registrazione del rilascio. Risultati bloccati non aggiornano lo storico; quando
la capacita e esaurita si blocca senza espellere i record precedenti.

`ReleaseHistory` e uno storage **in memoria del singolo processo**. Va mantenuto
dal servizio e condiviso da tutte le richieste interessate. Riavviarlo, ricrearlo
per query o usare istanze isolate in piu worker perde la protezione tra rilasci:
per un servizio distribuito serve uno storage persistente e transazionale.
Non e stata aggiunta una persistenza simulata o un'identita derivata dal client.

Il fingerprint esamina il Dataset RDFLib locale prima e dopo la richiesta.
Una volta rilasciato un risultato, il profilo con guardia temporale blocca
qualsiasi cambiamento dello snapshot. Non permette automaticamente una nuova
epoca di pubblicazione: quella scelta richiede una policy esterna per il
rilascio nel tempo. Come il runtime esistente, non e un controllo da eseguire
caricando in Python un triplestore di produzione.

## Limiti e test

I gruppi individuali intermedi restano permessi: le loro coorti si combinano
attraverso i livelli di aggregazione prima del controllo finale. La provenienza
di ciascun aggregato resta distinta nell'aritmetica finale: moltiplicare una
media rara per un conteggio grande non nasconde la sua coorte insufficiente.

Il trattamento degli zeri derivati e conservativo: una trasformazione che
produce zero non aumenta la coorte, mentre una misura letta direttamente e
pari a zero conserva la provenienza. Alcune statistiche innocue possono quindi
essere soppresse. Aggregazioni dentro un nodo GRAPH non ancora tracciabili
vengono rifiutate quando il controllo dei contributi effettivi e attivo.

Questi controlli bloccano i casi riprodotti; non costituiscono una prova generale
di anonimato o differential privacy. Non coprono tutte le inferenze da conoscenza
esterna, l'omogeneita degli attributi, ogni possibile espressione equivalente,
ne i canali temporali di esecuzione o la distinzione tra rilascio e soppressione.
La normalizzazione degli errori non governa eventuali log interni del servizio.

I test prima marcati `xfail` sono regressioni effettive del profilo hardened:
11 varianti complesse e 6 scenari generali. Le osservazioni del profilo storico
restano nella suite per dimostrare l'effetto dei toggle. I test positivi, quelli
sui prerequisiti e quelli di disattivazione sono in `tests/test_privacy_policies.py`.

La [matrice dei profili effettivamente testati](../tests/README.md#profili-usati-nei-test)
distingue suite predefinita, hardened e override dei toggle. I 470 test passati
sono il totale misto, non 470 esecuzioni hardened. Nei test dei bypass complessi
la normalizzazione degli errori e disattivata: un crash inatteso deve fallire il
test, anziche essere normalizzato e contato come blocco dell'attacco.
