# Suite avversaria

Tutti i dati sono fittizi. Le destinazioni esterne usano example.invalid.
Le query con SERVICE, update e dialetto Virtuoso sono analizzate, mai eseguite.
I file .rq sono separati in queries/; cases.json descrive 45 casi singoli e
scenarios.json descrive 10 scenari sequenziali, di dataset o di integrazione.

## Esecuzione

```powershell
uv run pytest tests/privacy/test_adversarial.py tests/privacy/test_adversarial_sequences.py tests/privacy/test_adversarial_payloads.py -v
uv run python -m tools.export_adversarial
```

L'export generale `uv run python -m tools.export_test_results` include ora questi casi.
Alberi e verdetti dei casi singoli sono in artifacts/tests/adversarial/<id>/;
report.json riassume gli esiti. Per property path o dialetti non supportati
un'algebra puo non essere disponibile: il blocco non prova supporto semantico.

## Come leggere gli esiti

- test_adversarial.py: 45 casi, di cui 37 bloccati staticamente, 3 al runtime e
  5 controlli positivi. Verifica la sintassi standard prima del verdetto, cosi
  un refuso non diventa una prova di blocco. Per i dialetti il rifiuto del parser
  e esplicitamente atteso. Un database sentinella verifica che le query bloccate
  staticamente non vengano eseguite.
- test_adversarial_payloads.py: 12 risposte del backend alterate, intercettate
  nell'intero flusso execute_checked, non solo chiamando il controllo di formato.
- test_adversarial_sequences.py: 6 requisiti ancora violati marcati xfail strict
  e 4 dimostrazioni di rischi osservati. Le dimostrazioni passano quando riproducono
  il rischio: non significano che il sistema lo prevenga.

Gli xfail vengono eseguiti e falliscono nella condizione attesa. Non sono skip
e non sono test superati. strict fa fallire la suite se un requisito viene
soddisfatto senza aggiornare la classificazione. Per vedere i fallimenti reali:

```powershell
uv run pytest -m security_gap --runxfail -v
```

Questo comando deve attualmente terminare con 6 fallimenti.
I marker sono registrati in pyproject.toml. Il codice di produzione non e stato
reso piu permissivo o modificato per ottenere test verdi.

## Lacune riprodotte

| ID | Lacuna | Dimostrazione |
|---|---|---|
| GAP-01 | Nessuna gestione dello storico | 8 e 7 su coorti che differiscono per una persona sono entrambi restituiti |
| GAP-02 | Confronto temporale | Stessa query prima e dopo una modifica nota: 8 e 7 |
| GAP-03 | Mappatura grafo/paziente non verificata | Cinque grafi contenenti record della stessa persona superano k=5 |
| GAP-04 | Nessuna autorizzazione per utente | Un grafo con prefisso corretto appartenente a un altro tenant viene incluso |
| GAP-05 | Provenienza non correlata | Una condizione nel default graph puo controllare il risultato di una coorte non correlata |
| GAP-06 | Errori backend non normalizzati | Un'eccezione sintetica con valore privato non viene convertita in ResultBlocked |

GAP-02 riguarda osservazioni tra esecuzioni, non prova una race durante una
singola verifica. GAP-04 esprime un requisito di integrazione mancante: oggi
execute_checked non riceve alcuna identita o ACL. GAP-06 riproduce un'eccezione
del backend con monkeypatch, non un errore reale di Virtuoso.

## Matrice delle famiglie di attacco

