import asyncio
import json
import random

import pytest

from agent_orchestration import (
    CheckedQueryExecutor, Decision, DecisionRequest, FakeClassifier, FakeLLM,
    FakeSparqlLLM, PromptRequest, SparqlRequest, SparqlResult, SparqlWorkflow,
    StaticQueryAnalyzer, SystemOnePromptValidator,
)
from agent_orchestration.fakes import by_keywords, random_choice, sequence
from sparql_analyzer.demo import EXAMPLE_QUERY
from tools.generate_synthetic_data import generate

pytestmark = pytest.mark.offline_workflow


def decision_request():
    return DecisionRequest("state", "Assess", {"allow": "allowed", "block": "prohibited", "review": "ambiguous"})


def test_sequence_exhaustion_and_explicit_cycle():
    async def exercise():
        model = FakeClassifier(sequence(["allow", "block"]))
        assert (await model.run(decision_request())).choice == "allow"
        assert (await model.run(decision_request())).choice == "block"
        with pytest.raises(RuntimeError, match="exhausted"):
            await model.run(decision_request())
        cyclic = FakeLLM(sequence(["first", "second"], repeat=True))
        assert [await cyclic.run("p") for _ in range(3)] == ["first", "second", "first"]
    asyncio.run(exercise())


def test_keywords_priority_fallback_and_prompt_extraction():
    model = FakeClassifier(by_keywords({"delete": "block", "count": "allow"}, "review",
        text=lambda r: json.loads(r.state)["prompt"]))
    async def exercise():
        guard = SystemOnePromptValidator(model)
        for prompt, expected in [("COUNT patients", "allow"), ("delete then count", "block"), ("unspecified", "review")]:
            assert (await guard.run(PromptRequest(prompt, "schema", "never delete"))).decision == expected
        generator = FakeSparqlLLM(by_keywords({"count": EXAMPLE_QUERY}, "invalid query"))
        assert (await generator.run(SparqlRequest("COUNT", "s", "p"))).query == EXAMPLE_QUERY
    asyncio.run(exercise())


def test_seeded_randomness_is_local_and_does_not_invent_confidence():
    state = random.getstate()
    async def exercise():
        first = FakeClassifier(random_choice(["allow", "block", "review"], seed=42))
        second = FakeClassifier(random_choice(["allow", "block", "review"], seed=42))
        a = [await first.run(decision_request()) for _ in range(12)]
        b = [await second.run(decision_request()) for _ in range(12)]
        assert a == b and len({r.choice for r in a}) > 1
        assert all(r.probability is None for r in a)
    asyncio.run(exercise())
    assert random.getstate() == state


def test_async_generation_context_and_explicit_probability():
    async def respond(request):
        return SparqlResult(request.schema)
    async def exercise():
        request = SparqlRequest("prompt", EXAMPLE_QUERY, "trusted policy", "analyst")
        model = FakeSparqlLLM(respond)
        assert (await model.run(request)).query == EXAMPLE_QUERY
        assert model.calls == [request]
        guard = SystemOnePromptValidator(FakeClassifier(Decision("allow", 0.2)), min_allow_probability=0.8)
        assert (await guard.run(PromptRequest("p", "s", "policy"))).decision == "review"
    asyncio.run(exercise())


@pytest.mark.parametrize("response,error", [("unknown", ValueError), (123, TypeError)])
def test_invalid_classifier_outputs(response, error):
    with pytest.raises(error):
        asyncio.run(FakeClassifier(response).run(decision_request()))


@pytest.mark.parametrize("decision,query,status", [
    ("allow", EXAMPLE_QUERY, "released"),
    ("block", EXAMPLE_QUERY, "blocked_prompt"),
    ("review", EXAMPLE_QUERY, "review_prompt"),
    ("allow", "DELETE WHERE { ?s ?p ?o }", "blocked_query"),
    (RuntimeError("backend unavailable"), EXAMPLE_QUERY, "error"),
    ("allow", RuntimeError("generation failed"), "error"),
])
def test_real_workflow_gates(decision, query, status):
    classifier, generator = FakeClassifier(decision), FakeSparqlLLM(query)
    pipe = SparqlWorkflow(SystemOnePromptValidator(classifier), generator,
        StaticQueryAnalyzer(), CheckedQueryExecutor(generate()))
    result = asyncio.run(pipe.run(PromptRequest("count", "schema", "aggregates only")))
    assert result.status == status
    if status == "released":
        assert result.result["results"]["bindings"][0]["patients"]["value"] == "8"
    else:
        assert result.result is None
    assert len(generator.calls) == (1 if decision == "allow" else 0)


def test_delay_times_out_before_generation():
    classifier, generator = FakeClassifier("allow", delay=1), FakeSparqlLLM(EXAMPLE_QUERY)
    pipe = SparqlWorkflow(SystemOnePromptValidator(classifier), generator,
        StaticQueryAnalyzer(), CheckedQueryExecutor(generate()), model_timeout_seconds=0.01)
    result = asyncio.run(pipe.run(PromptRequest("p", "s", "policy")))
    assert result.status == "error" and result.error_type == "TimeoutError"
    assert len(classifier.calls) == 1 and generator.calls == []


@pytest.mark.parametrize("factory", [sequence, random_choice])
def test_empty_responses(factory):
    with pytest.raises(ValueError):
        factory([])
