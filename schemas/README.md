# Schemi e metadati

Questa cartella contiene schemi RDF e metadati per il generatore SPARQL.

| Percorso | Ruolo |
| --- | --- |
| [`sphn/sphn_rdf_schema.ttl`](sphn/sphn_rdf_schema.ttl) | Ontologia SPHN: classi, proprieta, label e gerarchie. |
| [`shacl/shacler_shapes.ttl`](shacl/shacler_shapes.ttl) | Shape SHACL: percorsi, tipi, cardinalita e vincoli sui dati. |
| [`void/`](void/README.md) | Profilo strutturale derivato ed esempi usati dal server MCP `sparql-llm`. |

Lo SHACL conserva i vincoli completi; il VoID ne espone soltanto una parte per
aiutare il modello a costruire query. Leggere questi file come contesto non
equivale a validare i dati o a garantire l'anonimizzazione dei risultati.
L'integrazione della validazione SHACL e descritta nella
[guida all'adeguatezza](../docs/policies/adequacy-shacl.md).

Per collegare i metadati ai modelli seguire la
[guida ai modelli locali](../docs/guides/local-models.md). Per l'inferenza RDFS
di Virtuoso, il loader usa invece [`ontologies/`](../ontologies/), come spiegato
nel [manuale del triplestore](../infra/virtuoso/README.md).
