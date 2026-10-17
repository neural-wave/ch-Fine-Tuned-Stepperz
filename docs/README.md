# Documentazione

Per installazione e primi comandi partire dal [README principale](../README.md).

## Cosa vuoi fare?

| Obiettivo | Guida |
|---|---|
| Provare il workflow senza modelli reali | [Modelli fittizi](guides/fake-models.md), [test offline e report](../tests/README.md) |
| Scegliere modelli e avviarli sull'istanza | [Modelli locali](guides/local-models.md), [file di configurazione](../config/README.md) |
| Collegare classificatore, generatore e runtime | [Workflow agentico](guides/agent-workflow.md) |
| Validare ed eseguire SPARQL | [Analizzatore e runtime](guides/sparql.md) |
| Capire schemi, SHACL e VoID | [Mappa degli schemi](../schemas/README.md) |
| Gestire il triplestore | [Virtuoso](../infra/virtuoso/README.md) |
| Trovare demo o tool | [Esempi](../examples/README.md), [manutenzione](../tools/README.md) |

## Approfondimenti

| Area | Documenti |
|---|---|
| Architettura | [Mappa del codice](architecture/project-layout.md), [flusso e diagrammi](architecture/overview.md), [sorgenti Mermaid](architecture/diagrams/README.md) |
| Policy | [Configurazione](policies/configuration.md), [catalogo dei toggle](policies/checks.md), [operazioni](policies/operations.md), [privacy](policies/privacy.md), [adeguatezza SHACL](policies/adequacy-shacl.md) |
| Sicurezza | [Attacchi all'anonimato](security/anonymity-attacks.md), [compliance e ruolo di SHACL](security/compliance-and-shacl.md) |
| Dataset | [Corpus prompt-query](../tests/fixtures/system/README.md), [smoke test sintetico iniziale](system-dataset.md) |
| Specifiche | [API](specifications/API_specification.md), [regole applicative](specifications/Query_Compliance.md) |

Le specifiche includono requisiti progettuali; guide e test descrivono il codice
implementato. Il workflow usa il runtime RDFLib locale, mentre gli script
Virtuoso seguono un percorso separato.
