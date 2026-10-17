# VoID strutturale per sparql-llm

[`sphn-schema-void.ttl`](sphn-schema-void.ttl) fornisce al caricatore `sparql-llm`
una mappa delle classi, proprieta e tipi dichiarati negli
[schemi sorgenti](../README.md). Deriva soltanto da
[`shacler_shapes.ttl`](../shacl/shacler_shapes.ttl) e
[`sphn_rdf_schema.ttl`](../sphn/sphn_rdf_schema.ttl), senza interrogare il database
o leggere i file paziente.

## Utilizzo

Il MCP SPHN distingue le classi/datatype di range dai valori fissi: per esempio
`hasCode` con range ICD descrive il tipo del nodo codice, non richiede come
oggetto l'IRI della classe ICD stessa. Le risposte includono
`declared_value_types` e una nota di interpretazione. La rappresentazione
ShEx-like dei tipi usa shape degli oggetti e datatype, conservando i value set
per il solo `rdf:type`. Non sostituisce lo SHACL completo o un lookup terminologico.

Il preset principale usa questo VoID nel server SPHN di `LLM_ENGINE`, avviato
da `bash start-mcp.sh` e collegato tramite `mcp_url` in `models.json`.
Per il precedente backend stdio, la configurazione opzionale
[`sparql-mcp.json`](../../config/agents/sparql-mcp.json) usa:

```json
"void_file": "schemas/void/sphn-schema-void.ttl",
"examples_file": "schemas/void/query-examples.ttl"
```

I percorsi sono relativi alla radice del repository per l'avvio previsto dal
progetto. Adattare `endpoint_url` al triplestore reale. Il file evita il profiling
VoID del database per caricare questa struttura; il server puo comunque
contattare l'endpoint per altre informazioni.

[`query-examples.ttl`](query-examples.ttl) aggiunge prefissi e un esempio di
conteggio per il recupero documentale. L'esempio coincide con il gruppo
`00_compliant`: la valutazione con modelli reali esclude questo gruppo per non
valutare una query gia fornita al modello. Per l'avvio MCP e i modelli vedere la
[guida locale](../../docs/guides/local-models.md).

## Origine e verifica

La conversione e stata eseguita con SPARQL `CONSTRUCT` e RDF4J/Java incluso nel
JAR ufficiale void-generator 0.19. [`shacl-to-void.rq`](shacl-to-void.rq) conserva
la query; [`verification.json`](verification.json) riporta hash e controlli:

| Contenuto | Quantita |
| --- | ---: |
| Classi target | 208 |
| Associazioni classe-proprieta | 980 |
| Collegamenti a classi o datatype | 1.451 |
| Classi referenziate complessive | 630 |
| Triple RDF | 5.488 |
| Property shape con percorsi complessi non appiattiti | 95 |

Il Turtle e stato ricaricato con RDF4J; la mappa estratta con la query
`sparql_llm.utils.GET_VOID_DESC` coincide con quella del sottoinsieme di schemi
convertito. Questi controlli non attestano l'indicizzazione del server MCP
upstream, da provare sull'istanza.

## Limiti

La conversione estrae `sh:targetClass`, proprieta con `sh:path` IRI, `sh:class`,
`sh:datatype`, alternative `sh:or`, riferimenti `sh:node` con `sh:targetClass`,
label e commenti. Non esegue ragionamento OWL o validazione SHACL.

I percorsi complessi, le cardinalita, i vincoli SPARQL e le combinazioni logiche
complete restano nello SHACL originale. Il VoID e una proiezione strutturale:
una relazione dichiarata non implica che esista nei dati. Non contiene
statistiche osservate o inventate (`void:triples`, `void:entities`,
`void:distinctSubjects`, `void:distinctObjects`).
