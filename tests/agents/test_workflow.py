import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agent_orchestration import (
    CallableSystemOneModel, CheckedQueryExecutor, Decision, DecisionRequest,
    PromptRequest, PromptValidation, SemanticEvaluator, SparqlResult,
    SparqlWorkflow, StaticQueryAnalyzer, SystemOnePromptValidator,
)
from agent_orchestration.evaluation import (
    EvaluationExpectation, GenerationEvaluator, SystemEvaluator, load_prompt_cases, summarize,
)
from agent_orchestration.semantic import equivalent
from sparql_analyzer.demo import EXAMPLE_QUERY
from sparql_analyzer.runtime import ResultBlocked
from tools.generate_synthetic_data import generate
from tools.generate_system_dataset import expected_count
from tests.paths import ROOT

pytestmark = pytest.mark.offline_workflow

LINKS = ROOT / "tests/fixtures/system/prompt_query_links.json"


def request():
    return PromptRequest("Count patients", "schema", "aggregates only", "analyst")


def workflow(*, decision="allow", query=EXAMPLE_QUERY, executor=None):
    guard = SimpleNamespace(run=AsyncMock(return_value=PromptValidation(decision, "test")))
    generator = SimpleNamespace(run=AsyncMock(return_value=SparqlResult(query)))
    analyzer = StaticQueryAnalyzer()
    return SparqlWorkflow(guard, generator, analyzer,
                          executor or CheckedQueryExecutor(generate()))


@pytest.mark.parametrize("decision,status", [("block", "blocked_prompt"), ("review", "review_prompt")])
def test_prompt_stops_generation(decision, status):
    pipe = workflow(decision=decision)
    result = asyncio.run(pipe.run(request()))
    assert result.status == status
    assert result.query is None and result.result is None
    pipe.generator.run.assert_not_awaited()


def test_real_analyzer_stops_executor():
    executor = SimpleNamespace(run=AsyncMock())
    pipe = workflow(query="DELETE WHERE { ?s ?p ?o }", executor=executor)
    result = asyncio.run(pipe.run(request()))
    assert result.status == "blocked_query" and result.result is None
    executor.run.assert_not_awaited()


def test_real_runtime_suppresses_small_cohort():
    pipe = workflow(query=EXAMPLE_QUERY.replace("BilledDiagnosis", "OncologyDiagnosis"))
    result = asyncio.run(pipe.run(request()))
    assert result.status == "blocked_runtime" and result.result is None


def test_context_reaches_generation_and_result_is_released():
    pipe = workflow()
    result = asyncio.run(pipe.run(request()))
    assert result.status == "released"
    assert equivalent(expected_count(8), result.result)
    generated_request = pipe.generator.run.call_args.args[0]
    assert generated_request.permissions == "analyst"
    assert generated_request.policy == "aggregates only"
    assert set(result.timings) == {"prompt_validation", "generation", "query_analysis", "execution"}


@pytest.mark.parametrize("stage", ["prompt_validator", "generator", "analyzer", "executor"])
def test_errors_are_not_successful_security_blocks(stage):
    pipe = workflow()
    component = getattr(pipe, stage)
    component.run = Mock(side_effect=RuntimeError("private provider details")) if stage == "analyzer" else AsyncMock(side_effect=RuntimeError("private provider details"))
    result = asyncio.run(pipe.run(request()))
    assert result.status == "error" and result.result is None
    assert result.error_type == "RuntimeError"
    assert "private provider details" not in str(result)


def test_timeout_prevents_generation():
    async def slow(_):
        await asyncio.sleep(1)
    pipe = workflow()
    pipe.model_timeout_seconds = 0.01
    pipe.prompt_validator.run = slow
    result = asyncio.run(pipe.run(request()))
    assert result.status == "error" and result.error_type == "TimeoutError"
    pipe.generator.run.assert_not_awaited()


def test_native_validator_passes_context_and_abstains():
    backend = SimpleNamespace(run=AsyncMock(return_value=Decision("allow", 0.4)))
    validator = SystemOnePromptValidator(backend, min_allow_probability=0.8)
    result = asyncio.run(validator.run(request()))
    assert result.decision == "review"
    state = json.loads(backend.run.call_args.args[0].state)
    assert state["permissions"] == "analyst"
    assert state["prompt"] == request().prompt


def test_native_unknown_choice_is_error():
    backend = SimpleNamespace(run=AsyncMock(return_value=Decision("unexpected")))
    with pytest.raises(ValueError, match="unknown"):
        asyncio.run(SystemOnePromptValidator(backend).run(request()))


@pytest.mark.parametrize("probability", [None, 0.1, 0.9])
def test_native_allow_threshold(probability):
    backend = SimpleNamespace(run=AsyncMock(return_value=Decision("allow", probability)))
    result = asyncio.run(SystemOnePromptValidator(backend, min_allow_probability=0.8).run(request()))
    assert result.decision == ("allow" if probability == 0.9 else "review")


