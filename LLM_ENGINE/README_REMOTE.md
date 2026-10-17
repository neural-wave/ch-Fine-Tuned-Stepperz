# Stack SPHN su Vast.ai

Eseguire dalla radice del repository, nel terminale Linux dell'istanza:

```bash
uv sync --locked --python 3.12 --extra local --extra api
bash LLM_ENGINE/start_remote.sh
bash start-api.sh --host 0.0.0.0 --port 10100
```

Servono vLLM nell'ambiente GPU, uv, tmux, curl e ss. Nessun container richiesto.
Lo script remoto installa le dipendenze MCP se manca il suo ambiente.
Non avvia Virtuoso e non esegue query sui dati paziente.

## Una configurazione

Modificare [models.json](../config/agents/models.json): `model`, `base_url`,
`mcp_url` e le impostazioni `laya`. API, debugger, CLI e health check usano
questo file. Lo script remoto lo legge per avviare vLLM e MCP; non serve
`.env.remote` e non viene generato `models.remote.json`.
Le variabili esportate per il comando `doctor` sono derivate dal JSON.
Le configurazioni `.env` del prototipo standalone restano utilizzabili solo
avviando esplicitamente quella CLI fuori da questo percorso.

Il preset espone vLLM su `127.0.0.1:18000/v1` e MCP su
`127.0.0.1:18888/mcp`. Lo script accetta indirizzi HTTP locali con questi path;
le porte sono lette dal JSON. Laya viene caricato in Python dall'API.

## Cambiare modello o aggiornare MCP

Lo script riusa i servizi esistenti. Dopo una modifica al modello fermare
il servizio che lo gestisce e rilanciare lo script. Per le sessioni create qui:

```bash
tmux kill-session -t '=sphn-qwen'
# Solo se hai aggiornato anche il codice MCP:
tmux kill-session -t '=sphn-mcp'
bash LLM_ENGINE/start_remote.sh
```

Questo interrompe le richieste attive. Riavviare anche API o debugger per
rileggere il JSON. Non fermare servizi gestiti da altri launcher alla cieca.

## Verifiche

```bash
curl --fail http://127.0.0.1:18000/v1/models
uv run --extra agents --extra mcp sparql-run --check-mcp
bash start-and-test.sh
```

L'ultimo comando avvia o riusa i servizi e lancia suite offline e health check
reali, caricando i modelli. Vedere [test](../tests/README.md).
Log dei servizi in `/workspace/logs/`; report in `artifacts/tests/`.

Se in precedenza avevi impostato `NL2SPARQL_CONFIG` o `MODEL_CONFIG` verso
il vecchio JSON remoto, rimuovi quelle variabili e le corrispondenti voci del
debugger per tornare al file condiviso. Le vecchie copie in `artifacts/` non
sono piu lette automaticamente.
