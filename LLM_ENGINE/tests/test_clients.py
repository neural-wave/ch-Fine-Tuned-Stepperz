import json
from dataclasses import replace

import httpx
import pytest
from mcp.types import CallToolResult, TextContent
from openai import AsyncOpenAI

from sparql_agent.config import Config
from sparql_agent.llm_client import LLMClient
from sparql_agent.mcp_client import MCPClient, format_result

from .conftest import EXAMPLE


@pytest.mark.parametrize("structured", [True, False])
def test_mcp_structured_and_legacy_text_results(structured):
    payload = {"query_examples": [EXAMPLE]}
    result = CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structured_content=payload if structured else None,
    )
    formatted = format_result(result, "search_sparql_examples", Config())
    assert not formatted.is_error and not formatted.empty
    assert json.loads(formatted.content)["query_examples"] == [EXAMPLE]


def test_mcp_empty_error_and_unexpected_formats():
    for result, error, empty in (
        (CallToolResult(content=[], structured_content={"query_examples": []}), False, True),
        (CallToolResult(content=[TextContent(type="text", text="failed")], is_error=True), True, False),
        (CallToolResult(content=[TextContent(type="text", text="unknown format")]), True, False),
    ):
        output = format_result(result, "search_sparql_examples", Config())
        assert output.is_error == error and output.empty == empty


def test_context_budget_keeps_whole_records_and_marks_omissions():
    config = Config(max_tool_result_chars=350)
    payload = {
        "query_examples": [
            EXAMPLE,
            {**EXAMPLE, "query": "x" * 1000},
            {**EXAMPLE, "endpoint_url": "https://elsewhere.org/sparql"},
        ]
    }
    output = format_result(
        CallToolResult(content=[], structured_content=payload), "search_sparql_examples", config
    )
    data = json.loads(output.content)
    assert data["query_examples"] == [EXAMPLE] and output.truncated
    assert data["client_context"]["other_endpoint_or_empty_records_omitted"] == 1
    assert data["client_context"]["records_omitted_for_context_budget"] == 1


async def test_openai_adapter_uses_config_and_retains_usage():
    observed = []

    def handler(request):
        observed.append((request.url, json.loads(request.content)))
        return httpx.Response(
            200,
            json={
                "id": "mock",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "OK"}}
                ],
                "usage": {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11},
            },
        )

    config = replace(Config(), llm_base_url="http://test.local/v1", llm_model="test-model")
    async with LLMClient(config) as llm:
        await llm.client.close()
        llm.client = AsyncOpenAI(
            base_url=config.llm_base_url,
            api_key="dummy",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        reply = await llm.complete([{"role": "user", "content": "Hi"}])
    url, body = observed[0]
    assert str(url) == "http://test.local/v1/chat/completions"
    assert body["model"] == "test-model" and body["temperature"] == 0
    assert "tools" not in body and reply.total_tokens == 11


async def test_discovery_paginates():
    from types import SimpleNamespace

    class Pages:
        async def list_tools(self, *, cursor=None):
            tool = SimpleNamespace(name="first" if not cursor else "second", description="", input_schema={})
            return SimpleNamespace(tools=[tool], next_cursor="next" if not cursor else None)

    client = MCPClient(Config())
    client.client = Pages()
    assert set(await client.discover()) == {"first", "second"}
