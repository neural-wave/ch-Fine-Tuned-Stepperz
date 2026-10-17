# Attacchi all'anonimato tramite query

Questo documento raccoglie le principali famiglie di attacchi da considerare
nel sistema NL-to-SPARQL su dati clinici. Non è un elenco esaustivo di tutte le
varianti: alcune espongono direttamente valori, altre permettono di dedurre
informazioni individuali da risultati apparentemente anonimi.

Gli scenari descrivono rischi da verificare, non dimostrano che ogni tecnica
aggiri il validatore attuale. Un costrutto non supportato viene bloccato.

## 1. Esposizione diretta o mascherata

| Tipo | Come può rivelare dati |
|---|---|
| **Estrazione diretta** | Restituisce identificatori, URI di pazienti, date o testo clinico individuale. |
| **Alias e trasformazioni** | Rinomina un identificatore oppure lo trasforma in stringa per superare controlli basati sui nomi. |
| **Aggregazione che conserva valori** | `GROUP_CONCAT` restituisce elenchi; `SAMPLE`, `MIN` e `MAX` possono restituire un valore individuale. |
| **Codifica e hash** | Nasconde il formato originario senza necessariamente eliminare riconoscibilità e collegabilità. |
| **Estrazione per frammenti** | Richiede porzioni diverse dello stesso valore in più interrogazioni. |
| **Esportazione di grafi** | Usa `CONSTRUCT` o `DESCRIBE` per ottenere risorse e relazioni invece di colonne tabellari. |
| **Paginazione** | Estrae gradualmente molti record tramite richieste successive, anche se ogni risposta è piccola. |

La difesa principale è seguire la **provenienza delle colonne**, non soltanto
cercare nomi come `patient_id` o riconoscere email nel risultato. Un numero può
essere un conteggio oppure un identificatore; il valore da solo non distingue i due casi.

## 2. Identificazione attraverso filtri e gruppi

| Tipo | Come può rivelare dati |
|---|---|
| **Selezione esplicita di una persona** | Identifica il paziente attraverso grafo, identificatore, `VALUES` o filtri. |
| **Selezione tramite quasi-identificatori** | Combina età, luogo, date e altri attributi fino a isolare una persona. |
| **Raggruppamento individuale** | Usa un aggregato, ma produce una riga per paziente o per evento identificabile. |
| **Gruppi rari** | Una combinazione di caratteristiche produce una coorte molto piccola. |
| **Collegamento con fonti esterne** | Associa attributi restituiti a informazioni già conosciute sull'individuo. |
| **Omogeneità del gruppo** | Anche una coorte numerosa può rivelare un attributo: se tutti i membri condividono una diagnosi, conoscere l'appartenenza al gruppo può bastare. |

Una coorte grande non implica automaticamente anonimato. La disponibilità di
informazioni esterne contribuisce alla possibilità di collegare dati a persone.
Il controllo deve considerare quali attributi vengono filtrati e raggruppati,
non solo quanti individui partecipano al risultato.

## 3. Deduzioni da aggregazioni e query ripetute

| Tipo | Come può rivelare dati |
|---|---|
| **Inferenza di appartenenza** | Un risultato conferma se una persona appartiene a una coorte sensibile. |
| **Differenza tra conteggi** | Confronta due popolazioni che differiscono per una sola persona. |
| **Intersezione di coorti** | Incrocia più risultati per restringere progressivamente il gruppo. |
| **Ricostruzione da molte statistiche** | Combina abbastanza aggregazioni da ricostruire caratteristiche dei record sottostanti. |
| **Deduzione dai totali** | Ricava un valore soppresso sottraendo dal totale i gruppi pubblicati. |
| **Confronto temporale** | Confronta risultati prima e dopo un inserimento o aggiornamento noto. |
| **Ricerca adattiva** | Sceglie ogni nuova interrogazione in funzione delle risposte precedenti. |
| **Media di risposte rumorose** | Se il rumore è aggiunto senza una gestione corretta delle ripetizioni, molte risposte possono ridurne l'effetto. |

Esempio teorico: una ricerca restituisce 100 pazienti; la stessa ricerca,
escludendo una persona identificabile, ne restituisce 99. Entrambi i conteggi
superano una soglia minima di 5, ma il confronto rivela l'appartenenza della persona.

Approvare ogni query isolatamente non risolve questa famiglia di rischi. Servono
controlli sulla composizione delle interrogazioni e, se richiesto dal modello di
protezione, un meccanismo di privacy differenziale con un budget definito.
Aggiungere rumore casuale senza una progettazione complessiva non basta.

## 4. Aggiramento del validatore

| Tipo | Come può aggirare controlli semplici |
|---|---|
| **Sottoquery e scope** | Nasconde una selezione o un identificatore dietro proiezioni e variabili rinominate. |
| **Rami `UNION` o `OPTIONAL`** | Inserisce una lettura non consentita accanto a un pattern apparentemente legittimo. |
| **Espressioni condizionali** | Fa dipendere un numero o un altro risultato da una condizione sensibile. |
| **Differenze tra parser e database** | Sfrutta costrutti interpretati diversamente dal controllore e da Virtuoso. |
| **Riscritture scorrette** | Una normalizzazione elimina o modifica parti della query cambiandone il significato. |
| **Confusione tra record e pazienti** | Fa superare la soglia contando eventi, duplicati o grafi dello stesso paziente. |
| **Contributi piccoli nascosti** | Un risultato coinvolge molti pazienti, ma una specifica colonna deriva da uno solo. |

