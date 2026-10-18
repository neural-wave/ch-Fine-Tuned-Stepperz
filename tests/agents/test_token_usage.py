"""Token accounting across model contracts, backends, retries and early exits."""
import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from agent_orchestration import (
    CallableSystemOneModel, Decision, DecisionRequest, FakeClassifier, FakeLLM,
    FakeSparqlLLM, LLM, ModelResponse, PromptRequest, SparqlRequest, SparqlResult,
    SparqlWorkflow, StaticQueryAnalyzer, SystemOnePromptValidator, TokenUsage,
    tokenizer_counter,
)
from agent_orchestration.models import summarize_usage
from sparql_analyzer.demo import EXAMPLE_QUERY

pytestmark = pytest.mark.offline_workflow
REQUEST = PromptRequest("Count patients", "schema", "aggregate only")


@pytest.mark.parametrize("threshold,expected", [(None, "allow"), (.9, "review")])
def test_native_prompt_adapter_preserves_backend_metadata(threshold, expected):
    response = ModelResponse(Decision("allow", .8), TokenUsage(7, 0, source="reported"),
                             {"backend": "scripted-native"})
    guard = SystemOnePromptValidator(CallableSystemOneModel(lambda request: response),
                                    min_allow_probability=threshold)
    result = asyncio.run(guard.run_with_usage(REQUEST))
    assert result.output.decision == expected
    assert result.metadata == {"backend": "scripted-native"}
    assert result.usage == response.usage


@pytest.mark.parametrize("kwargs", [
    {"input_tokens": -1}, {"output_tokens": 1.5}, {"input_tokens": True},
    {"input_tokens": 2, "output_tokens": 3, "total_tokens": 4, "source": "reported"},
    {"source": "guess"}, {"complete": True}, {"input_tokens": 3},
])
def test_invalid_usage_is_rejected(kwargs):
    with pytest.raises(ValueError):
        TokenUsage(**kwargs)


