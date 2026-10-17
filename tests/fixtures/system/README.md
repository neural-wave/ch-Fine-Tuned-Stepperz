# Associazioni prompt-query

[`prompt_query_links.json`](prompt_query_links.json) collega prompt, decisioni
attese e query del [corpus di compliance](../cases/README.md). Le query restano
nei file `.rq`; l'hash del contenuto rileva modifiche che richiedono la revisione
dell'associazione. I prompt sono annotati manualmente, non validati da un modello
o da una revisione clinica indipendente.

Per eseguire la valutazione con risposte note, dalla radice del repository:

```bash
uv run --extra agents python -m tools.evaluate_workflow --offline
```

Il report è `artifacts/workflow-evaluation/report.json`. Oracoli, fixture,
separazione per `group_id` e limiti del confronto sono nella
[guida al workflow](../../../docs/guides/agent-workflow.md).

Per aggiornare le associazioni usare `uv run python -m tools.build_prompt_links`
solo dopo aver rivisto le annotazioni nel tool rispetto alle query correnti.
Non suddividere le parafrasi dello stesso gruppo tra train e test.

Il [dataset di sistema iniziale](../../../docs/system-dataset.md) è uno smoke
test separato. Per suite e comandi pytest vedere [`tests/README.md`](../../README.md).
