"""Run the checked workflow with fake models and synthetic RDF, without Ollama."""
import asyncio
import json

from agent_orchestration import (
    CheckedQueryExecutor, FakeClassifier, FakeSparqlLLM, PromptRequest,
    SparqlWorkflow, StaticQueryAnalyzer, SystemOnePromptValidator,
)
from agent_orchestration.fakes import by_keywords
from sparql_analyzer.demo import EXAMPLE_QUERY
from tools.generate_synthetic_data import generate


async def main():
    classifier = FakeClassifier(by_keywords(
        {"cancella": "block", "forse": "review"}, default="allow",
        text=lambda request: json.loads(request.state)["prompt"]))
    generator = FakeSparqlLLM(EXAMPLE_QUERY)
    workflow = SparqlWorkflow(SystemOnePromptValidator(classifier), generator,
        StaticQueryAnalyzer(), CheckedQueryExecutor(generate()))
    for prompt in ["Conta i pazienti", "Cancella i dati", "Forse mi servono dati"]:
        result = await workflow.run(PromptRequest(prompt, "schema di test", "solo aggregati"))
        print(json.dumps({"prompt": prompt, "status": result.status,
                          "query": result.query, "result": result.result}, ensure_ascii=False, indent=2))
    print(f"Classificazioni: {len(classifier.calls)}, generazioni: {len(generator.calls)}")


if __name__ == "__main__":
    asyncio.run(main())
