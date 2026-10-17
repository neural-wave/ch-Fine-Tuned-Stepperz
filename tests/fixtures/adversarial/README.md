# Corpus avversario

Dati e identificatori sono fittizi; le destinazioni esterne usano
`example.invalid`. Le query con SERVICE, update o dialetto Virtuoso vengono
analizzate e bloccate prima dell'esecuzione. Nessun database remoto è interrogato.

- [`cases.json`](cases.json) annota le query singole in [`queries/`](queries/).
- [`scenarios.json`](scenarios.json) descrive sequenze, varianti del dataset e
  integrazioni. Il valore `known_gap` conserva la classificazione storica:
  le regressioni attuali verificano il blocco con hardened.
- Il [corpus complesso](../adversarial_complex/README.md) copre maschere numeriche,
  contributi artificiali e provenienza delle misure.

## Esecuzione

Dalla radice del repository:

```bash
uv run pytest tests/privacy/test_adversarial.py tests/privacy/test_adversarial_sequences.py tests/privacy/test_adversarial_payloads.py -q
uv run pytest tests/privacy/test_adversarial_sequences.py -m security_gap -v
uv run python -m tools.export_adversarial
```

Il primo comando verifica query singole, sequenze e risposte alterate. Il secondo
isola le regressioni hardened. L'export scrive in
`artifacts/tests/adversarial/`: un risultato per caso e un `report.json`.
Copia anche i metadati degli scenari, ma **non ne esegue i test sequenziali**.
L'export generale `tools.export_test_results` comprende questo sottocorpus.

## Significato degli esiti

| Suite | Cosa verifica |
|---|---|
| [`test_adversarial.py`](../../privacy/test_adversarial.py) | Aspettative di `cases.json` sul profilo predefinito. Controlla la sintassi standard prima del verdetto e impedisce alle query bloccate staticamente di raggiungere il database |
| [`test_adversarial_payloads.py`](../../privacy/test_adversarial_payloads.py) | Risposte del backend alterate lungo l'intero percorso `execute_checked` |
| [`test_adversarial_sequences.py`](../../privacy/test_adversarial_sequences.py), marker `security_gap` | Blocco con hardened e contesto fidato; SHACL disattivato perché le fixture privacy sono minimali |
| Stessa suite, marker `risk_demonstration` | Riproduzione dei rischi sul profilo predefinito: un test verde conferma l'osservazione del rischio |

Le regressioni di blocco sono test ordinari, non `xfail`. Il rifiuto di un
dialetto non supportato non prova equivalenza semantica con Virtuoso.
Per configurazione dei toggle e controlli positivi vedere
[`test_privacy_policies.py`](../../privacy/test_privacy_policies.py) e la
[guida privacy](../../../docs/policies/privacy.md).

## Scenari generali

| Scenario storico | Dimostrazione | Regressione hardened |
|---|---|---|
| Differenze tra conteggi | Due coorti di 8 e 7 persone isolano una presenza | Il secondo rilascio viene bloccato usando lo storico |
| Confronto temporale | La stessa query prima e dopo una modifica nota restituisce 8 e 7 | La verifica usa lo snapshot fidato |
| Grafi duplicati | Più grafi della stessa persona gonfiano la coorte | Il mapping fidato conta persone distinte |
| Autorizzazione | Un prefisso del grafo non prova l'accesso al tenant | Il contesto fidato definisce i grafi autorizzati |
| Condizione non correlata | Un record nel default graph controlla una coorte non correlata | La policy rifiuta la provenienza non correlata |
| Errore backend | Un'eccezione sintetica contiene un valore privato | L'errore pubblico viene normalizzato |

Il confronto temporale modifica i dati tra richieste: non verifica una race
durante una singola esecuzione. L'errore backend è simulato, non prodotto da
Virtuoso. I controlli dipendono dal servizio che fornisce principal, ACL,
mapping delle persone, storico e snapshot corretti.

Sul profilo predefinito restano dimostrazioni di omogeneità, coorti sovrapposte,
complementi ricostruibili e ricostruzione dell'appartenenza mediante conteggi
ripetuti. Non sono prove di protezione.

## Copertura e limiti

Le query singole coprono estrazione diretta, alias, hash e codifiche,
aggregazioni che conservano identificatori, frammenti ricomponibili, paginazione,
selezione individuale, sottoquery, UNION/OPTIONAL, coorti rare, risorse esterne e
operatori vietati. Le annotazioni nei JSON restano la fonte dei singoli esiti.

La policy numerica permette aritmetica su conteggi verificati (`r05`) e SUM/AVG
di misure autorizzate; COUNT con espressioni su identificatori è bloccato
staticamente (`r04`). Consentire queste operazioni non garantisce anonimato:
le [sonde complesse](../adversarial_complex/README.md) ne verificano usi avversari.

Prima del deployment restano da provare ACL e isolamento di utenti/cache,
restrizioni di rete, comportamento parser/Virtuoso, snapshot durante modifiche
concorrenti e riservatezza di tempi, errori e log. I test offline del workflow
verificano che le query generate attraversino i controlli; la resistenza a
prompt injection e l'accuratezza dei modelli richiedono inferenza reale.
Un eventuale meccanismo di privacy differenziale richiederebbe test propri di
budget, composizione e contributo per persona.

Le fixture illustrano strutture di privacy, non cartelle cliniche validate
contro le shape SPHN complete. Per i comandi generali e i profili vedere
[`tests/README.md`](../../README.md).
