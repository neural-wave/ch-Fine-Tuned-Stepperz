# Sonde avversarie complesse

## Obiettivo e perimetro

Queste sonde cercano un'esposizione effettiva con gli operatori numerici ammessi
dal profilo predefinito. Non basta che la query passi il controllo statico:
per dichiarare un bypass deve superare execute_checked e produrre il valore
sintetico che dimostra l'isolamento o una statistica individuale.

Si usano esclusivamente fixture RDFLib locali e dati fittizi. SERVICE e altri
costrutti bloccati non vengono eseguiti; nessuna connessione a un database reale.
Le aspettative e i valori sintetici sono in [`cases.json`](cases.json).

## Fixture

[`complex_fixture.py`](../../support/complex_fixture.py) crea otto grafi con join tra diagnosi, caso, soggetto, esame,
quantita e marcatore numerico noto. I valori di misura sono 1000..1007; un solo
paziente ha una misura rara pari a 4242. Il default graph contiene una misura
7777 non correlata ai pazienti. I numeri sono fittizi e scelti per rendere
verificabile ogni risultato. Il marcatore 0..7 simula un quasi-identificatore
conosciuto dall'attaccante, non una protezione o un dato clinico realistico.

Le fixture sono minimali e non vengono validate contro tutte le shape SPHN.
La variante `duplicate_person` modifica i
collegamenti in modo che tutti i grafi facciano riferimento alla stessa persona.

## Esito riprodotto

Gli esiti BYPASS riportati sotto si riferiscono al profilo storico predefinito.
Gli stessi 11 casi sono ora bloccati nei test del profilo hardened, con
contesto fidato e [policy privacy](../../../docs/policies/privacy.md).
Le 3 query positive continuano a funzionare anche con quel profilo.

- 25 query separate, ciascuna sintatticamente valida.
- 11 varianti espongono un valore o sottogruppo individuale nel modello di minaccia.
- 11 vengono bloccate, di cui 6 staticamente e 5 al runtime.
- 3 sono controlli positivi complessi che devono continuare a funzionare.

Gli 11 bypass sono varianti di famiglie di problemi, non 11 vulnerabilita
indipendenti. Alcuni rafforzano lacune gia note: correlazione e grafi duplicati.
La dimensione della coorte formale non basta a stabilire l'anonimato.

## Casi

| File | Esito sul profilo predefinito | Spiegazione |
|---|---|---|
| [c01_masked_sum.rq](queries/c01_masked_sum.rq) | BYPASS | Otto contribuenti formali, ma sette contributi sono azzerati: espone il valore del solo target. |
| [c02_scaled_masked_average.rq](queries/c02_scaled_masked_average.rq) | BYPASS | Media mascherata e numerosita ricostruiscono il valore individuale. |
| [c03_rounded_masked_sum.rq](queries/c03_rounded_masked_sum.rq) | BYPASS | Aritmetica e arrotondamento nascondono lo stesso isolamento individuale. |
| [c04_coalesce_optional_sum.rq](queries/c04_coalesce_optional_sum.rq) | BYPASS | COALESCE assegna zero ai non contribuenti e gonfia la coorte apparente della misura rara. |
| [c05_coalesce_optional_average.rq](queries/c05_coalesce_optional_average.rq) | BYPASS | La media con riempimento a zero viene riscalata per esporre la misura rara. |
| [c06_union_zero_padding.rq](queries/c06_union_zero_padding.rq) | BYPASS | Un ramo UNION aggiunge pazienti con zeri; DISTINCT non protegge la misura rara. |
| [c07_default_graph_broadcast.rq](queries/c07_default_graph_broadcast.rq) | BYPASS | Una misura nel default graph e ripetuta su otto grafi paziente non correlati. |
| [c08_default_graph_ratio.rq](queries/c08_default_graph_ratio.rq) | BYPASS | Rapporto tra somma e coorte espone una misura esterna non correlata. |
| [c09_duplicate_person_average.rq](queries/c09_duplicate_person_average.rq) | BYPASS | Otto grafi della stessa persona sono contati come otto contribuenti. |
| [c10_identifier_numeric_alias.rq](queries/c10_identifier_numeric_alias.rq) | Bloccato | AVG di identificatori numerici attraverso alias aritmetico. |
| [c11_identifier_with_fake_numeric_origin.rq](queries/c11_identifier_with_fake_numeric_origin.rq) | Bloccato | Lo stesso nome variabile riceve una provenienza numerica e una identificativa. |
| [c12_rare_having.rq](queries/c12_rare_having.rq) | Bloccato | La condizione HAVING dipende da una misura di un solo paziente. |
| [c13_rare_order_by.rq](queries/c13_rare_order_by.rq) | Bloccato | Aggregato individuale nascosto nell ordinamento. |
| [c14_nested_group_concat.rq](queries/c14_nested_group_concat.rq) | Bloccato | Operatore vietato dentro uno scope annidato. |
| [c15_conditional_identifier_count.rq](queries/c15_conditional_identifier_count.rq) | Bloccato | Condizione su identificatore nascosta dentro COUNT. |
| [c16_service_in_optional.rq](queries/c16_service_in_optional.rq) | Bloccato | SERVICE in un ramo opzionale: mai eseguito durante il test. |
| [c17_nested_numeric_predicate_spoof.rq](queries/c17_nested_numeric_predicate_spoof.rq) | Bloccato | Una sottoquery non deve trasformare un identificatore in una misura. |
| [c18_ratio_zero_denominator.rq](queries/c18_ratio_zero_denominator.rq) | Bloccato | Divisione per zero dopo aggregazioni formalmente lecite. |
| [c19_rare_direct_average.rq](queries/c19_rare_direct_average.rq) | Bloccato | Senza riempimento artificiale la misura rara deve essere soppressa. |
| [c20_non_finite_branch.rq](queries/c20_non_finite_branch.rq) | Bloccato | Una misura non finita non deve arrivare all output. |
| [c21_safe_multi_join_average.rq](queries/c21_safe_multi_join_average.rq) | Consentito | Controllo positivo: join su caso e soggetto, media reale della coorte. |
| [c22_safe_optional_count.rq](queries/c22_safe_optional_count.rq) | Consentito | Controllo positivo: ramo opzionale vuoto e rapporto tra aggregati coerenti. |
| [c23_safe_minus.rq](queries/c23_safe_minus.rq) | Consentito | Controllo positivo: MINUS su criterio clinico, somma di otto misure. |
| [c24_combined_join_union_mask.rq](queries/c24_combined_join_union_mask.rq) | BYPASS | Composizione di costrutti ammessi: misura individuale sotto una somma con coorte gonfiata. |
| [c25_rare_indicator_sum.rq](queries/c25_rare_indicator_sum.rq) | BYPASS | SUM di indicatori pubblica un gruppo positivo di una persona, pur dichiarando otto contribuenti. |

