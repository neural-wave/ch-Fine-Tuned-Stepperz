import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("pydantic_ai")
import httpx
from pydantic_ai.providers.openai import OpenAIProvider

from agent_orchestration import CheckedQueryExecutor, PromptRequest, SparqlWorkflow, StaticQueryAnalyzer
from agent_orchestration import local_models
from sparql_analyzer.demo import EXAMPLE_QUERY
from tools.generate_synthetic_data import generate
from tests.paths import ROOT

pytestmark = pytest.mark.offline_workflow


def test_chat_model_can_use_another_compatible_server():
    model = local_models.chat_model("different-model", "http://localhost:8080/v1")
    assert model.model_name == "different-model"
    assert str(model.client.base_url) == "http://localhost:8080/v1/"


@pytest.mark.parametrize("usage", [{"truncated": True}, {"state_tokens_dropped": 1}, {"options": {"collapsed": True}}])
def test_laya_refuses_incomplete_input(usage):
    backend = SimpleNamespace(predict=lambda *a, **k: {"usage": usage})
    with pytest.raises(ValueError, match="truncated"):
        asyncio.run(local_models.laya_validator(backend).run(PromptRequest("prompt", "schema", "policy")))


def test_laya_abstains_on_low_confidence_and_preserves_trusted_context():
    def predict(state, questions, max_len):
        assert json.loads(state)["permissions"] == "aggregates"
        assert set(questions["decision"]["criteria"]) == {"allow", "block", "review"}
        return {"answers": {"decision": {"choice": "allow", "low_confidence": True}}}
    verdict = asyncio.run(local_models.laya_validator(SimpleNamespace(predict=predict)).run(
        PromptRequest("prompt", "schema", "policy", "aggregates")))
    assert verdict.decision == "review"


def test_chat_http_mcp_and_checked_workflow(tmp_path, monkeypatch):
    """Real PydanticAI HTTP serialization + real stdio MCP, controlled inference."""
    pytest.importorskip("mcp")
    from pydantic_ai.mcp import MCPServerStdio
    calls, loads = [], []
    def laya_load(*args, **kwargs):
        loads.append(args)
        return SimpleNamespace(predict=lambda *a, **k: {"usage": {}, "answers": {
            "decision": {"choice": "allow", "answer_confidence": 0.9, "confidence": 0.1}}})
    monkeypatch.setitem(sys.modules, "laya", SimpleNamespace(load=laya_load))
    config = tmp_path / "models.json"
    config.write_text(json.dumps({"base_url": "http://local.test/v1", "model": "test-qwen",
        "laya": {"model_id": "test-laya"}, "mcp_settings": "settings.json"}))
    def test_server(command, **kwargs):
        return MCPServerStdio(sys.executable, args=["-m", "tests.support.native_mcp_server"],
            cwd=str(ROOT), allow_sampling=False)
    monkeypatch.setattr("pydantic_ai.mcp.MCPServerStdio", test_server)

    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        tools = {t["function"]["name"] for t in payload["tools"]}
        assert "execute_sparql_query" not in tools
        assert "get_classes_schema" in tools
        if payload["messages"][-1]["role"] != "tool":
            name, arguments = "get_classes_schema", {"classes": ["sphn:BilledDiagnosis"]}
        else:
            assert "BilledDiagnosis" in payload["messages"][-1]["content"]
            name, arguments = next(n for n in tools if n != "get_classes_schema"), {"query": EXAMPLE_QUERY}
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0,
            "model": "test-qwen", "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{"id": str(len(calls)), "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)}}]}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            def provider(**kwargs):
                return OpenAIProvider(**kwargs, http_client=client)
            monkeypatch.setattr("pydantic_ai.providers.openai.OpenAIProvider", provider)
            async with local_models.open_models(config) as (guard, generator):
                workflow = SparqlWorkflow(guard, generator, StaticQueryAnalyzer(), CheckedQueryExecutor(generate()))
                for _ in range(2):
                    result = await workflow.run(PromptRequest("count patients", "schema", "policy"))
                    assert result.status == "released", result
                    assert result.prompt_validation.probability == 0.9
                    assert result.result["results"]["bindings"][0]["patients"]["value"] == "8"
    asyncio.run(exercise())
    assert len(loads) == 1 and len(calls) == 4