| Famiglia | Casi / test | Tipo di verifica e limiti |
|---|---|---|
| Estrazione diretta | a01, a34 | Blocco prima del database |
| Alias e trasformazioni | a02, a19, a20 | Propagazione oppure rifiuto della struttura |
| Aggregazioni che conservano valori | a03-a06 | GROUP_CONCAT/SAMPLE/MIN/MAX bloccati |
| Hash e codifiche | a07, a08, a29 | SHA256/ENCODE_FOR_URI ed escape IRI |
| Frammenti ricomponibili | a09, a10 | Entrambi i frammenti sono bloccati |
| Esportazione di grafi | a11, a12 | CONSTRUCT/DESCRIBE bloccati |
| Paginazione | a13, a14 | Due pagine di identificatori entrambe bloccate |
| Selezione esplicita individuale | a15-a17, a28 | VALUES, BIND, CONCAT, BASE |
| Quasi-identificatori | s02 e sequenze | Valori clinici distintivi fittizi; GAP-01 |
| Gruppi individuali | a18 | Alias del grafo usato come categoria |
| Gruppi rari | r01 | Un solo paziente, soppressione runtime |
| Collegamento con fonti esterne | Ricostruzione s07 | Conoscenza esterna simulata persona-valore; non usa fonti reali |
| Omogeneita | test_homogeneity_is_not_hidden_by_threshold | Dimostrazione di rischio, non una difesa |
| Appartenenza | Ricostruzione s07 | Ricava il vettore di appartenenza di 12 persone fittizie |
| Differenze tra conteggi | GAP-01 | Seconda risposta ancora restituita |
| Intersezione di coorti | s01, s02, s05 | Risposte sovrapposte 8,7,7: nessuna policy dello storico |
| Ricostruzione da statistiche | s01, s07 per 12 persone | Ricostruisce 8 appartenenze positive con conteggi tutti sopra soglia |
| Deduzione dai totali | test_suppressed_complement_is_recoverable | Il gruppo di 1 e soppresso ma si ricava da 8-7 |
| Confronto temporale | GAP-02 | Dataset modificato tra due richieste |
| Ricerca adattiva | Sequenze di esclusione | Una famiglia di sonde e riprodotta; nessuna protezione generale dimostrata |
| Media di risposte rumorose | Non applicabile al runtime attuale | Nessun meccanismo di rumore/budget implementato; richiede futuri test statistici |
| Sottoquery e scope | a19, a20, a23 | Blocco di proiezioni annidate ed EXISTS |
| Rami UNION/OPTIONAL | a21, a22, r03 | Rami liberi e colonna con coorte piccola |
| Segnali condizionali | a23, a24, a33, r04, r05, GAP-05 | Espressioni bloccate; condizione non correlata riprodotta come lacuna |
| Differenze parser/database | a35, a36 | Solo rifiuto del dialetto; equivalenza con Virtuoso ancora da verificare |
| Riscritture scorrette | a28, a29, controlli p01-p04 | Normalizzazioni limitate; nessun test differenziale Virtuoso |
| Record scambiati per pazienti | r02, GAP-03 | Dieci esami bloccati; duplicazione dei grafi ancora problematica |
| Contributi piccoli nascosti | r03 | Verifica distinta della colonna OPTIONAL |
| Federazione e rete | a25-a27 | Blocco statico; non verifica firewall o SSRF del deployment |
| Grafi non autorizzati | GAP-04, test_foreign_graph_blocked preesistente | Prefisso estraneo bloccato; ACL per utente assente |
| Errori/log/debug | GAP-06 e payload head_link/debug | Eccezioni e metadati; log reali ancora da verificare |
| Canali laterali | Verifica di integrazione da fare | Non si deduce protezione temporale da test unitari su valori |
| Cache/isolamento utenti | Verifica di integrazione da fare | Nessuna cache autenticata presente nel prototipo |
| Prompt injection | Verifica di integrazione da fare | Nessun generatore LLM eseguito: rifiutare SPARQL non dimostra resistenza del modello |

## Verifiche di integrazione ancora necessarie

1. Endpoint: identita distinte, ACL sui grafi, cache separata per utente e policy.
   Atteso: dati di un tenant mai restituiti a un altro, neppure da cache.
2. Rete: policy che impedisce richieste non autorizzate anche se il database
   riceve query per errore. Le prove unitarie non inviano traffico esterno.
3. Parser/Virtuoso: confronto sul dialetto supportato, con sola lettura su fixture
   isolate. Nessuna eliminazione silenziosa di DEFINE o OPTION(inference).
4. Snapshot: modifiche concorrenti durante verifica della coorte e risposta,
   per assicurare che venga usato lo stesso snapshot.
5. Tempi/errori/log: verificare che le risposte pubbliche e i canali operativi
   non espongano record e che i timeout non diventino un oracolo di presenza.
6. LLM: prompt diretti e contenuti indiretti fittizi; qualunque query generata
   deve attraversare gli stessi controlli, senza endpoint alternativi.
7. Eventuale privacy differenziale: composizione del budget, contributo massimo
   per paziente e comportamento delle ripetizioni; non basta verificare che i
   numeri cambino tra chiamate.

Le fixture aggiunte per le sonde sono esempi strutturali di privacy, non dati
clinici validati SHACL. Le valutazioni non costituiscono una prova di anonimato.

## Aggiornamento della policy v3

COUNT con espressioni su identificatori e rifiutato gia staticamente (r04).
L'aritmetica su aggregati verificati e consentita (r05, valore atteso 1008).
SUM/AVG di misure autorizzate sono disponibili; la query s06 e quindi approvabile.
Le sei lacune riprodotte e le quattro dimostrazioni di rischio restano valide.
