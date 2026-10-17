# Modelli e consumo dei token

Tutti i contratti (`LLM`, `SparqlLLM`, `SystemOneModel`, `PromptValidator`)
espongono due metodi:

```python
output = await model.run(request)  # comportamento precedente
response = await model.run_with_usage(request)
output = response.output
tokens = response.usage  # TokenUsage, specifico di questa chiamata
```

`ModelResponse` contiene dati applicativi e metriche separati. Le metriche non
entrano nello schema richiesto all'LLM: non vengono generate dal modello.
Non esiste un contatore globale `last_usage`, che mescolerebbe richieste concorrenti.
Gli import da `agent_orchestration`, `.models`, `.adapters` e `.fakes` restano validi.

## Quali token vengono contati

| Backend | Fonte |
|---|---|
| LLM/generatore/guard PydanticAI | Usage del singolo run, cumulativo sui turni e retry osservati dall'SDK |
| Ollama, vLLM, llama.cpp tramite API compatibile | Usage restituito dal provider, raccolto da PydanticAI |
| Laya nativo | `usage.input_tokens` del forward pass; output zero perche non genera testo |
| Altri classificatori nativi/Hugging Face | `ModelResponse(Decision(...), TokenUsage(...))` restituito dal callback, oppure tokenizer opzionale |
| Modelli fittizi | Zero token reali, `source="simulated"`; contatori simulati impostabili nei test |
| Implementazioni precedenti con solo `run()` | Usage non disponibile, oppure `count_tokens()` personalizzato |

I token di input includono quanto contabilizzato dal backend: istruzioni,
contesto, strumenti, schema e cronologia. Non si conta solo il testo del prompt.
Le risposte ai tool vengono contate quando entrano nell'input di un successivo
turno del modello; il retrieval MCP non e di per se un modello generativo.
Cache e reasoning sono riportati separatamente quando disponibili e non vengono
sommati di nuovo al totale input + output.

Il backend deve esporre contatori per misurare il consumo reale. Una chiamata
senza risposta, un retry interno non rendicontato dal provider o un thread nativo
ancora attivo dopo la cancellazione non possono essere ricostruiti con certezza.
In caso di errore/timeout vengono conservati i contatori parziali ricevuti, con
`complete=false`. Se l'input di Laya viene rifiutato per troncamento dopo il
forward pass, i token gia misurati vengono comunque conservati.

Il formato `TokenUsage` accetta input, output, totale, modello, fonte, numero di
richieste e dettagli opzionali di cache e reasoning. `None` significa sconosciuto,
zero significa consumo noto nullo. `source` distingue `reported`, `estimated`,
`simulated`, `unavailable`; i contatori sintetici dei modelli di test PydanticAI
sono identificati come simulati/stimati.

Riferimenti dei backend: [usage PydanticAI](https://ai.pydantic.dev/api/usage/)
e [usage Laya](https://github.com/NandhaKishorM/laya/blob/main/docs/http-api.md).

## Analytics restituite

`sparql-run` aggiunge `analytics` al JSON gia esistente:

```json
{
  "analytics": {
    "token_usage": {
      "input_tokens": 90,
      "output_tokens": 20,
      "total_tokens": 110,
      "known_input_tokens": 90,
      "known_output_tokens": 20,
      "known_total_tokens": 110,
      "complete": true,
      "estimated": false,
      "by_stage": {
        "prompt_validation": {"input_tokens": 50, "output_tokens": 0, "total_tokens": 50},
        "generation": {"input_tokens": 40, "output_tokens": 20, "total_tokens": 60}
      }
    },
    "timings": {"prompt_validation": 0.1, "generation": 1.2}
  }
}
```

Esempio abbreviato: ogni voce di `by_stage` include anche modello, fonte,
completezza, richieste e dettagli opzionali. I tempi di esempio non sono misure.
Le fasi non eseguite non compaiono: un prompt bloccato conta solo il guard.
Con una fase non rendicontata o parziale il totale completo diventa `null`;
`known_total_tokens` conserva la somma disponibile. `estimated=true` segnala
l'uso di un conteggio stimato. Il campo `timings` precedente resta compatibile.

I benchmark riportano questi dati in ogni `outcome.analytics` e il riepilogo
aggregato in `summary.token_usage`. Gli health check salvano `token_usage` nelle
proprieta del report XML. I token compaiono anche nei log nativi del workflow.
L'API separata in `src/api/server.py` usa direttamente `LLM_ENGINE` e conserva
il proprio contratto `tokens_consumed`; non attraversa questo workflow.

## Collegare un backend nuovo

Se il backend espone usage, restituirlo insieme alla decisione:

```python
from agent_orchestration import CallableSystemOneModel, Decision, ModelResponse, TokenUsage

def predict(request):
    raw = backend.predict(request.state, request.question, request.options)
    return ModelResponse(
        Decision(raw["choice"]),
        TokenUsage.from_backend(raw.get("usage"), model="my-classifier"),
    )

classifier = CallableSystemOneModel(predict)
```

`backend` e il modello da fornire. La funzione puo essere sincrona o asincrona.
Per un nuovo LLM basta implementare `run_with_usage` con lo stesso involucro,
oltre al normale `run`; il workflow non richiede modifiche.

Senza contatori del backend si puo fornire un tokenizer gia caricato:

```python
from agent_orchestration import tokenizer_counter

counter = tokenizer_counter(
    tokenizer,
    model="my-classifier",
    input_text=serialize_native_request,
    generates_text=False,
)
classifier = CallableSystemOneModel(predict_decision_only, token_counter=counter)
```

`tokenizer`, `serialize_native_request` e `predict_decision_only` sono forniti dal
chiamante. Il contatore non scarica pesi o tokenizer. Per un generatore usare
`generates_text=True` e fornire le serializzazioni input/output adeguate.
Si tratta di una stima esplicita: bisogna includere template chat e istruzioni
effettive; il solo tokenizer non conosce il contesto aggiunto dal server o i retry.
Se la serializzazione include gia i token speciali, passare
`add_special_tokens=False` per evitare di contarli due volte.
Gli adapter PydanticAI preferiscono sempre l'usage del provider al tokenizer.
