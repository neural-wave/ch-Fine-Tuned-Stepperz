"""Cross-component behavior with scripted models and real local RDF checks."""
import asyncio
from dataclasses import replace
import json
from unittest.mock import AsyncMock, Mock

import pytest

from agent_orchestration import (
    CheckedQueryExecutor, Decision, FakeClassifier, FakeSparqlLLM, PromptRequest,
    SparqlWorkflow, StaticQueryAnalyzer, SystemOnePromptValidator,
)
from agent_orchestration.evaluation import EvaluationExpectation, SystemEvaluator, load_prompt_cases
from agent_orchestration.semantic import equivalent
from agent_orchestration.fakes import sequence
from sparql_analyzer.demo import EXAMPLE_QUERY
from sparql_analyzer.runtime import ResultBlocked
from tools.generate_synthetic_data import generate
from tools.generate_system_dataset import expected_count
from tests.paths import ROOT

pytestmark = pytest.mark.offline_workflow
CASES = load_prompt_cases(ROOT / "tests/fixtures/system/prompt_query_links.json")
REQUEST = PromptRequest("Count patients", "trusted schema", "aggregates only", "analyst")


def pipeline(decision="allow", response=EXAMPLE_QUERY):
    classifier, generator = FakeClassifier(decision), FakeSparqlLLM(response)
    analyzer, executor = StaticQueryAnalyzer(), CheckedQueryExecutor(generate())
    analyzer.run = Mock(wraps=analyzer.run)
    executor.run = AsyncMock(wraps=executor.run)
    workflow = SparqlWorkflow(SystemOnePromptValidator(classifier, min_allow_probability=0.8),
        generator, analyzer, executor)
    return workflow, classifier, generator


DECISIONS = [
    pytest.param(Decision("allow", 0.9), None, None, id="allow"),
    pytest.param("block", "blocked_prompt", None, id="block"),
    pytest.param("review", "review_prompt", None, id="review"),
    pytest.param(Decision("allow", 0.2), "review_prompt", None, id="uncertain-allow"),
    pytest.param("allow", "review_prompt", None, id="missing-probability"),
    pytest.param("unknown", "error", "ValueError", id="unknown-class"),
    pytest.param(123, "error", "TypeError", id="wrong-classifier-output"),
    pytest.param(RuntimeError("private classifier message"), "error", "RuntimeError", id="classifier-failure"),
]
GENERATIONS = [
    pytest.param(EXAMPLE_QUERY, "released", None, id="valid"),
    pytest.param("DELETE WHERE { ?s ?p ?o }", "blocked_query", None, id="forbidden"),
    pytest.param(EXAMPLE_QUERY.replace("BilledDiagnosis", "OncologyDiagnosis"), "blocked_runtime", "ResultBlocked", id="small-cohort"),
    pytest.param("SELECT WHERE {{{", "blocked_query", None, id="syntax-error"),
    pytest.param(" ", "error", "ValueError", id="empty-query"),
    pytest.param(123, "error", "TypeError", id="wrong-generator-output"),
    pytest.param(RuntimeError("private generator message"), "error", "RuntimeError", id="generator-failure"),
]


@pytest.mark.parametrize("decision,early_status,early_error", DECISIONS)
@pytest.mark.parametrize("response,query_status,query_error", GENERATIONS)
def test_gate_combinations(decision, early_status, early_error, response, query_status, query_error):
    pipe, classifier, generator = pipeline(decision, response)
    snapshot = pipe.executor.snapshot_id()
    outcome = asyncio.run(pipe.run(REQUEST))
    expected = early_status or query_status
    assert outcome.status == expected
    assert outcome.error_type == (early_error if early_status else query_error)
    assert len(classifier.calls) == 1
    assert len(generator.calls) == (0 if early_status else 1)
    reached_analysis = not early_status and query_status not in {"error"}
    assert pipe.analyzer.run.call_count == int(reached_analysis)
    reached_execution = not early_status and query_status in {"released", "blocked_runtime"}
    assert pipe.executor.run.await_count == int(reached_execution)
    expected_stage = "prompt_validation" if early_status else (
        "generation" if query_status == "error" else "execution" if reached_execution else "query_analysis")
    assert outcome.stage == expected_stage
    assert all(value >= 0 for value in outcome.timings.values())
    assert pipe.executor.snapshot_id() == snapshot
    assert "private classifier message" not in repr(outcome)
    assert "private generator message" not in repr(outcome)
    if expected == "released":
        assert outcome.result == expected_count(8)
    else:
        assert outcome.result is None
    if early_status:
        assert outcome.query is None and outcome.analysis is None


