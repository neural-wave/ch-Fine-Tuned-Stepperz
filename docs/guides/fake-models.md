# Modelli fittizi

Tre classi sostituibili ai backend reali, senza Ollama, PydanticAI o pesi:

| Classe | Input | Output |
|---|---|---|
| `FakeLLM` | testo | testo |
| `FakeSparqlLLM` | `SparqlRequest` | `SparqlResult` |
| `FakeClassifier` | `DecisionRequest` | `Decision` |

La strategia si passa direttamente al costruttore:

```python
from agent_orchestration import FakeLLM, FakeSparqlLLM, FakeClassifier
from agent_orchestration.fakes import sequence, by_keywords, random_choice

text = FakeLLM("Risposta fissa")
generator = FakeSparqlLLM("SELECT * WHERE { ?s ?p ?o }")
classifier = FakeClassifier("allow")

classifier = FakeClassifier(sequence(["allow", "block", "review"]))
generator = FakeSparqlLLM(sequence(["query valida", "query malformata"], repeat=True))
classifier = FakeClassifier(random_choice(["allow", "block", "review"], seed=42))
generator = FakeSparqlLLM(by_keywords({"conta": "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"}, default="query non valida"))

failing = FakeLLM(RuntimeError("Errore simulato"))
slow = FakeClassifier("allow", delay=2)
custom = FakeLLM(lambda request: request.upper())
```

`sequence` solleva un errore quando esaurisce le risposte; `repeat=True` ripete
l'intera sequenza. Anche errori possono comparire nella sequenza. Creare una
nuova strategia per ogni test indipendente: sequenze e casualita hanno stato.
`by_keywords` usa la prima corrispondenza nell'ordine del dizionario, ignorando
maiuscole/minuscole; poi usa il default. Per SPARQL cerca nel prompt, per le
decisioni nello state. Se lo state contiene JSON con policy e permessi, isolare
il prompt con `text=lambda r: json.loads(r.state)["prompt"]` (importando `json`).

Si possono passare funzioni sincrone o asincrone che ricevono la richiesta
completa. Le funzioni sincrone devono essere brevi; per simulare attese usare
`delay` o una funzione asincrona. Le richieste tentate sono in `model.calls`,
anche dopo errore o timeout. Nessuna probabilita viene inventata: per simulare
una soglia passare esplicitamente `Decision("allow", probability=0.3)`.

Per il workflow, usare `SystemOnePromptValidator(classifier)` e il generatore
fittizio direttamente. Rimangono attivi analizzatore e runtime reali.
La demo completa usa dati sintetici e mostra rilascio, blocco e revisione:

```bash
uv run python -m examples.fake_workflow
```

Queste strategie verificano il comportamento del sistema, non la comprensione
del linguaggio o l'accuratezza di un modello di sicurezza. La query fittizia
puo essere volutamente errata o proibita per provare i controlli successivi.