@pytest.mark.parametrize("raw", [
    {"input_tokens": 10, "output_tokens": 3},
    {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    {"prompt_eval_count": 10, "eval_count": 3},
    SimpleNamespace(input_tokens=10, output_tokens=3, total_tokens=13),
])
def test_provider_field_aliases(raw):
    usage = TokenUsage.from_backend(raw, model="chosen")
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (10, 3, 13)
    assert usage.complete and usage.source == "reported" and usage.model == "chosen"


def test_cache_and_reasoning_are_subsets_not_extra_total_tokens():
    usage = TokenUsage.from_backend({"prompt_tokens": 100, "completion_tokens": 20,
        "prompt_tokens_details": {"cached_tokens": 70},
        "completion_tokens_details": {"reasoning_tokens": 8}})
    assert usage.total_tokens == 120
    assert usage.cache_read_tokens == 70 and usage.reasoning_tokens == 8


def test_unknown_and_partial_usage_are_not_silently_zero():
    summary = summarize_usage({"classifier": TokenUsage(),
                               "generator": TokenUsage(10, 3, source="reported")})
    assert summary["total_tokens"] is None and not summary["complete"]
    assert summary["known_total_tokens"] == 13
    partial = summarize_usage({"generator": TokenUsage(10, 3, source="reported", complete=False)})
    assert partial["total_tokens"] is None and partial["known_total_tokens"] == 13
    inputs_only = summarize_usage({"classifier": TokenUsage(input_tokens=8, source="reported")})
    assert inputs_only["total_tokens"] is None and inputs_only["known_total_tokens"] == 8


def test_text_contract_supports_optional_tokenizer_without_changing_run():
    class TextModel(LLM):
        async def run(self, request):
            return "one answer"
    class Tokenizer:
        def encode(self, text, *, add_special_tokens):
            return [1] * (len(text.split()) + int(add_special_tokens))
    model = TextModel(token_counter=tokenizer_counter(Tokenizer(), model="custom"))
    result = asyncio.run(model.run_with_usage("one question"))
    assert result.output == "one answer"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (3, 2)
    assert result.usage.source == "estimated"
    assert asyncio.run(model.run("one question")) == "one answer"
    assert asyncio.run(TextModel().run_with_usage("question")).usage.total_tokens is None


def test_fake_text_uses_no_real_tokens_and_can_script_usage():
    assert asyncio.run(FakeLLM("answer").run_with_usage("prompt")).usage.total_tokens == 0
    usage = TokenUsage(5, 2, source="simulated")
    assert asyncio.run(FakeLLM("answer", usage=usage).run_with_usage("prompt")).usage == usage


def test_native_classifier_accepts_reported_usage_or_tokenizer():
    request = DecisionRequest("some state", "decide", {"allow": "yes", "block": "no"})
    usage = TokenUsage(19, 0, model="native", source="reported", requests=1)
    model = CallableSystemOneModel(lambda _: ModelResponse(Decision("allow", .8), usage))
    response = asyncio.run(model.run_with_usage(request))
    assert response.output.choice == "allow" and response.usage == usage
    assert asyncio.run(model.run(request)) == Decision("allow", .8)
    fallback = CallableSystemOneModel(lambda _: Decision("allow"),
                                     token_counter=lambda *_: TokenUsage(7, 0, source="estimated"))
    assert asyncio.run(fallback.run_with_usage(request)).usage.total_tokens == 7


@pytest.mark.parametrize("decision,status", [("allow", "query_ready"), ("block", "blocked_prompt"),
                                               ("review", "review_prompt")])
def test_workflow_counts_only_the_models_that_ran(decision, status):
    guard = SystemOnePromptValidator(FakeClassifier(decision, usage=TokenUsage(10, 0, source="simulated")))
    generator = FakeSparqlLLM(EXAMPLE_QUERY, usage=TokenUsage(20, 5, source="simulated"))
    workflow = SparqlWorkflow(guard, generator, StaticQueryAnalyzer())
    result = asyncio.run(workflow.run(REQUEST, execute=False))
    tokens = result.analytics["token_usage"]
    assert result.status == status
    assert tokens["complete"]
    assert tokens["total_tokens"] == (35 if decision == "allow" else 10)
    assert ("generation" in tokens["by_stage"]) == (decision == "allow")
    assert asdict(result)["analytics"]["token_usage"] == tokens


def test_unknown_guard_usage_keeps_known_generation_counts_visible():
    from agent_orchestration.validation import PromptValidation
    async def validate(_):
        return PromptValidation("allow", "legacy backend")
    workflow = SparqlWorkflow(SimpleNamespace(run=validate),
        FakeSparqlLLM(EXAMPLE_QUERY, usage=TokenUsage(20, 5, source="simulated")), StaticQueryAnalyzer())
    tokens = asyncio.run(workflow.run(REQUEST, execute=False)).analytics["token_usage"]
    assert tokens["total_tokens"] is None and tokens["known_total_tokens"] == 25
    assert not tokens["complete"]


def test_laya_reports_input_tokens_and_no_generated_output_even_on_truncation():
    from agent_orchestration.adapters.laya import laya_validator
    for truncated in (False, True):
        backend = SimpleNamespace(predict=lambda *a, **k: {
            "usage": {"input_tokens": 83, "output_tokens": 0, "truncated": truncated},
            "answers": {"decision": {"choice": "allow", "low_confidence": True}}})
        guard = laya_validator(backend, model_id="laya-test")
        result = asyncio.run(SparqlWorkflow(guard, FakeSparqlLLM(EXAMPLE_QUERY), StaticQueryAnalyzer()).run(
            REQUEST, execute=False))
        tokens = result.analytics["token_usage"]
        assert tokens["total_tokens"] == 83
        assert tokens["by_stage"]["prompt_validation"]["output_tokens"] == 0
        assert result.status == ("error" if truncated else "review_prompt")


def test_concurrent_reuse_has_independent_usage():
    async def predict(request):
        await asyncio.sleep(.01 if request.state == "slow" else 0)
        return ModelResponse(Decision("allow"), TokenUsage(
            len(request.state), 0, source="reported"))
    model = CallableSystemOneModel(predict)
    async def exercise():
        return await asyncio.gather(*(model.run_with_usage(DecisionRequest(
            state, "decide", {"allow": "yes", "block": "no"})) for state in ("slow", "fastest")))
    responses = asyncio.run(exercise())
    assert [response.usage.total_tokens for response in responses] == [4, 7]


def test_pydantic_retry_counts_all_responses_without_polluting_output_schema():
    pytest.importorskip("pydantic_ai")
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelResponse as AgentResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.usage import RequestUsage
    from agent_orchestration import PydanticAISparqlLLM
    calls = []
    def respond(messages, info):
        calls.append(messages)
        assert set(info.output_tools[0].parameters_json_schema["properties"]) == {"query"}
        args = {"invalid": "retry"} if len(calls) == 1 else {"query": EXAMPLE_QUERY}
        return AgentResponse(parts=[ToolCallPart(info.output_tools[0].name, args)],
                             usage=RequestUsage(input_tokens=11, output_tokens=4))
    adapter = PydanticAISparqlLLM(Agent(FunctionModel(respond), output_type=SparqlResult, retries=1))
    response = asyncio.run(adapter.run_with_usage(REQUEST))
    assert response.usage.total_tokens == 30 and response.usage.requests == 2
    assert response.output.query == EXAMPLE_QUERY
    again = asyncio.run(adapter.run_with_usage(REQUEST))
    assert again.usage.total_tokens == 15 and again.usage.requests == 1


@pytest.mark.parametrize("timeout", [False, True])
def test_partial_usage_survives_provider_failure_and_timeout(timeout):
    pytest.importorskip("pydantic_ai")
    from agent_orchestration import PydanticAISparqlLLM
    class Agent:
        model = SimpleNamespace(model_name="provider", system="openai")
        async def run(self, prompt, *, usage):
            usage.input_tokens += 7
            usage.output_tokens += 2
            usage.requests += 1
            if timeout:
                await asyncio.sleep(1)
            raise RuntimeError("provider failed after one response")
    workflow = SparqlWorkflow(SystemOnePromptValidator(FakeClassifier("allow")),
        PydanticAISparqlLLM(Agent()), StaticQueryAnalyzer(), model_timeout_seconds=.02)
    result = asyncio.run(workflow.run(REQUEST, execute=False))
    tokens = result.analytics["token_usage"]
    assert result.status == "error"
    assert result.error_type == ("TimeoutError" if timeout else "RuntimeError")
    assert tokens["total_tokens"] is None and tokens["known_total_tokens"] == 9
    assert not tokens["by_stage"]["generation"]["complete"]
