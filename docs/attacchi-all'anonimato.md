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

Una soglia di coorte è una scelta di policy, non una garanzia universale.
Una lista di operatori vietati non sostituisce una lista esplicita delle
strutture effettivamente supportate e controllate.

## 7. Stato del progetto e matrice di test

La [suite avversaria avanzata](../tests/adversarial/README.md) associa le famiglie
elencate a query separate, test runtime, dimostrazioni di rischio e verifiche di
integrazione mancanti. Sei lacune sono riprodotte con test xfail strict: non
vengono contate come protezioni riuscite.

Il prototipo contiene controlli statici su alcune esposizioni dirette e una
verifica runtime locale per COUNT globali diretti, con controllo delle colonne,
dei tipi, dei conteggi e della coorte per valore.

Non è stata dimostrata copertura completa delle deduzioni tra query, dei canali
laterali o dell'integrazione con Virtuoso. I test disponibili non costituiscono
una certificazione di privacy. Sul dataset da 50 GB i controlli di supporto
dovranno operare nel database, senza trasferire tutte le righe dei pazienti in Python.

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
- [Non compliance e SHACL](non-compliance-e-shacl.md): distinzione tra qualità dei dati, semantica delle query e privacy.
- [Implementazione e limiti](sparql.md).
