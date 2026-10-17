# Revisione della query per sesso del 17 ottobre 2026

Il log fornito dall'utente riguarda una richiesta sul colera nelle diagnosi
fatturate, per sesso e senza restrizioni sul rango diagnostico. Il classificatore
ha consentito il prompt. L'analisi della query ha restituito `unsupported`, senza
violazioni R1-R5, per il controllo `category_group`. Il workflow ha quindi
restituito `blocked_query` senza eseguire query sui dati.

La query esatta e conservata come
[fixture di regressione](../../tests/fixtures/regressions/billed-diagnosis-by-sex.rq).

## Cosa limita il controllore

Una statistica aggregata per categoria puo essere una richiesta lecita.
Il prototipo attuale non ne verifica pero il rilascio: il percorso piatto
richiede un aggregato globale con provenienza dai grafi paziente e il contratto
di risposta predefinito richiede una sola riga numerica. `?sex` e invece una
categoria e `GROUP BY ?sex` produce potenzialmente piu righe.

Disabilitare soltanto `category_group` fa passare questa analisi statica ma
il runtime continua a rifiutare la struttura. I test riproducono entrambi i
passaggi. Supportare le categorie richiede almeno verifica delle etichette,
provenienza e soglia minima per ogni gruppo, gestione di gruppi piccoli e un
contratto di risposta coerente. I controlli non sono stati allentati.

Il log ora segnala esplicitamente che `unsupported` e una limitazione del
motore, non la conferma di una violazione o di un intento malevolo.

## La query generata non e equivalente al prompt

- Non esiste una condizione che identifichi il colera. L'IRI ICD-10-GM nella
  query e quello della classe di codifica, non un codice verificato di malattia.
- Il predicato `hasRankCode` viene fissato a un valore, mentre era richiesto
  qualsiasi rango.
- `sphn:hasSex` non e dichiarato nello schema SPHN fornito. Lo schema descrive
  `AdministrativeSex`, collegato al paziente da `hasSubjectPseudoIdentifier`,
  e il relativo `hasCode`.
- Mancano i pattern `GRAPH ?g` che il runtime usa per la provenienza paziente.

Inoltre, la fixture sintetica usata nel comando non contiene codici diagnostici
o amministrativi del sesso: non fornisce un oracolo per questa domanda.
Il controllo statico di sicurezza non e un verificatore generale di equivalenza
tra prompt e query. Rendere una query eseguibile non ne prova il significato.

## Correzioni applicate

Il workflow possiede il riepilogo dei log a `INFO`; quando viene chiamato da un
workflow, l'adapter emette i propri dettagli a `DEBUG`. Da solo, l'adapter mantiene
il riepilogo a `INFO`. La query non viene quindi duplicata nel normale log.

Il MCP mostrava le classi di range VoID tra parentesi quadre come se fossero
valori fissi. Ora le mostra come tipi degli oggetti, espone anche
`declared_value_types` e chiarisce che i tipi non sono codici della terminologia.
La distinzione tra value set e shape dell'oggetto e descritta nel
[primer ShEx](https://shexspec.github.io/primer/).

Le istruzioni del generatore richiedono inoltre di mantenere condizioni e
quantificatori del prompt, usare predicati verificati e grafi paziente, e non
sostituire un codice clinico con l'IRI di un sistema di codifica. Sono indicazioni
al modello, non una prova di correttezza delle sue future risposte.

Le correzioni sono verificate offline. Dopo l'aggiornamento sulla VM, riavviare
il processo MCP per caricare i nuovi metadati prima di riprovare il modello.
