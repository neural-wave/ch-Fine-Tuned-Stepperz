# Documentazione

Partire dal [README principale](../README.md) per orientarsi e dalla
**[guida dei comandi](guides/commands.md)** per eseguire le funzionalita.

## Percorsi d'uso

| Obiettivo | Documentazione |
|---|---|
| Esporre POST /nl-to-sparql al client | [API HTTP](guides/http-api.md) |
| Eseguire un prompt con modelli reali | [Avvio locale](guides/local-models.md), [configurazione](../config/README.md) |
| Capire stati, fasi e componenti del workflow | [Workflow agentico](guides/agent-workflow.md) |
| Leggere token e analytics o collegare un nuovo modello | [Modelli e uso dei token](guides/model-usage.md) |
| Ridurre e misurare la latenza dei modelli | [Prestazioni inferenza](guides/inference-performance.md) |
| Provare o simulare i modelli | [Modelli fittizi](guides/fake-models.md), [demo](../examples/README.md) |
| Eseguire test e leggere i report | [Test](../tests/README.md) |
| Valutare il corpus o rigenerare dati/report | [Tools](../tools/README.md) |
| Analizzare una query gia disponibile | [SPARQL e runtime](guides/sparql.md) |
| Scegliere schemi e metadati | [Schemi](../schemas/README.md) |
| Gestire il database | [Virtuoso](../infra/virtuoso/README.md) |
| Consultare il prototipo sperimentale separato | [LLM_ENGINE](../LLM_ENGINE/README.md) |

## Riferimenti

| Area | Documenti |
|---|---|
| Architettura | [Mappa del codice](architecture/project-layout.md), [flusso e diagrammi](architecture/overview.md), [sorgenti Mermaid](architecture/diagrams/README.md) |
| Policy | [Configurazione](policies/configuration.md), [catalogo dei toggle](policies/checks.md), [operazioni](policies/operations.md), [privacy](policies/privacy.md), [adeguatezza SHACL](policies/adequacy-shacl.md) |
| Sicurezza | [Attacchi all'anonimato](security/anonymity-attacks.md), [compliance e ruolo di SHACL](security/compliance-and-shacl.md) |
| Caso diagnosticato | [Query per sesso: gruppi non supportati ed errori di generazione](security/query-by-sex-review.md) |
| Dataset | [Corpus prompt-query](../tests/fixtures/system/README.md), [smoke test iniziale](system-dataset.md) |
| Specifiche | [API](specifications/API_specification.md), [regole applicative](specifications/Query_Compliance.md) |

Le specifiche includono requisiti progettuali; guide e test descrivono quanto
implementato. Workflow RDFLib, script Virtuoso e `LLM_ENGINE` sono percorsi distinti.
