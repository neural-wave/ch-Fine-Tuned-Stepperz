# Policy di adeguatezza dei dati con SHACL

La policy verifica che i grafi RDF rispettino le shape scelte dal servizio:
proprieta richieste, cardinalita, datatype, classi delle risorse collegate e
vincoli SHACL-SPARQL, inclusi i target SPARQL delle shape SPHN. Usa pySHACL
0.25.0 con RDFLib 7.1.4, come fissato nelle dipendenze del progetto.
Le shape SPHN del repository sono in [shacler_shapes.ttl](../../schemas/shacl/shacler_shapes.ttl).

Adeguatezza qui significa conformita ai vincoli selezionati. Non dimostra
veridicita dei dati, correttezza clinica della domanda, compatibilita di ogni
unita di misura o anonimato della risposta. Le shape sono aperte: non sono
una whitelist completa dei predicati ammessi nelle query.

## Profili e interruttori

| Profilo | Adeguatezza SHACL |
|---|---|
| `default` | Disattivata, per compatibilita con l'API e le fixture precedenti. |
| `adequacy` / `Policy.adequacy()` | Tutte le opzioni SHACL attive, insieme ai controlli predefiniti; non richiede il contesto privacy. |
| `hardened` / `Policy.hardened()` | Tutte le opzioni SHACL e privacy attive; richiede entrambi i contesti fidati. |
| `unrestricted` | Disattivata. |

| Interruttore | Effetto |
|---|---|
| `adequacy_shacl` | Esegue il motore e blocca le violazioni. Senza `ShaclContext` blocca la richiesta. |
| `adequacy_targets` | Richiede almeno un focus node effettivo appartenente ai dati originali di ogni grafo non vuoto; ignora le shape disattivate. |
| `adequacy_meta_shapes` | Valida le shape con il meta-schema SHACL incluso nel motore. |
| `adequacy_warnings` | Rende bloccanti i risultati con severity `sh:Warning`. |
| `adequacy_infos` | Rende bloccanti i risultati con severity `sh:Info`. |

Gli ultimi quattro controlli dipendono da `adequacy_shacl`. Disattivare il
controllo principale li disattiva tutti. Attivarlo da solo esegue la validazione
di base: per ottenere tutte le opzioni usa il profilo `adequacy` o `hardened`.
Disattivare Warning/Info e una scelta operativa: non significa che i dati siano
conformi senza rilievi secondo lo standard. Le violazioni rimangono bloccanti.

```python
from sparql_analyzer import Policy, ShaclContext
from sparql_analyzer.runtime import execute_checked

# Percorsi locali e configurazione scelti dal servizio, non dal modello/client.
shacl = ShaclContext.from_files(
    "schemas/shacl/shacler_shapes.ttl",
    # ontology_path="schemas/sphn/sphn_rdf_schema.ttl",  # ontologia locale fidata
    inference="rdfs",
)
policy = Policy.adequacy()
result = execute_checked(dataset, query, policy=policy, shacl_context=shacl)

# Esempio: consentire soltanto i rilievi Info.
policy = policy.with_checks(adequacy_infos=False)

# Con tutte le protezioni privacy:
result = execute_checked(
    authorized_dataset, query, policy=Policy.hardened(),
    context=trusted_execution_context, shacl_context=shacl,
)
```

La configurazione JSON e in [config/policies/adequacy.json](../../config/policies/adequacy.json).
Il formato `checks` e i toggle CLI sono quelli delle altre policy. La CLI del
validatore statico non esegue SHACL: questo controllo richiede i dati RDF e
viene applicato da `execute_checked`, anche se `support_analysis` e disattivata.
`validate_adequacy(dataset, shacl, policy=Policy.adequacy())` permette inoltre
di verificare i dati senza eseguire una query; solleva `ResultBlocked` in caso
di rifiuto. Il suo esito vale per i dati osservati in quella chiamata: non e
un certificato riutilizzabile su uno snapshot successivo.

## Perimetro e ordine dei controlli

1. L'ACL privacy, quando attiva, viene controllata prima di leggere i dati per SHACL.
2. Il runtime calcola il fingerprint del Dataset prima della validazione.
3. Le shape e l'eventuale ontologia vengono ricostruite da copie immutabili
   conservate in `ShaclContext`; la configurazione e separata dalla query.
4. Ogni grafo non vuoto, incluso il default graph, viene validato separatamente.
   Non viene creata un'unione implicita tra grafi paziente. Le risorse di
   riferimento necessarie devono essere presenti nel perimetro di validazione
   o nell'ontologia fidata, secondo la semantica del motore.
5. Inferenza RDFS, se richiesta, opera su copie: non modifica il Dataset e
   non abilita automaticamente l'inferenza nella query utente. Un regime
   `sh:entailment` diverso da RDFS o incompatibile con la configurazione e rifiutato.
6. Dopo SHACL, la query attraversa i controlli statici e runtime previsti.
7. Il fingerprint viene ricontrollato prima del rilascio e della registrazione
   nello storico. Una modifica osservata sopprime il risultato anche senza storico.

Un motore in errore, un report inatteso, dati vuoti o target mancanti non
diventano una validazione riuscita. L'obbligo sui target e configurabile;
le eccezioni del motore restano sempre errori. Report completi, focus node,
valori e messaggi delle shape non sono inclusi nel payload SPARQL o negli
errori pubblici di questo modulo. I log del resto dell'applicazione richiedono
comunque una gestione separata.

## Limiti e verifiche

Il controllo dei target evita un'approvazione completamente vacua per grafo;
non dimostra che ogni risorsa o proprieta sia coperta da una shape. La scelta
e la copertura clinica delle shape restano responsabilita del servizio.
Sono supportati SHACL Core, SHACL-SPARQL e i target diretti `sh:SPARQLTarget`.
Regole, JavaScript, funzioni e altre funzionalita avanzate riconosciute dal
contesto vengono rifiutate; non si abilita un motore generico SHACL-AF.
Shape e ontologie sono fidate; i loro
vincoli SPARQL non sono query utente da filtrare con le regole privacy.
Non vengono caricati automaticamente import OWL o ontologie da URL.

La validazione viene rifatta sui dati a ogni richiesta abilitata, senza cache
di conformita. Sul file SPHN completo puo essere costosa. I fingerprint prima
e dopo non sostituiscono un isolamento transazionale: non rilevano una modifica
intermedia poi annullata. L'integrazione con snapshot Virtuoso e la validazione
all'ingestione con attestazioni persistenti restano da implementare. `infra/virtuoso/scripts/query.sh`
non applica questa policy.

[test_adequacy.py](../../tests/adequacy/test_adequacy.py) verifica casi validi, violazioni
singole, SHACL-SPARQL, separazione dei grafi, target mancanti, severita,
meta-schema, RDFS su copie, errori, modifiche durante la query e integrazione
con il profilo hardened completo. Usa [shape di test esplicite](../../tests/fixtures/shacl/shapes.ttl)
e una fixture dedicata; non rende piu permissive le shape SPHN ufficiali.
Un test separato carica il file SPHN completo e verifica un'istanza Algorithm
valida e una con datatype errato, selezionate tramite target SPARQL. Il meta-schema
del file completo viene verificato nel caso valido; il caso invalido riusa le
stesse shape immutabili con quel solo controllo disattivato. Non e una
validazione dell'intero dataset clinico.

Riferimento: [W3C SHACL, validazione e report](https://www.w3.org/TR/shacl/#validation).