## Famiglie di bypass

- **Maschere e zeri artificiali:** IF, COALESCE o UNION fanno apparire ampia una
  coorte in cui un solo paziente contribuisce davvero al valore rilasciato.
- **Media invertibile:** media mascherata e numerosità ricostruiscono una misura
  individuale. Le composizioni più articolate non cambiano questo risultato.
- **Provenienza non correlata:** un valore nel default graph viene ripetuto su
  più grafi paziente; la coorte formale non descrive la sorgente reale del valore.
- **Grafi duplicati:** più grafi della stessa persona non equivalgono a più persone.
- **Indicatori di gruppi rari:** una somma su una coorte ampia può rivelare un solo
  membro di un sottogruppo noto. Il rischio dipende anche dalla conoscenza simulata
  del marcatore e della popolazione, non soltanto dal valore numerico finale.

## Esecuzione e significato dei test

```powershell
uv run pytest tests/privacy/test_complex_attacks.py -v
uv run python -m tests.support.complex_attacks
uv run pytest tests/privacy/test_complex_attacks.py -m security_gap -v
```

Le 25 osservazioni verificano risultati esatti, blocchi controllati o controlli
positivi. Quelle che riproducono un bypass hanno il marker risk_demonstration:
il loro successo significa che il problema e riproducibile, non risolto.

I requisiti separati con marker `security_gap` verificano invece il blocco con
`Policy.hardened()`, contesto fidato, `adequacy_shacl=False` e
`privacy_normalize_errors=False`. Sono test ordinari, non `xfail`: soltanto
`ResultBlocked` soddisfa l'aspettativa; un crash imprevisto fa fallire il test.
Il terzo comando esegue solo queste regressioni. I controlli positivi hardened
sono in [`test_privacy_policies.py`](../../privacy/test_privacy_policies.py).

Il report e in artifacts/tests/adversarial_complex/report.json; ogni query ha
anche parse_tree.json, algebra.json e verdict.json in una sottocartella dedicata.
privacy_bypass_reproduced distingue i bypass dalle normali query consentite.
L'export generale `tools.export_test_results` include questa suite. Il report
osserva il profilo predefinito, non esegue le regressioni hardened.

## Implicazioni per il controllore

La lista di operatori vietati e il controllo dei datatype non bastano per questi
casi. Le protezioni hardened considerano provenienza, contribuzione, maschere,
riempimenti, rami e correlazione tra risorse e persone. Non basta eliminare tutti
gli zeri: zero puo essere una misura reale e il criterio va definito semanticamente.

Il contesto fidato deve fornire autorizzazioni, mapping delle persone, storico
e snapshot corretti; queste fixture non verificano l'integrazione con identità
e dati reali. I report riguardano RDFLib locale, non il comportamento di Virtuoso
o una garanzia di anonimato. Comandi generali in [`tests/README.md`](../../README.md).