def test_context_is_preserved_and_stages_run_in_order():
    events = []
    def classify(request):
        events.append("classify")
        assert json.loads(request.state) == {
            "prompt": REQUEST.prompt, "schema": REQUEST.schema,
            "policy": REQUEST.policy, "permissions": REQUEST.permissions}
        return Decision("allow", 0.9)
    def generate_query(request):
        events.append("generate")
        assert (request.prompt, request.schema, request.policy, request.permissions) == (
            REQUEST.prompt, REQUEST.schema, REQUEST.policy, REQUEST.permissions)
        return EXAMPLE_QUERY
    pipe, _, _ = pipeline(classify, generate_query)
    analyze, execute = pipe.analyzer.run, pipe.executor.run
    def analyze_query(query):
        events.append("analyze")
        assert query == EXAMPLE_QUERY
        return analyze(query)
    async def execute_query(query):
        events.append("execute")
        assert query == EXAMPLE_QUERY
        return await execute(query)
    pipe.analyzer.run, pipe.executor.run = analyze_query, execute_query
    assert asyncio.run(pipe.run(REQUEST)).status == "released"
    assert events == ["classify", "generate", "analyze", "execute"]


def test_repeated_requests_do_not_consume_generation_after_prompt_block():
    pipe, _, generator = pipeline(sequence([
        Decision("allow", 0.9), "block", Decision("allow", 0.9), Decision("allow", 0.9)]),
        sequence([EXAMPLE_QUERY, RuntimeError("failure"), EXAMPLE_QUERY]))
    async def exercise():
        return [await pipe.run(replace(REQUEST, prompt=f"request {i}")) for i in range(4)]
    results = asyncio.run(exercise())
    assert [r.status for r in results] == ["released", "blocked_prompt", "error", "released"]
    assert [r.prompt for r in generator.calls] == ["request 0", "request 2", "request 3"]
    assert results[0].result == results[-1].result == expected_count(8)
    assert results[1].query is None and results[2].result is None


def test_concurrent_requests_keep_their_prompt_and_permissions():
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        async def respond(request):
            if request.prompt == "slow":
                assert request.permissions == "first analyst"
                entered.set()
                await release.wait()
                return EXAMPLE_QUERY
            assert request.prompt == "fast" and request.permissions == "second analyst"
            return "DELETE WHERE { ?s ?p ?o }"
        pipe, _, generator = pipeline(Decision("allow", 0.9), respond)
        slow = asyncio.create_task(pipe.run(replace(REQUEST, prompt="slow", permissions="first analyst")))
        await asyncio.wait_for(entered.wait(), 2)
        try:
            fast = await pipe.run(replace(REQUEST, prompt="fast", permissions="second analyst"))
        finally:
            release.set()
        first = await slow
        assert fast.status == "blocked_query" and first.status == "released"
        assert len(generator.calls) == 2 and pipe.executor.run.await_count == 1
    asyncio.run(exercise())


@pytest.mark.parametrize("cancel", [False, True], ids=["generation-timeout", "external-cancellation"])
def test_interrupted_generation_never_executes_and_next_request_recovers(cancel):
    async def exercise():
        entered, never = asyncio.Event(), asyncio.Event()
        async def respond(request):
            if request.prompt == "interrupt":
                entered.set()
                await never.wait()
            return EXAMPLE_QUERY
        pipe, _, _ = pipeline(Decision("allow", 0.9), respond)
        pipe.model_timeout_seconds = 1 if cancel else 0.03
        task = asyncio.create_task(pipe.run(replace(REQUEST, prompt="interrupt")))
        await asyncio.wait_for(entered.wait(), 2)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await task
            assert result.status == "error" and result.error_type == "TimeoutError"
        pipe.analyzer.run.assert_not_called()
        pipe.executor.run.assert_not_awaited()
        result = await pipe.run(REQUEST)
        assert result.status == "released" and pipe.executor.run.await_count == 1
    asyncio.run(exercise())


