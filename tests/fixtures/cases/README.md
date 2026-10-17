# Query di test

32 file SPARQL separati. Le aspettative in cases.json sono indipendenti dal validatore.

| Query | Esito atteso | Motivo |
|---|---|---|
| [00_compliant.rq](00_compliant.rq) | Conforme | Conteggio aggregato di pazienti con diagnosi, senza identificatori in uscita. |
| [01_single_patient_graph.rq](01_single_patient_graph.rq) | R1 | Grafo esplicito di un paziente, anche se il risultato e aggregato. |
| [02_not_aggregated.rq](02_not_aggregated.rq) | R2 | Restituisce record individuali, non statistiche di coorte. |
| [03_unrestricted_graph.rq](03_unrestricted_graph.rq) | R3 | Scansiona qualsiasi tripla senza vincoli su soggetto, predicato o oggetto. |
| [04_ask.rq](04_ask.rq) | R4 | ASK e read-only ma le regole richiedono esclusivamente SELECT. |
| [05_identifier_aggregate.rq](05_identifier_aggregate.rq) | R5 | GROUP_CONCAT espone ID pur producendo un risultato aggregato. |
| [06_single_patient_values.rq](06_single_patient_values.rq) | R1 | Il paziente e selezionato tramite VALUES invece di GRAPH costante. |
| [07_identifier_alias.rq](07_identifier_alias.rq) | R2, R5 | STR e un alias non rendono anonimo l identificatore del grafo. |
| [08_identifier_group_by.rq](08_identifier_group_by.rq) | R1, R2, R5 | COUNT con GROUP BY paziente restituisce statistiche individuali ed espone il grafo. |
| [09_unrestricted_subquery.rq](09_unrestricted_subquery.rq) | R3 | La scansione indiscriminata e nascosta in una sottoquery. |
| [10_construct.rq](10_construct.rq) | R2, R4, R5 | CONSTRUCT esporta risorse di diagnosi invece di statistiche SELECT. |
| [11_delete.rq](11_delete.rq) | R4 | DELETE modifica i dati: deve essere rifiutato. Solo parsing, mai esecuzione. |
| [12_ok_diagnosis_lab_join.rq](12_ok_diagnosis_lab_join.rq) | Conforme | Join tra diagnosi ed esami nello stesso grafo; restituisce solo conteggi distinti. |
| [13_ok_optional_dates.rq](13_ok_optional_dates.rq) | Conforme | OPTIONAL con filtro temporale su valori clinici e conteggio globale. |
| [14_ok_union_cohorts.rq](14_ok_union_cohorts.rq) | Conforme | Unione di due coorti con pattern tipizzati e filtro su una data. |
| [15_ok_minus_treatment.rq](15_ok_minus_treatment.rq) | Conforme | Esclusione di pazienti con trattamento; nessun identificatore in uscita. |
| [16_ok_numeric_range.rq](16_ok_numeric_range.rq) | Conforme | Filtro numerico a intervallo su quantita e aggregazione globale. |
| [17_ok_multiple_optional_counts.rq](17_ok_multiple_optional_counts.rq) | Conforme | Due rami OPTIONAL, con DISTINCT per evitare duplicazioni nei conteggi. |
| [18_ok_arithmetic_counts.rq](18_ok_arithmetic_counts.rq) | Conforme | Espressione aritmetica che dipende soltanto da conteggi globali. |
| [19_ok_having_count.rq](19_ok_having_count.rq) | Conforme | HAVING e ORDER BY basati su conteggi di coorte, non su ID. |
| [20_ok_optional_numeric_filter.rq](20_ok_optional_numeric_filter.rq) | Conforme | Join opzionale con misure filtrate; esporta solo conteggi. |
| [21_ok_union_minus_join.rq](21_ok_union_minus_join.rq) | Conforme | Combinazione di UNION, MINUS e join clinici, con output aggregato. |
| [22_bad_identifier_alias_concat.rq](22_bad_identifier_alias_concat.rq) | R5 | Un identificatore attraversa due BIND ed e concatenato nell output. |
| [23_bad_patient_filter_alias_chain.rq](23_bad_patient_filter_alias_chain.rq) | R1 | Il grafo paziente viene selezionato tramite una catena di alias e un filtro. |
| [24_bad_optional_unrestricted.rq](24_bad_optional_unrestricted.rq) | R3 | Un pattern clinico esterno non giustifica un ramo opzionale completamente libero. |
| [25_bad_group_by_patient_alias.rq](25_bad_group_by_patient_alias.rq) | R1, R2, R5 | Conteggi individuali mascherati dietro un alias del grafo. |
| [26_bad_subquery_identifier_export.rq](26_bad_subquery_identifier_export.rq) | R2, R5 | La sottoquery non rende anonimo un identificatore rinominato ed esportato. |
| [27_bad_optional_min_identifier.rq](27_bad_optional_min_identifier.rq) | R5 | MIN di un identificatore ne espone comunque un valore, anche se aggregato. |
| [28_bad_values_patient_join.rq](28_bad_values_patient_join.rq) | R1 | VALUES restringe la coorte a un paziente nonostante join e aggregazioni. |
| [29_bad_construct_join.rq](29_bad_construct_join.rq) | R2, R4, R5 | CONSTRUCT esporta le risorse cliniche collegate e i loro identificatori. |
| [30_bad_modify_diagnoses.rq](30_bad_modify_diagnoses.rq) | R4 | DELETE/INSERT modifica diagnosi selezionate con join e filtro temporale. |
| [31_bad_union_raw_dates.rq](31_bad_union_raw_dates.rq) | R2 | Date di eventi individuali esportate senza aggregazione da due coorti. |
