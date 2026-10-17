# Catalogo dei controlli

Generato dal registro `sparql_analyzer/policy.py`. Privacy e adeguatezza SHACL sono opt-in nel profilo predefinito e attive nel profilo hardened. Il profilo adequacy abilita i controlli SHACL senza le opzioni privacy.

| Interruttore | Effetto | Richiede | Default |
|---|---|---|---|
| `syntax_analysis` | Analisi dell'AST sintattico; il parsing rimane necessario. |  | true |
| `algebra_analysis` | Analisi dell'algebra SPARQL. |  | true |
| `scope_analysis` | Isolamento delle variabili locali delle sottoquery. |  | true |
| `sensitivity_analysis` | Propagazione della sensibilita attraverso alias e aggregati. | `algebra_analysis`, `scope_analysis` | true |
| `numeric_analysis` | Classificazione delle misure e delle espressioni numeriche. | `algebra_analysis`, `scope_analysis` | true |
| `aggregate_analysis` | Propagazione delle dipendenze da aggregati. | `algebra_analysis`, `scope_analysis` | true |
| `support_analysis` | Valutazione delle righe di supporto e provenienza. | `algebra_analysis`, `scope_analysis` | true |
| `control_analysis` | Provenienza delle condizioni nel percorso annidato. | `support_analysis` | true |
| `query_length` | Lunghezza massima della query. |  | true |
| `select_only` | Ammette soltanto SELECT. | `algebra_analysis` | true |
| `known_nodes` | Rifiuta operatori dell'algebra non verificati. | `algebra_analysis` | true |
| `fixed_graph` | Rifiuta grafi costanti non autorizzati. | `algebra_analysis` | true |
| `patient_reference` | Rifiuta URI espliciti nel namespace pazienti. | `algebra_analysis` | true |
| `clinical_pattern` | Richiede almeno un pattern clinico. | `algebra_analysis` | true |
| `unrestricted_triple` | Rifiuta triple con tre variabili. | `algebra_analysis` | true |
| `fixed_subject` | Rifiuta soggetti URI costanti. | `algebra_analysis` | true |
| `constant_identifier` | Rifiuta identificatori costanti. | `algebra_analysis` | true |
| `predicate_shape` | Rifiuta predicati variabili e property path. | `algebra_analysis` | true |
| `predicate_vocabulary` | Limita il vocabolario dei predicati. | `algebra_analysis` | true |
| `values` | Rifiuta VALUES non verificati. | `algebra_analysis` | true |
| `category_group` | Rifiuta raggruppamenti esterni per categoria. | `sensitivity_analysis` | true |
| `supported_aggregates` | Limita gli aggregati staticamente verificati. | `algebra_analysis` | true |
| `sensitive_filter` | Rifiuta filtri su risorse e identificatori individuali. | `sensitivity_analysis` | true |
| `sensitive_bind` | Rifiuta costanti assegnate a variabili sensibili. | `sensitivity_analysis` | true |
| `individual_group` | Rifiuta raggruppamenti individuali nell'output esterno. | `sensitivity_analysis` | true |
| `sensitive_count` | Rifiuta espressioni COUNT dipendenti da identificatori. | `sensitivity_analysis` | true |
| `sensitive_output` | Rifiuta risorse e identificatori nell'output. | `sensitivity_analysis` | true |
| `numeric_aggregates` | SUM/AVG soltanto su misure autorizzate. | `numeric_analysis` | true |
| `aggregate_output` | Output composto esclusivamente da aggregati. | `aggregate_analysis` | true |
| `forbid_group_concat` | Vieta esplicitamente GROUP_CONCAT. | `syntax_analysis` | true |
| `forbid_sample` | Vieta esplicitamente SAMPLE. | `syntax_analysis` | true |
| `forbid_min` | Vieta esplicitamente MIN. | `syntax_analysis` | true |
| `forbid_max` | Vieta esplicitamente MAX. | `syntax_analysis` | true |
| `forbid_service` | Vieta esplicitamente SERVICE. | `syntax_analysis` | true |
| `forbid_ask` | Vieta esplicitamente ASK. | `syntax_analysis` | true |
| `forbid_construct` | Vieta esplicitamente CONSTRUCT. | `syntax_analysis` | true |
| `forbid_describe` | Vieta esplicitamente DESCRIBE. | `syntax_analysis` | true |
| `forbid_from` | Vieta esplicitamente FROM. | `syntax_analysis` | true |
| `forbid_from_named` | Vieta esplicitamente FROM NAMED. | `syntax_analysis` | true |
| `forbid_sparql_update` | Vieta esplicitamente SPARQL UPDATE. | `syntax_analysis` | true |
| `forbid_load` | Vieta esplicitamente LOAD. | `syntax_analysis` | true |
| `forbid_clear` | Vieta esplicitamente CLEAR. | `syntax_analysis` | true |
| `forbid_drop` | Vieta esplicitamente DROP. | `syntax_analysis` | true |
| `forbid_create` | Vieta esplicitamente CREATE. | `syntax_analysis` | true |
| `forbid_add` | Vieta esplicitamente ADD. | `syntax_analysis` | true |
| `forbid_move` | Vieta esplicitamente MOVE. | `syntax_analysis` | true |
| `forbid_copy` | Vieta esplicitamente COPY. | `syntax_analysis` | true |
| `forbid_insert` | Vieta esplicitamente INSERT. | `syntax_analysis` | true |
| `forbid_delete` | Vieta esplicitamente DELETE. | `syntax_analysis` | true |
| `runtime_graph_scope` | Verifica il namespace dei grafi durante l'esecuzione. | `support_analysis` | true |
| `runtime_cohort` | Soglia minima sui grafi contribuenti. | `support_analysis` | true |
| `runtime_work_limit` | Limite delle righe di supporto/intermedie. | `support_analysis` | true |
| `runtime_measures` | Controlla datatype e valori delle misure intermedie. | `support_analysis` | true |
| `runtime_aggregates` | Limita gli aggregati eseguibili dal percorso verificato. | `support_analysis` | true |
| `runtime_expressions` | Limita gli argomenti e le proiezioni numeriche verificate. | `support_analysis`, `numeric_analysis`, `aggregate_analysis` | true |
| `runtime_distinct_star` | Rifiuta COUNT(DISTINCT *). | `support_analysis` | true |
| `runtime_single_graph` | Richiede una variabile grafo nel percorso semplice. | `support_analysis` | true |
| `runtime_global_group` | Richiede una sola riga aggregata finale. | `support_analysis` | true |
| `runtime_control_cohort` | Soglia sulle dipendenze di controllo annidate. | `control_analysis` | true |
| `result_shape` | Struttura dei contenitori SPARQL Results JSON. |  | true |
| `result_columns` | Colonne esattamente uguali a quelle approvate. | `result_shape` | true |
| `result_single_row` | Una sola riga nella risposta finale. | `result_shape` | true |
| `result_metadata` | Nessun campo o metadato aggiuntivo. | `result_shape` | true |
| `result_numbers` | Output composto da letterali numerici verificati. |  | true |
| `numeric_format` | Forma lessicale coerente con il datatype numerico. |  | true |
| `count_format` | Conteggi interi non negativi. | `result_numbers`, `aggregate_analysis` | true |
| `finite_numbers` | Rifiuta numeri non finiti. |  | true |
| `numeric_bounds` | Limiti su lunghezza ed esponente dei numeri. |  | true |
| `result_consistency` | Confronta la risposta con gli aggregati ricalcolati. | `support_analysis`, `result_numbers` | true |
| `privacy_effective_contributors` | Coorti dei contributi effettivi: segue IF/COALESCE e riempimenti artificiali. | `runtime_cohort` | false |
| `privacy_correlated_patterns` | Rifiuta pattern clinici nel default graph, non correlati a GRAPH. | `algebra_analysis` | false |
| `privacy_distinct_persons` | Conta persone canoniche dal mapping fidato, non grafi distinti. | `runtime_cohort` | false |
| `privacy_authorization` | Verifica principal e ACL del dataset prima di interrogare i dati. |  | false |
| `privacy_query_history` | Blocca differencing, piccoli complementi e statistiche diverse sulla stessa coorte. | `privacy_distinct_persons`, `runtime_control_cohort` | false |
| `privacy_temporal_history` | Vincola i rilasci allo stesso snapshot del dataset. | `support_analysis` | false |
| `privacy_normalize_errors` | Sostituisce errori imprevisti con un errore pubblico privo di dati. |  | false |
| `adequacy_shacl` | Valida separatamente i grafi RDF con SHACL Core e SHACL-SPARQL prima del rilascio. |  | false |
| `adequacy_targets` | Richiede almeno un focus node effettivo per ogni grafo dati non vuoto. | `adequacy_shacl` | false |
| `adequacy_meta_shapes` | Verifica le shape con il meta-schema SHACL prima di validare i dati. | `adequacy_shacl` | false |
| `adequacy_warnings` | Considera bloccanti anche i risultati SHACL Warning. | `adequacy_shacl` | false |
| `adequacy_infos` | Considera bloccanti anche i risultati SHACL Info. | `adequacy_shacl` | false |
