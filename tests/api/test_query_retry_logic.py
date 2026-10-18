"""Deterministic repair state transitions, with concurrency replaced by inline doubles.

These tests need no event loop or sockets; HTTP/concurrency has separate tests.
"""
from contextlib import nullcontext

import pytest

from api import service as service_module
from agent_orchestration import workflow as workflow_module
from agent_orchestration.models import TokenUsage
from agent_orchestration.query_retry import repair_request, validate_query_retries
from agent_orchestration.validation import StaticQueryAnalyzer
from tests.api.test_query_retry import BAD, EXAMPLE_QUERY, scripted

pytestmark = pytest.mark.offline_workflow


def inline(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    finally:
        coroutine.close()
    raise AssertionError("The test double unexpectedly suspended")


@pytest.fixture(autouse=True)
def inline_concurrency(monkeypatch):
    async def call(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr(service_module.asyncio, "to_thread", call)
    monkeypatch.setattr(workflow_module.asyncio, "timeout", lambda seconds: nullcontext())


@pytest.mark.parametrize("budget", [0, 1, 3])
def test_exhaustion_retains_each_failure_and_sums_all_generations(budget):
    translator, requests = scripted([BAD] * (budget + 1), retries=budget)
    result = inline(translator.run("count"))
    assert result["is_compliant"] is False and len(requests) == budget + 1
    assert result["tokens_consumed"] == 7 + 15 * (budget + 1)
    assert result["analytics"]["query_retry"]["stop_reason"] == "retry_limit"
    assert all(attempt["failed_checks"] == ["SYNTAX"] for attempt in result["analytics"]["query_attempts"])
    assert len(requests[-1].feedback) == budget


def test_success_stops_repair_and_preserves_original_request():
    translator, requests = scripted([BAD, EXAMPLE_QUERY])
    result = inline(translator.run("count"))
    assert len(requests) == 2 and result["is_compliant"] is True
    assert result["tokens_consumed"] == 37
    assert requests[1].prompt == requests[0].prompt == "count"
    assert requests[1].schema == requests[0].schema
    assert requests[1].policy == requests[0].policy and requests[1].permissions == requests[0].permissions
    assert requests[1].feedback[0]["query"] == BAD
    assert result["analytics"]["query_attempts"][1]["failed_checks"] == []


@pytest.mark.parametrize("decision", ["block", "review"])
def test_non_allowed_prompts_are_never_repaired(decision):
    translator, requests = scripted([BAD], decision=decision)
    result = inline(translator.run("original"))
    assert result["is_compliant"] is False and len(requests) == 1
    assert result["analytics"]["query_retry"]["stop_reason"] == "prompt_not_allowed"


def test_partial_usage_and_completed_attempt_survive_retry_failure():
    error = ConnectionError("provider detail")
    error.token_usage = TokenUsage(3, 1, source="reported", complete=False)
    translator, requests = scripted([BAD, error])
    with pytest.raises(ConnectionError) as failure:
        inline(translator.run("count"))
    analytics = failure.value.execution_analytics
    assert analytics["failed_stage"] == "generation_retry_1"
    assert analytics["token_usage"]["known_total_tokens"] == 26
    assert analytics["token_usage"]["total_tokens"] is None
    assert analytics["query_attempts"][0]["failed_checks"] == ["SYNTAX"]
    assert analytics["query_attempts"][1]["status"] == "error"


@pytest.mark.parametrize("bad", [-1, True, "2", None, 1.5])
def test_configuration_rejects_invalid_retry_budgets(bad):
    with pytest.raises(ValueError, match="query_retries"):
        validate_query_retries(bad)


def test_execution_workflow_only_executes_after_static_success():
    translator, requests = scripted([BAD, EXAMPLE_QUERY])
    executions = []
    class Executor:
        async def run(self, query):
            executions.append(query)
            return {"checked": True}
    pipe = workflow_module.SparqlWorkflow(translator.guard, translator.generator, StaticQueryAnalyzer(),
                                         Executor(), query_retries=2)
    result = inline(pipe.run(translator.template))
    assert result.status == "released" and executions == [EXAMPLE_QUERY]
    assert result.analytics["token_usage"]["total_tokens"] == 37
    assert len(requests) == 2 and len(requests[1].feedback) == 1


def test_execution_workflow_keeps_failed_retry_usage():
    error = ConnectionError("private")
    error.token_usage = TokenUsage(2, 0, source="reported", complete=False)
    translator, _ = scripted([BAD, error])
    pipe = workflow_module.SparqlWorkflow(translator.guard, translator.generator, StaticQueryAnalyzer(), query_retries=1)
    result = inline(pipe.run(translator.template))
    assert result.status == "error" and result.stage == "generation_retry_1"
    assert result.analytics["token_usage"]["known_total_tokens"] == 24
    assert result.analytics["query_attempts"][1]["status"] == "error"


def test_feedback_cannot_modify_the_recorded_findings():
    translator, _ = scripted([BAD])
    report = StaticQueryAnalyzer().run(BAD)
    request = repair_request(translator.template, [{"attempt": 1, "query": BAD, "analysis": report}])
    request.feedback[0]["findings"][0]["reason"] = "changed"
    assert report["findings"][0]["reason"] != "changed"


def test_request_histories_are_isolated_and_guard_runs_only_once_per_request():
    translator, requests = scripted([BAD, EXAMPLE_QUERY, BAD, EXAMPLE_QUERY])
    guard = translator.guard.run_with_usage
    calls = []
    async def classify(request):
        calls.append(request)
        return await guard(request)
    translator.guard.run_with_usage = classify
    first = inline(translator.run("first"))
    second = inline(translator.run("second"))
    assert len(calls) == 2 and all(not request.feedback for request in calls)
    assert requests[2].prompt == "second" and requests[2].feedback == ()
    assert len(requests[3].feedback) == 1
    assert len(first["query_attempts"]) == len(second["query_attempts"]) == 2


def test_runtime_rejection_does_not_trigger_query_repair():
    from sparql_analyzer.runtime import ResultBlocked
    translator, requests = scripted([EXAMPLE_QUERY])
    class Executor:
        async def run(self, query):
            raise ResultBlocked("blocked by runtime")
    pipe = workflow_module.SparqlWorkflow(translator.guard, translator.generator, StaticQueryAnalyzer(),
                                         Executor(), query_retries=2)
    result = inline(pipe.run(translator.template))
    assert result.status == "blocked_runtime" and len(requests) == 1


def test_analysis_failure_never_associates_old_report_with_new_query(monkeypatch):
    translator, _ = scripted([BAD, EXAMPLE_QUERY])
    validate = service_module.validate
    def analyze(query):
        if query == EXAMPLE_QUERY:
            raise RuntimeError("checker failed on second query")
        return validate(query)
    monkeypatch.setattr(service_module, "validate", analyze)
    with pytest.raises(RuntimeError) as failure:
        inline(translator.run("count"))
    analytics = failure.value.execution_analytics
    assert failure.value.generated_query == EXAMPLE_QUERY and analytics["query_analysis"] is None
    assert analytics["query_attempts"][0]["analysis"]["status"] == "unsupported"
    assert analytics["query_attempts"][1]["analysis"] is None
