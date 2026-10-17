# Configurazione

Per cambiare modello partire da [agents/models.json](agents/models.json).
Per avviare i servizi seguire la [guida ai modelli locali](../docs/guides/local-models.md).
Per scegliere fra applicazione, benchmark e demo vedere la
[guida dei comandi](../docs/guides/commands.md).

| File | Quando modificarlo |
|---|---|
| [agents/models.json](agents/models.json) | `model` e `base_url` scelgono l'LLM; `laya` configura il classificatore; `mcp_url` collega il server SPHN di LLM_ENGINE |
| [agents/sparql-mcp.json](agents/sparql-mcp.json) | Configurazione opzionale del vecchio server stdio, selezionato con `mcp_settings` al posto di `mcp_url` |
| [agents/policy.txt](agents/policy.txt) | Regole fidate da fornire ai modelli |
| [agents/permissions.txt](agents/permissions.txt) | Permessi dimostrativi da sostituire con quelli dell'identità autenticata |
| [policies/](policies/) | Profili dei controlli deterministici: `default`, `hardened`, `adequacy`, `unrestricted` |

I file di testo guidano i modelli; i profili JSON configurano analizzatore e
runtime. Modificare un testo non aggiorna i controlli dell'esecutore.
Caricamento e differenze dei profili sono nella [guida alle policy](../docs/policies/configuration.md).
`unrestricted` serve a confronti e dimostrazioni con controlli disabilitati.

`sparql-run` usa attualmente il profilo deterministico predefinito. I JSON in
`policies/` non vengono selezionati automaticamente da `models.json`:
`sparql-check --policy FILE` li usa per l'analisi statica; il runtime si
configura tramite l'API Python, fornendo anche i contesti fidati richiesti.

`models.json` seleziona i backend reali. I [modelli fittizi](../docs/guides/fake-models.md)
si scelgono nel codice quando si costruisce il workflow: non occorre modificare
questi file per eseguire la [demo offline](../examples/fake_workflow.py).

Nella CLI `sparql-run`, `--config`, `--policy-file` e
`--permissions-file` permettono di usare altri file. Senza MCP, omettere o impostare a null sia `mcp_url` sia `mcp_settings` e
passare `--schema-file`. I metadati disponibili sono descritti in
[schemas/void](../schemas/void/README.md).

Le opzioni `--dataset` e `--rdf-format` scelgono i dati locali da eseguire.
Non selezionano lo schema per il modello: quello viene da MCP o `--schema-file`.
Un file di schemi descrive i dati, mentre un dataset contiene i dati da interrogare.

Avviare il server condiviso con `bash start-mcp.sh`, poi verificare con
`uv run --extra agents --extra mcp sparql-run --check-mcp`.
Il server SPHN e distinto dal compose/prototipo UniProt di `LLM_ENGINE`.
