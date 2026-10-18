# Prompt di validazione

[prompts.json](prompts.json) contiene 178 richieste con etichetta binaria:
88 consentite e 90 vietate. Il preset le unisce ai benchmark gia presenti.
Gli ultimi 160 casi formano 40 famiglie: ogni famiglia ha due varianti consentite
e due vietate, in due lingue. 38 famiglie sono in inglese/italiano e due in
francese/tedesco. Le coppie rendono visibili falsi positivi e falsi negativi
su testi simili, senza affidarsi soltanto a parole come "identifier" o "DELETE".

| Area | Esempi di confronto |
|---|---|
| Aggregati clinici | Conteggi, medie, percentuali, join, esistenza, categorie e serie temporali contro output individuali |
| Identificabilita | Grafi di singoli pazienti, pseudonimi, hash, combinazioni di quasi-identificatori, collegamenti pubblici |
| Canali di divulgazione | GROUP_CONCAT, valori numerici codificati, membership bit, paginazione con LIMIT/OFFSET |
| Protezioni delle coorti | Soppressione rispettata contro soglie indebolite, singleton e differencing esplicito |
| Istruzioni non fidate | Ruoli amministrativi dichiarati, falsi messaggi di sistema, JSON e documenti recuperati |
| Robustezza del testo | Negazioni, attacchi citati ma non richiesti, refusi, Unicode confondibile e richieste lunghe |
| Pretesti | Debug, assistenza, urgenza e simulazioni usati per chiedere dati individuali |
| Operazioni | SPARQL nel prompt, aggiornamenti e federazione esterna contro statistiche locali autorizzate |

`malicious` indica che il comportamento richiesto viola la policy testuale
aggregate-only dell'analista dimostrativo. Non descrive l'intenzione psicologica
dell'autore. `label_reason` spiega il contrasto della famiglia. Le etichette sono
manuali, da rivedere prima di usarle come benchmark indipendente.

Una richiesta aggregata lecita puo usare una struttura non supportata dal checker.
Questo non cambia la sua etichetta: serve a distinguere la qualita del controllo
del prompt dai limiti della generazione e dell'analisi statica. Le richieste
benigne soggette a soglie presuppongono i controlli di rilascio al runtime;
una query generata non prova da sola l'anonimizzazione.

I metadati e le etichette sono solo per la valutazione: all'API arriva il testo
del prompt. Non aggiungere questi casi al retrieval MCP o al training. Tenere
insieme tutte le varianti dello stesso `group` in eventuali split; le traduzioni
e le parafrasi non sono osservazioni indipendenti. Questa suite non simula una
cronologia di attacchi distribuiti su piu richieste o misura la sicurezza runtime.

Comandi, metriche e log nella [guida di validazione](../README.md).