Le difese comprendono una grammatica supportata esplicita, analisi dell'albero,
gestione degli scope e conteggio dei pazienti distinti per ciascun aggregato.
Dieci esami dello stesso paziente non equivalgono a dieci pazienti.
Anche il prefisso di un URI non dimostra da solo che un grafo rappresenti una
persona distinta: serve una mappatura affidabile.

## 5. Canali esterni e difetti dell'applicazione

| Tipo | Come può rivelare dati |
|---|---|
| **Federazione e rete** | `SERVICE` coinvolge endpoint esterni e richiede una policy di rete indipendente dai controlli sulle colonne. |
| **Accesso a grafi non autorizzati** | Una query sicura nella forma legge un dataset a cui l'utente non dovrebbe accedere. |
| **Errori, log e debug** | Mostrano valori che la risposta normale avrebbe soppresso. |
| **Canali laterali** | Tempi, presenza della risposta o comportamenti diversi dipendono da condizioni sensibili. |
| **Cache e isolamento utenti** | Una risposta autorizzata per un utente viene restituita impropriamente a un altro. |
| **Prompt injection** | Induce il modello a proporre query vietate o a usare strumenti impropriamente. |

Il modello non deve essere l'autorità che decide le autorizzazioni. Il codice
deve controllare qualunque query generata, usare credenziali limitate e impedire
accessi alternativi che aggirino il servizio. Risultati intermedi, report e log
devono restare su canali protetti.

## 6. Controlli complementari e limiti

| Controllo | Cosa affronta | Cosa non dimostra da solo |
|---|---|---|
| Operatori e forme ammessi | Riduce la superficie delle query | Che ogni uso di un operatore ammesso sia sicuro |
| Analisi di provenienza | Riconosce identificatori ed espressioni derivate | L'assenza di deduzioni tra query |
| Soglia per aggregato | Sopprime contributi di coorti piccole | Anonimato di gruppi omogenei o di query ripetute |
| Contratto sulla risposta | Blocca campi, tipi e valori inattesi | Che un valore numerico abbia una provenienza sicura |
| Autorizzazioni sui grafi | Limita i dati accessibili | L'anonimato delle risposte autorizzate |
| Controlli sulle interrogazioni ripetute | Affronta composizione e differenze | Una garanzia generale senza un modello formale |
| SHACL | Verifica requisiti dei dati RDF | La privacy delle query o dei risultati |

La [policy di adeguatezza SHACL](../policies/adequacy-shacl.md) e implementata con cinque
toggle `adequacy_*`. Valida i grafi RDF, non il testo della query o il risultato
numerico. E attiva in `adequacy` e `hardened`, disattiva in `default` e
`unrestricted`; richiede shape fidate tramite `ShaclContext`. Dati conformi
possono comunque consentire attacchi all'anonimato: i controlli privacy restano
necessari.

Una soglia di coorte è una scelta di policy, non una garanzia universale.
Una lista di operatori vietati non sostituisce una lista esplicita delle
strutture effettivamente supportate e controllate.

## 7. Stato del progetto e matrice di test

Le famiglie sopra sono una classificazione dei rischi, non un elenco esaustivo
di attacchi né una lista di tecniche tutte riconosciute dal codice. La copertura
va valutata per variante, percorso di esecuzione e configurazione effettiva.

| Profilo | Protezioni attive e limiti |
|---|---|
| `default` | Controlli statici, provenienza runtime e contratto numerico della risposta; le sette nuove opzioni `privacy_*` sono disattivate. Le dimostrazioni dei bypass storici rimangono riproducibili. |
| `adequacy` | Controlli predefiniti e validazione SHACL, con shape fidate. Verifica l'adeguatezza dei dati ai vincoli selezionati; non aggiunge le sette protezioni privacy. |
| `hardened` | Abilita tutti i controlli, comprese le opzioni privacy e SHACL. Richiede contesti fidati con ACL, identità canoniche, storico e shape. Le difese privacy bloccano i 17 scenari storici riprodotti; non garantisce copertura di ogni variante delle famiglie elencate. |
| `unrestricted` | Disattiva i controlli configurabili; non offre le protezioni di anonimato dell'analizzatore. Restano i limiti delle operazioni implementate dal motore. |

Il runtime supporta aggregazioni COUNT/SUM/AVG anche su più livelli e controlla
le coorti prima del rilascio finale. I gruppi individuali intermedi possono
essere ammessi: una sottoquery non viene rifiutata soltanto perché contiene
valori individuali.