@pytest.mark.parametrize("stage", ["prompt_validation", "generation", "query_analysis", "execution"])
def test_runtime_block_exception_is_only_a_block_at_execution(stage):
    pipe, _, _ = pipeline(Decision("allow", 0.9))
    error = ResultBlocked("private execution message")
    if stage == "prompt_validation":
        pipe.prompt_validator.run = AsyncMock(side_effect=error)
    elif stage == "generation":
        pipe.generator.run = AsyncMock(side_effect=error)
    elif stage == "query_analysis":
        pipe.analyzer.run = Mock(side_effect=error)
    else:
        pipe.executor.run = AsyncMock(side_effect=error)
    result = asyncio.run(pipe.run(REQUEST))
    assert result.status == ("blocked_runtime" if stage == "execution" else "error")
    assert result.stage == stage and result.result is None
    assert "private execution message" not in repr(result)


@pytest.mark.parametrize("rename,mapping,match", [(False, {}, True), (True, {}, False), (True, {"total": "patients"}, True)])
def test_semantic_oracle_checks_aliases_after_real_execution(rename, mapping, match):
    case = CASES[0]
    query = case.read_reference(ROOT)
    if rename:
        query = query.replace("AS ?patients", "AS ?total")
    pipe, _, _ = pipeline(Decision("allow", 0.9), query)
    expected = EvaluationExpectation("fixture", pipe.executor.snapshot_id(), "released",
        expected_count(8), column_mapping=mapping)
    row = asyncio.run(SystemEvaluator().run(case, replace(REQUEST, prompt=case.prompt), pipe, expected))
    assert row["outcome"]["status"] == "released"
    assert row["semantic_match"] is match and row["passed"] is match


@pytest.mark.parametrize("patients,seed", [(18, 42), (24, 7), (30, 91)])
def test_corpus_with_classifier_that_incorrectly_allows_everything(patients, seed):
    """Even a permissive fake guard must not bypass downstream query checks."""
    from tools.generate_workflow_fixtures import generate as rich_fixture
    dataset, oracles = rich_fixture(patients, seed)
    references = {case.prompt: case.read_reference(ROOT) for case in CASES if case.reference_query}
    classifier = FakeClassifier("allow")
    generator = FakeSparqlLLM(lambda request: references[request.prompt])
    executor = CheckedQueryExecutor(dataset)
    executor.run = AsyncMock(wraps=executor.run)
    snapshot = executor.snapshot_id()
    pipe = SparqlWorkflow(SystemOnePromptValidator(classifier), generator, StaticQueryAnalyzer(), executor)
    async def exercise():
        for case in CASES:
            if case.reference_query is None:
                continue
            outcome = await pipe.run(replace(REQUEST, prompt=case.prompt))
            if case.expected_query_compliant:
                assert outcome.status == "released", case.id
                assert equivalent(oracles[case.group_id], outcome.result), case.id
            else:
                assert outcome.status == "blocked_query" and outcome.result is None, case.id
    asyncio.run(exercise())
    assert len(classifier.calls) == len(generator.calls) == len(references)
    assert executor.run.await_count == sum(case.expected_query_compliant is True for case in CASES)
    assert executor.snapshot_id() == snapshot


@pytest.mark.parametrize("flag", [1, "true", None, False])
def test_non_boolean_analysis_never_authorizes_execution(flag):
    pipe, _, _ = pipeline(Decision("allow", 0.9))
    pipe.analyzer.run = Mock(return_value={"is_compliant": flag})
    outcome = asyncio.run(pipe.run(REQUEST))
    assert outcome.status == "blocked_query" and outcome.result is None
    pipe.executor.run.assert_not_awaited()


def test_semantic_evaluation_rejects_snapshot_changes_during_execution():
    from rdflib import URIRef
    case = CASES[0]
    pipe, _, _ = pipeline(Decision("allow", 0.9), case.read_reference(ROOT))
    expected = EvaluationExpectation("fixture", pipe.executor.snapshot_id(), "released", expected_count(8))
    execute = pipe.executor.run
    async def execute_and_change_snapshot(query):
        result = await execute(query)
        pipe.executor.dataset.graph(URIRef("urn:changed")).add((URIRef("urn:s"), URIRef("urn:p"), URIRef("urn:o")))
        return result
    pipe.executor.run = execute_and_change_snapshot
    with pytest.raises(ValueError, match="Fixture changed"):
        asyncio.run(SystemEvaluator().run(case, replace(REQUEST, prompt=case.prompt), pipe, expected))
