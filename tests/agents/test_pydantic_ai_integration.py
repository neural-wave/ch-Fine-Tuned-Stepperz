"""Real PydanticAI serialization/structured-output tests, no inference API."""
import asyncio
import json

import pytest

pytest.importorskip("pydantic_ai", reason="Install the agents extra")
from pydantic_ai import Agent
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart, RetryPromptPart
from pydantic_ai.models import override_allow_model_requests

from agent_orchestration import (
    CheckedQueryExecutor, PromptRequest, PromptValidation, PydanticAIPromptValidator,
    PydanticAILLM, PydanticAISparqlLLM, SparqlRequest, SparqlResult,
    SparqlWorkflow, StaticQueryAnalyzer,
    FakeClassifier, FakeSparqlLLM, SystemOnePromptValidator,
)
from tools.evaluate_workflow import evaluate
from sparql_analyzer.demo import EXAMPLE_QUERY
from tools.generate_synthetic_data import generate

pytestmark = pytest.mark.offline_workflow


@pytest.fixture(autouse=True)
def prevent_real_model_requests():
    with override_allow_model_requests(False):
        yield


def test_text_adapter_with_actual_agent():
    adapter = PydanticAILLM(Agent(TestModel(custom_output_text="hello"), output_type=str))
    assert asyncio.run(adapter.run("test")) == "hello"


@pytest.mark.parametrize("feedback", [(), ({"attempt": 1, "query": "SELECT WHERE",
    "findings": [{"code": "SYNTAX", "reason": "Invalid query"}]},)])
def test_structured_generation_receives_all_fields(feedback):
    received = []
    def generate_query(messages, info):
        prompt = next(part.content for message in reversed(messages) for part in message.parts if isinstance(part, UserPromptPart))
        received.append(json.loads(prompt))
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"query": EXAMPLE_QUERY})])
    adapter = PydanticAISparqlLLM(Agent(FunctionModel(generate_query), output_type=SparqlResult))
    result = asyncio.run(adapter.run(SparqlRequest("count", "RDF schema", "only counts", "analyst", feedback)))
    assert result.query == EXAMPLE_QUERY
    assert received == [{"prompt": "count", "schema": "RDF schema", "policy": "only counts",
                         "permissions": "analyst", "feedback": list(feedback)}]


def test_actual_pydantic_agents_in_full_pipeline():
    guard = PydanticAIPromptValidator(Agent(TestModel(custom_output_args={
        "decision": "allow", "reason": "scripted", "probability": None,
    }), output_type=PromptValidation))
    generator = PydanticAISparqlLLM(Agent(TestModel(custom_output_args={"query": EXAMPLE_QUERY}), output_type=SparqlResult))
    pipe = SparqlWorkflow(guard, generator, StaticQueryAnalyzer(), CheckedQueryExecutor(generate()))
    result = asyncio.run(pipe.run(PromptRequest("count", "schema", "policy")))
    assert result.status == "released"
    assert result.result["results"]["bindings"][0]["patients"]["value"] == "8"


def test_offline_benchmark_uses_existing_corpus_and_three_fixtures():
    report = asyncio.run(evaluate(offline=True))
    assert report["metadata"]["mode"] == "scripted-pydanticai-TestModel"
    assert report["static_component"]["passed"] == report["static_component"]["cases"] == 34
    summary = report["system"]["summary"]
    assert summary["cases"] == summary["passed"] == 108
    assert summary["semantic_match"]["total"] == 39
    assert summary["errors"] == 0
    generation = report["generation_component"]["summary"]
    assert generation["cases"] == generation["passed"] == 39
    assert generation["prompt_match"]["total"] == 0


def test_generation_component_can_run_independently():
    report = asyncio.run(evaluate(offline=True, component="generation"))
    assert report["system"]["summary"]["cases"] == 0
    assert report["generation_component"]["summary"]["passed"] == 39


@pytest.mark.parametrize("final_query,status", [
    (EXAMPLE_QUERY, "released"),
    ("DELETE WHERE { ?s ?p ?o }", "blocked_query"),
    (" ", "error"),
])
def test_structured_output_retry_still_passes_through_query_gates(final_query, status):
    calls = []
    def respond(messages, info):
        calls.append(messages)
        if len(calls) == 1:
            arguments = {"query": {"invalid": "type"}}
        else:
            assert any(isinstance(part, RetryPromptPart) for m in messages for part in m.parts)
            arguments = {"query": final_query}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, arguments)])
    generator = PydanticAISparqlLLM(Agent(FunctionModel(respond), output_type=SparqlResult, retries=1))
    pipe = SparqlWorkflow(SystemOnePromptValidator(FakeClassifier("allow")), generator,
        StaticQueryAnalyzer(), CheckedQueryExecutor(generate()))
    result = asyncio.run(pipe.run(PromptRequest("count", "schema", "policy")))
    assert result.status == status and len(calls) == 2
    assert (result.result is not None) == (status == "released")


def test_classifier_validation_retry_can_end_in_block_without_generation():
    calls = []
    def respond(messages, info):
        calls.append(messages)
        decision = "invalid" if len(calls) == 1 else "block"
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
            {"decision": decision, "reason": "scripted", "probability": None})])
    guard = PydanticAIPromptValidator(Agent(FunctionModel(respond), output_type=PromptValidation, retries=1))
    generator = FakeSparqlLLM(EXAMPLE_QUERY)
    pipe = SparqlWorkflow(guard, generator, StaticQueryAnalyzer(), CheckedQueryExecutor(generate()))
    result = asyncio.run(pipe.run(PromptRequest("count", "schema", "policy")))
    assert result.status == "blocked_prompt" and len(calls) == 2
    assert generator.calls == []


def test_exhausted_structured_output_retries_are_an_error():
    calls = []
    def respond(messages, info):
        calls.append(messages)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"missing_query": True})])
    generator = PydanticAISparqlLLM(Agent(FunctionModel(respond), output_type=SparqlResult, retries=1))
    pipe = SparqlWorkflow(SystemOnePromptValidator(FakeClassifier("allow")), generator,
        StaticQueryAnalyzer(), CheckedQueryExecutor(generate()))
    result = asyncio.run(pipe.run(PromptRequest("count", "schema", "policy")))
    assert result.status == "error" and result.stage == "generation"
    assert result.error_type == "UnexpectedModelBehavior" and len(calls) == 2
    assert result.analysis is None and result.result is None