def test_native_callable_sync_and_async():
    async def async_predict(_):
        return Decision("block", 0.9)
    for predict in (lambda _: Decision("block", 0.9), async_predict):
        result = asyncio.run(CallableSystemOneModel(predict).run(DecisionRequest("s", "q", {"allow": "a", "block": "b"})))
        assert result.choice == "block"
    with pytest.raises(ValueError):
        asyncio.run(CallableSystemOneModel(lambda _: Decision("invalid")).run(DecisionRequest("s", "q", {"allow": "a", "block": "b"})))


def test_semantic_aliases_order_and_invalid_inputs():
    evaluator = SemanticEvaluator()
    expected = expected_count(8)
    actual = {"head": {"vars": ["metric"]}, "results": {"bindings": [{"metric": expected["results"]["bindings"][0]["patients"]}]}}
    assert evaluator.run(expected, actual).status == "different"
    assert evaluator.run(expected, actual, column_mapping={"metric": "patients"}).status == "match"
    assert evaluator.run(expected, {}).status == "error"
    assert evaluator.run(None, expected).status == "not_evaluated"
    bad = {"head": {"vars": ["x"]}, "results": {"bindings": [{"x": {"type": "bnode", "value": "a"}}]}}
    assert evaluator.run(bad, bad).status == "unsupported"
    left = expected_count(8)
    left["results"]["bindings"] += expected_count(9)["results"]["bindings"]
    reversed_rows = {"head": left["head"], "results": {"bindings": list(reversed(left["results"]["bindings"]))}}
    assert evaluator.run(left, reversed_rows).status == "match"
    assert evaluator.run(left, reversed_rows, ordered=True).status == "different"


@pytest.mark.parametrize("case", load_prompt_cases(LINKS), ids=lambda case: case.id)
def test_existing_query_links(case):
    query = case.read_reference(ROOT)
    if query is not None:
        assert StaticQueryAnalyzer().run(query)["is_compliant"] == case.expected_query_compliant


def test_changed_reference_requires_annotation_review():
    case = replace(load_prompt_cases(LINKS)[0], query_sha256="0" * 64)
    with pytest.raises(ValueError, match="Reference changed"):
        case.read_reference(ROOT)
    with pytest.raises(ValueError, match="outside"):
        replace(case, reference_query="../outside.rq").read_reference(ROOT)


def test_semantically_wrong_but_released_is_a_failed_system_test():
    case = load_prompt_cases(LINKS)[0]
    pipe = workflow(query=case.read_reference(ROOT).replace("COUNT(DISTINCT ?g)", "COUNT(?dx)"))
    expectation = EvaluationExpectation("fixture", pipe.executor.snapshot_id(), "released", expected_count(8))
    outcome = asyncio.run(SystemEvaluator().run(case, replace(request(), prompt=case.prompt), pipe, expectation))
    assert outcome["status_match"] and outcome["prompt_match"]
    assert outcome["semantic"]["status"] == "different"
    assert not outcome["passed"]
    summary = summarize([outcome])
    assert summary["semantic_match"] == {"correct": 0, "total": 1, "accuracy": 0.0}


def test_wrong_snapshot_is_rejected_before_generation():
    case = load_prompt_cases(LINKS)[0]
    pipe = workflow()
    with pytest.raises(ValueError, match="snapshot"):
        asyncio.run(SystemEvaluator().run(case, replace(request(), prompt=case.prompt), pipe,
                    EvaluationExpectation("wrong", "0" * 64, "released", expected_count(8))))
    pipe.generator.run.assert_not_awaited()


def test_generation_evaluation_requires_oracle_and_curated_prompt():
    cases = load_prompt_cases(LINKS)
    pipe = workflow()
    evaluator = GenerationEvaluator()
    expectation = EvaluationExpectation("fixture", pipe.executor.snapshot_id(), "released")
    for case in (cases[0], cases[1]):
        with pytest.raises(ValueError):
            asyncio.run(evaluator.run(case, replace(request(), prompt=case.prompt),
                        pipe.generator, pipe.analyzer, pipe.executor, expectation))


@pytest.mark.parametrize("patients,seed", [(18, 42), (24, 7), (30, 91)])
def test_existing_positive_queries_against_independent_fixture_oracles(patients, seed):
    from tools.generate_workflow_fixtures import generate as rich_fixture
    dataset, oracles = rich_fixture(patients, seed)
    for case in load_prompt_cases(LINKS):
        if case.expected_prompt_decision != "allow":
            continue
        query = case.read_reference(ROOT)
        # Trusted versioned references only, never arbitrary model output.
        raw_result = json.loads(dataset.query(query).serialize(format="json"))
        assert equivalent(oracles[case.group_id], raw_result), case.id
        checked = asyncio.run(CheckedQueryExecutor(dataset).run(query))
        assert equivalent(oracles[case.group_id], checked), case.id
