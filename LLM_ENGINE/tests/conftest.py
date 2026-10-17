"""Unit fixtures are deliberately synthetic; live tests use the actual SIB tools."""

import copy
import json

import pytest

from sparql_agent.llm_client import ModelReply
from sparql_agent.mcp_client import ToolResult, ToolSpec

ENDPOINT = "https://sparql.uniprot.org/sparql/"
QUERY = f"#+ endpoint: {ENDPOINT}\nSELECT ?value WHERE {{ VALUES ?value {{ 1 }} }}"
FINAL = f"```sparql\n{QUERY}\n```"
EXAMPLE = {"question": "Synthetic unit fixture", "query": QUERY, "endpoint_url": ENDPOINT}


def model_reply(content="", calls=None, finish_reason="stop", tokens=True):
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = calls
    return ModelReply(
        message, finish_reason, 10 if tokens else None, 5 if tokens else None, 15 if tokens else None, 0.1
    )


def tool_call(name="search_sparql_examples", arguments=None, call_id="call_1"):
    if arguments is None:
        arguments = {"question": "test", "steps": []}
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
        },
    }


class FakeLLM:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    async def complete(self, messages, tools=None):
        self.requests.append((copy.deepcopy(messages), copy.deepcopy(tools)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeMCP:
    def __init__(self, outputs=None):
        self.calls = []
        self.outputs = list(outputs or [])
        self.specs = {
            "search_sparql_examples": ToolSpec(
                "search_sparql_examples",
                "Actual schema shape, mock result",
                {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "steps": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["question", "steps"],
                },
            ),
            "search_sparql_classes": ToolSpec(
                "search_sparql_classes",
                "Schema",
                {
                    "type": "object",
                    "properties": {"classes": {"type": "array", "items": {"type": "string"}}},
                    "required": ["classes"],
                },
            ),
            "execute_sparql_query": ToolSpec("execute_sparql_query", "Never expose", {"type": "object"}),
            "unrelated_tool": ToolSpec("unrelated_tool", "Never expose", {"type": "object"}),
        }

    async def discover(self):
        return self.specs

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        if self.outputs:
            outcome = self.outputs.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return ToolResult(json.dumps({"query_examples": [EXAMPLE]}), endpoints=[ENDPOINT])


@pytest.fixture
def fake_mcp():
    return FakeMCP()