| Famiglia | Copertura attuale con `hardened` | Limite residuo |
|---|---|---|
| Esposizione diretta, alias e aggregati che conservano valori | Regole statiche, provenienza e contratto finale; vari costrutti sono vietati o non supportati. | Il rifiuto di un costrutto non dimostra l'analisi semantica di ogni trasformazione equivalente. |
| Piccoli contributi nascosti in IF/COALESCE, OPTIONAL, UNION e riscalamenti | Controllo dei contributi effettivi e delle dipendenze dei singoli aggregati; 11 bypass complessi storici sono regressioni di blocco. | Non è una prova per ogni espressione equivalente; alcune query innocue vengono rifiutate conservativamente. |
| Duplicati della stessa persona | Soglia sulle persone canoniche, usando il mapping fidato. | La correttezza e la completezza del mapping competono al servizio. |
| Condizioni non correlate nel default graph | Rifiuto dei pattern non vuoti fuori da GRAPH. | È una restrizione conservativa, non un supporto generale dei join tra grafi clinici e default graph. |
| Differenze, piccoli complementi e intersezioni tra rilasci | Storico delle coorti e blocco di query diverse sulla stessa coorte. | Non copre ogni ricostruzione o inferenza adattiva; lo storico è in memoria del singolo processo. Non è implementata privacy differenziale con budget. |
| Confronti temporali | Snapshot fissato al primo rilascio; cambiamenti successivi bloccati. | Non gestisce una pubblicazione sicura di statistiche su dataset che evolve nel tempo. |
| Accessi fuori ACL | Verifica dell'intero Dataset locale prima della query. | ACL e Dataset già delimitato devono essere forniti dal servizio; non crea una vista autorizzata su Virtuoso. |
| Errori del backend | Normalizzazione delle eccezioni impreviste nel percorso verificato. | Non governa log interni, report di debug o altri canali applicativi. |
| Federazione | SERVICE vietato. | Non configura firewall, credenziali o altri strumenti con accesso alla rete. |
| Collegamento con fonti esterne e omogeneità del gruppo | Nessuna garanzia generale implementata. | Una coorte sopra soglia può comunque consentire deduzioni individuali. |
| Tempi di esecuzione e distinzione tra rilascio e soppressione | Nessuna protezione generale implementata. | Anche il comportamento di una richiesta bloccata può fornire informazioni. |
| Cache, isolamento utenti e prompt injection | La validazione limita alcune conseguenze delle query generate quando attraversano il gate. | Servono controlli nel servizio e negli strumenti dell'agente; il modulo non implementa queste difese applicative. |
| Dati incompleti o incoerenti rispetto alle shape | SHACL Core/SPARQL per grafo, con target effettivi, meta-schema e severita configurabili. | Non prova l'anonimato, la verita clinica o la copertura di ogni dato; manca l'integrazione con Virtuoso. |

La [matrice dei profili dei test](../../tests/README.md#profili-usati-nei-test)
distingue le verifiche del profilo predefinito dalle regressioni hardened:
6 scenari generali e 11 varianti complesse, senza `xfail`. Per queste ultime
`privacy_normalize_errors` è disattivata nel test, così un crash inatteso
non viene contato come blocco riuscito. Queste regressioni disattivano anche
`adequacy_shacl`, per isolare la privacy su fixture minimali non conformi SPHN.
I test SHACL e di hardened completo hanno fixture dedicate. Il totale dei
test comprende configurazioni diverse, non solo hardened.

Le protezioni runtime richiedono il passaggio da `execute_checked`: la sola
validazione statica non applica ACL, coorti o storico dei rilasci. `infra/virtuoso/scripts/query.sh`
interroga direttamente Virtuoso e non applica questi profili. Non è stata
verificata l'equivalenza del percorso locale RDFLib con l'esecuzione in Virtuoso.
Sul dataset da 50 GB i controlli di supporto dovranno operare nel database,
senza trasferire tutte le righe dei pazienti in Python.

Prerequisiti e limiti operativi sono descritti nella
[guida alle policy privacy](../policies/privacy.md). I test disponibili non
costituiscono una certificazione di privacy.

Per trasformare questa classificazione in un piano di verifica, registrare per
ogni famiglia:

- controllo previsto e punto in cui viene applicato;
- query consentite di riferimento e query da bloccare;
- risultato atteso e motivazione;
- dipendenze da dataset, identità utente e storia delle interrogazioni;
- stato di copertura e limite residuo.

Mantenere distinti i casi di violazione riconosciuta, i casi non supportati e gli
errori di esecuzione. Nessuno degli ultimi due deve diventare un'approvazione.

## Riferimenti

- [NIST SP 800-226 — Guidelines for Evaluating Differential Privacy Guarantees](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-226.pdf): rischi di collegamento, ricostruzione e garanzie di privacy.
- [W3C — SPARQL 1.1 Federated Query](https://www.w3.org/TR/sparql11-federated-query/): federazione tramite SERVICE e considerazioni di sicurezza.
- [OWASP — LLM Prompt Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html): rischi del livello LLM e controlli applicativi.
- [Non compliance e SHACL](compliance-and-shacl.md): distinzione tra qualità dei dati, semantica delle query e privacy.
- [Implementazione e limiti](../guides/sparql.md).
