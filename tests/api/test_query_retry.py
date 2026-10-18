"""Bounded static-feedback repair through the real HTTP endpoint, no inference."""
import asyncio

from fastapi.testclient import TestClient
import pytest

from api.server import create_app
from agent_orchestration.models import ModelResponse, SparqlResult, TokenUsage
from agent_orchestration.workflow import SparqlWorkflow
from agent_orchestration.validation import StaticQueryAnalyzer
from tests.api.test_server import EXAMPLE_QUERY, service

pytestmark = pytest.mark.offline_workflow
BAD = "SELECT WHERE"


def scripted(queries, *, retries=2, decision="allow"):
    translator = service(decision=decision)
    translator.query_retries = retries
    requests = []
    responses = iter(queries)

    async def generate(request):
        requests.append(request)
        value = next(responses)
        if isinstance(value, BaseException):
            raise value
        return ModelResponse(SparqlResult(value), TokenUsage(10, 5, model="scripted", source="reported"))

    translator.generator.run_with_usage = generate
    return translator, requests


def test_failed_query_is_repaired_with_feedback_and_all_tokens_counted():
    translator, requests = scripted([BAD, EXAMPLE_QUERY])
    with TestClient(create_app(translator)) as client:
        response = client.post("/study/nl-to-sparql", json={"text": "Count patients"})
    assert response.status_code == 200
    result = response.json()
    assert result["is_compliant"] is True and result["sparql_query"] == EXAMPLE_QUERY
    assert result["tokens_consumed"] == 37  # guard 7 + two generations of 15
    assert len(requests) == 2 and requests[0].feedback == ()
    assert requests[1].prompt == requests[0].prompt == "Count patients"
    assert requests[1].policy == requests[0].policy and requests[1].permissions == requests[0].permissions
    assert requests[1].schema == requests[0].schema
    feedback, = requests[1].feedback
    assert feedback["query"] == BAD and feedback["findings"] and feedback["status"] == "unsupported"
    first, final = result["query_attempts"]
    assert first["failed_checks"] == ["SYNTAX"] and final["failed_checks"] == []
    assert first["analysis"]["is_compliant"] is False and final["analysis"]["is_compliant"] is True
    assert result["analytics"]["query_retry"] == {"configured_retries": 2, "retries_used": 1, "stop_reason": "accepted"}
    assert result["analytics"]["token_usage"]["by_stage"]["generation_retry_1"]["total_tokens"] == 15


@pytest.mark.parametrize("retries", [0, 1, 3])
def test_retry_budget_is_exact_and_exhaustion_returns_last_query(retries):
    translator, requests = scripted([BAD] * (retries + 1), retries=retries)
    with TestClient(create_app(translator)) as client:
        result = client.post("/study/nl-to-sparql", json={"text": "count"}).json()
    assert len(requests) == retries + 1 and result["is_compliant"] is False
    assert result["tokens_consumed"] == 7 + 15 * (retries + 1)
    assert result["analytics"]["query_retry"]["stop_reason"] == "retry_limit"
    assert len(result["analytics"]["query_attempts"]) == retries + 1
    assert len(requests[-1].feedback) == retries


@pytest.mark.parametrize("decision", ["block", "review"])
def test_prompt_denial_is_not_repaired_or_overridden(decision):
    translator, requests = scripted([BAD], decision=decision)
    with TestClient(create_app(translator)) as client:
        result = client.post("/study/nl-to-sparql", json={"text": "original"}).json()
    assert len(requests) == 1 and result["is_compliant"] is False
    assert result["analytics"]["query_retry"]["stop_reason"] == "prompt_not_allowed"


def test_second_call_failure_preserves_first_analysis_and_partial_consumption():
    error = ConnectionError("private provider details")
    error.token_usage = TokenUsage(3, 1, model="failed", source="reported", complete=False)
    translator, requests = scripted([BAD, error])
    with TestClient(create_app(translator)) as client:
        response = client.post("/study/nl-to-sparql", json={"text": "count"})
    assert response.status_code == 502 and "private provider details" not in response.text
    analytics = response.json()["analytics"]
    assert analytics["failed_stage"] == "generation_retry_1"
    assert analytics["token_usage"]["known_total_tokens"] == 26
    assert analytics["token_usage"]["total_tokens"] is None
    assert analytics["query_attempts"][0]["failed_checks"] == ["SYNTAX"]
    assert analytics["query_attempts"][1]["status"] == "error"
    assert analytics["query_attempts"][1]["token_usage"]["input_tokens"] == 3


def test_success_on_first_call_does_not_spend_remaining_retries():
    translator, requests = scripted([EXAMPLE_QUERY])
    with TestClient(create_app(translator)) as client:
        result = client.post("/nl-to-sparql", json={"text": "count"}).json()
    assert len(requests) == 1 and len(result["query_attempts"]) == 1
    assert result["tokens_consumed"] == 22


def test_timeout_during_repair_retains_the_first_attempt(monkeypatch):
    from api import server
    original_timeout = asyncio.timeout
    deadlines = []

    def controlled_timeout(seconds):
        deadline = original_timeout(None)
        deadlines.append(deadline)
        return deadline

    monkeypatch.setattr(server.asyncio, "timeout", controlled_timeout)
    translator, _ = scripted([BAD])
    generate = translator.generator.run_with_usage
    calls = 0

    async def delayed(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return await generate(request)
        deadlines[-1].reschedule(asyncio.get_running_loop().time())
        await asyncio.Event().wait()

    translator.generator.run_with_usage = delayed
    with TestClient(create_app(translator)) as client:
        response = client.post("/study/nl-to-sparql", json={"text": "count"})
    assert response.status_code == 504
    analytics = response.json()["analytics"]
    assert analytics["failed_stage"] == "generation_retry_1"
    assert analytics["token_usage"]["known_total_tokens"] == 22
    assert analytics["query_attempts"][0]["analysis"]["status"] == "unsupported"
    assert analytics["query_attempts"][1]["status"] == "error"


@pytest.mark.parametrize("invalid", [-1, True, 1.5, "2", None])
def test_invalid_retry_configuration_is_rejected(invalid):
    from api.service import TranslationService
    translator = service()
    with pytest.raises(ValueError, match="query_retries"):
        TranslationService(translator.guard, translator.generator, schema="schema", policy="policy", query_retries=invalid)


def test_execution_workflow_uses_same_feedback_and_only_runs_accepted_query():
    translator, requests = scripted([BAD, EXAMPLE_QUERY])
    executed = []

    class Executor:
        async def run(self, query):
            executed.append(query)
            return {"result": "checked"}

    pipe = SparqlWorkflow(translator.guard, translator.generator, StaticQueryAnalyzer(), Executor(), query_retries=2)
    result = asyncio.run(pipe.run(translator.template))
    assert result.status == "released" and executed == [EXAMPLE_QUERY]
    assert len(requests) == 2 and requests[1].feedback[0]["query"] == BAD
    assert result.analytics["token_usage"]["total_tokens"] == 37
    assert result.analytics["query_attempts"][0]["failed_checks"] == ["SYNTAX"]


def test_execution_workflow_exhaustion_never_calls_executor():
    translator, requests = scripted([BAD, BAD])
    pipe = SparqlWorkflow(translator.guard, translator.generator, StaticQueryAnalyzer(), query_retries=1)
    result = asyncio.run(pipe.run(translator.template))
    assert result.status == "blocked_query" and len(requests) == 2
    assert result.analytics["query_retry"]["stop_reason"] == "retry_limit"
