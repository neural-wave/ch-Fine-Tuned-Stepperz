# Dataset di sistema NL-to-SPARQL

Questo generatore conserva il primo smoke test sintetico. Per il corpus
principale basato sulle query gia esistenti e i test separati dei componenti,
usare la [guida al workflow](guides/agent-workflow.md).

Generazione riproducibile, senza modelli o accessi a dati reali:

```powershell
uv run python -m tools.generate_system_dataset
uv run pytest tests/test_system_dataset.py
```

Output: `artifacts/system-dataset/cases.jsonl`, `manifest.json` e tre fixture
RDF TriG da 12, 18 e 27 pazienti sintetici (seed 42, 7, 91).
Gli artefatti sono ignorati da Git; il generatore resta versionato.

Ogni riga contiene prompt, query oracolo se definita, risultato oracolo SPARQL
Results JSON, conteggio atteso derivato dalla costruzione della fixture,
query candidata, provenienza, etichette attese e risultati osservati.
La query oracolo viene eseguita e confrontata con il conteggio indipendente.
L'esito di sicurezza viene verificato tramite `execute_checked`.

I 24 casi coprono riferimento, parafrasi, rinomina di variabili interne,
IRI espliciti, DISTINCT mancante, classe errata, coorte piccola,
molti eventi di una sola persona ed estrazione di identificatori
(alcune varianti condividono lo stesso scenario di generazione).
Le query candidate sono scritte a mano: non sono output di un LLM.
Per valutare un generatore reale occorre registrare separatamente la sua query,
modello/versione/configurazione e confrontarla con l'oracolo sullo stesso snapshot.

`expected_result_match` riguarda i risultati; `expected_security_outcome`
riguarda il rilascio. Una coorte piccola può avere risultati corretti ma essere
bloccata. Una query che conta diagnosi anziché persone può essere rilasciata
e rimanere semanticamente errata. Una richiesta malevola non ha necessariamente
una query oracolo autorizzata: in quel caso l'oracolo è nullo.

Il confronto ignora l'ordine di righe e colonne, conserva duplicati e tipi RDF,
richiede gli stessi nomi delle colonne e rifiuta risultati con blank node.
Non supporta confronti ordinati, alias di output, tolleranze numeriche o grafi
CONSTRUCT/DESCRIBE. Corrispondenza su fixture non significa equivalenza logica
universale. Le fixture differenti riducono le coincidenze senza eliminarle.

Train/validation/test sono separati per fixture, ma ripetono i template:
non vanno usati per dichiarare generalizzazione a nuove famiglie di attacco.
Questa è una base end-to-end, non copertura completa della sicurezza.
Federazione, aggiornamenti, costi di query, attacchi multi-turn e policy
dipendenti dall'identità richiedono ulteriori scenari e un ambiente isolato.

Il generatore esegue direttamente soltanto query SELECT costanti del proprio
codice su dati sintetici. Non adattare questa esecuzione diretta a query LLM
non fidate: usarle soltanto con controlli, permessi e limiti appropriati.
