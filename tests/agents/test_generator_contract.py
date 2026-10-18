"""Production generator and real SDK over scripted HTTP, with no model loaded."""
import asyncio
import json

import httpx
import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.providers.openai import OpenAIProvider
from sparql_analyzer.validation import validate

from agent_orchestration.local_models import open_generator
from agent_orchestration.models import SparqlRequest

pytestmark = pytest.mark.offline_workflow
MODEL = "daniel-dona/sparql-model-era-lora-128-qwen3-8b"
QUERY = "SELECT (EXISTS { GRAPH <http://example.org/graph/patient-42> { ?s a <urn:Diagnosis> } } AS ?present) WHERE {}"
REQUEST = SparqlRequest("Check whether the fixed patient graph contains a diagnosis", "schema", "aggregate statistics only")


@pytest.fixture
def run_generator(tmp_path, monkeypatch):
    config = tmp_path / "models.json"
    config.write_text(json.dumps({"model": MODEL, "base_url": "http://model.test/v1"}))

    async def run(respond, request=REQUEST):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            monkeypatch.setattr("pydantic_ai.providers.openai.OpenAIProvider",
                lambda **kwargs: OpenAIProvider(**kwargs, http_client=client))
            async with open_generator(config, assessment_mode=True) as generator:
                return await generator.run_with_usage(request)
    return run


def completion(message, finish="stop"):
    return httpx.Response(200, json={"id": "test", "object": "chat.completion",
        "created": 0, "model": MODEL, "choices": [{"index": 0,
            "finish_reason": finish, "message": {"role": "assistant", **message}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})


def test_boolean_sparql_remains_a_query_string_and_uses_required_output(run_generator):
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["tool_choice"] == "required"
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        tool = body["tools"][0]["function"]
        assert tool["parameters"]["properties"]["query"]["type"] == "string"
        return completion({"content": None, "tool_calls": [{"id": "query", "type": "function",
            "function": {"name": tool["name"], "arguments": json.dumps({"query": QUERY})}}]}, "tool_calls")

    result = asyncio.run(run_generator(respond))
    assert result.output.query == QUERY
    assert result.usage.total_tokens == 15 and result.usage.requests == 1
    assert len(calls) == 1
    # Accepting the output contract must not approve a patient-specific probe.
    assert validate(result.output.query)["is_compliant"] is not True


@pytest.mark.parametrize("kind", ["empty", "thinking", "truncated", "boolean"])
def test_failed_outputs_are_logged_without_becoming_queries(run_generator, caplog, kind):
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if kind == "boolean":
            tool = body["tools"][0]["function"]
            return completion({"content": None, "tool_calls": [{"id": "query", "type": "function",
                "function": {"name": tool["name"], "arguments": '{"query": true}'}}]}, "tool_calls")
        message = {"content": None}
        if kind in {"thinking", "truncated"}:
            message["reasoning_content"] = "Reasoning without a final answer"
        return completion(message, "length" if kind == "truncated" else "stop")

    with pytest.raises(UnexpectedModelBehavior) as caught:
        asyncio.run(run_generator(respond))
    expected_calls = 1 if kind == "truncated" else 2
    assert len(calls) == expected_calls
    assert caught.value.token_usage.total_tokens == 15 * expected_calls
    assert not caught.value.token_usage.complete
    assert "Generator failed - model responses and validation feedback" in caplog.text
    assert '"finish_reason"' in caplog.text
    if kind in {"thinking", "boolean"}:
        assert "validation_feedback" in caplog.text
    if kind in {"thinking", "truncated"}:
        assert "Reasoning without a final answer" in caplog.text
