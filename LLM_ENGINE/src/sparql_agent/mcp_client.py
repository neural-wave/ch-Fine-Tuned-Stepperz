"""MCP 2.x client, endpoint filtering, and retrieval backend selection."""

import json
from dataclasses import dataclass, field, replace
from urllib.parse import urlparse

from mcp import Client
from mcp.types import CallToolResult

from .config import Config
from .sphn_retrieval import TARGET as SPHN_TARGET

RETRIEVAL_TOOLS = frozenset({"search_sparql_examples", "search_sparql_classes"})
SPHN_MCP_URL = "http://127.0.0.1:18888/mcp"


def select_retrieval_backend(config: Config, backend: str | None = None) -> Config:
    """Resolve the selected retrieval transport and target before creating clients."""
    backend = backend or config.retrieval_backend
    if backend == "public":
        return replace(config, retrieval_backend=backend)
    if backend == "sphn-void":
        return replace(
            config,
            retrieval_backend=backend,
            mcp_url=SPHN_MCP_URL,
            target_endpoint=SPHN_TARGET,
            enable_sparql_execution=False,
        )
    raise ValueError(f"Unknown retrieval backend: {backend}")


def same_endpoint(first: str, second: str) -> bool:
    a, b = urlparse(first), urlparse(second)
    return (a.scheme.lower(), a.netloc.lower(), a.path.rstrip("/"), a.query) == (
        b.scheme.lower(),
        b.netloc.lower(),
        b.path.rstrip("/"),
        b.query,
    )


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.input_schema},
        }


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    empty: bool = False
    truncated: bool = False
    endpoints: list[str] = field(default_factory=list)
    original_chars: int = 0


def format_result(result: CallToolResult, name: str, config: Config) -> ToolResult:
    """Prefer structured output, with support for older servers' JSON text blocks.

    Restrict returned records to the requested endpoint, then fit whole records into
    the context budget. This only trims actual retrieved data; it never invents it.
    """
    text = "\n".join(block.text for block in result.content if getattr(block, "type", "") == "text")
    data = result.structured_content
    if data is None and text:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            pass
    serialized = json.dumps(data, ensure_ascii=False) if data is not None else text
    original_chars = len(serialized)
    if result.is_error:
        return ToolResult(
            serialized[: config.max_tool_result_chars] or "MCP returned is_error=true",
            is_error=True,
            original_chars=original_chars,
            truncated=original_chars > config.max_tool_result_chars,
        )
    key = {"search_sparql_examples": "query_examples", "search_sparql_classes": "classes_schemas"}.get(name)
    endpoints = []
    if key and isinstance(data, dict) and isinstance(data.get(key), list):
        records = data[key]
        matches = [
            row
            for row in records
            if isinstance(row, dict)
            and same_endpoint(str(row.get("endpoint_url", "")), config.target_endpoint)
            and str(row.get("query" if key == "query_examples" else "shex", "")).strip()
        ]
        selected = []
        for row in matches:
            if len(json.dumps({key: [*selected, row]}, ensure_ascii=False)) <= config.max_tool_result_chars:
                selected.append(row)
        endpoints = sorted({row["endpoint_url"] for row in selected})
        omitted = len(matches) - len(selected)
        payload = {
            key: selected,
            "client_context": {
                "target_endpoint": config.target_endpoint,
                "other_endpoint_or_empty_records_omitted": len(records) - len(matches),
                "records_omitted_for_context_budget": omitted,
            },
        }
        if not selected:
            payload["client_context"]["notice"] = (
                "No usable records for the target endpoint; do not invent context."
            )
        return ToolResult(
            json.dumps(payload, ensure_ascii=False),
            empty=not selected,
            truncated=omitted > 0,
            endpoints=endpoints,
            original_chars=original_chars,
        )
    # An unexpected retrieval format is explicit, not counted as useful evidence.
    if key:
        return ToolResult(
            "Unexpected MCP retrieval format; expected "
            + key
            + ". Actual output:\n"
            + serialized[: config.max_tool_result_chars],
            is_error=True,
            original_chars=original_chars,
            truncated=original_chars > config.max_tool_result_chars,
        )
    truncated = original_chars > config.max_tool_result_chars
    return ToolResult(
        serialized[: config.max_tool_result_chars] + ("\n[truncated by client]" if truncated else ""),
        empty=not serialized.strip() or data in ({}, []),
        truncated=truncated,
        original_chars=original_chars,
    )


class MCPClient:
    def __init__(self, config: Config):
        self.config = config
        self.client = Client(config.mcp_url, read_timeout_seconds=config.mcp_timeout_seconds)

    async def __aenter__(self):
        await self.client.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.client.__aexit__(*args)

    async def discover(self) -> dict[str, ToolSpec]:
        found = {}
        cursor = None
        seen = set()
        while True:
            page = await self.client.list_tools(cursor=cursor)
            for tool in page.tools:
                found[tool.name] = ToolSpec(tool.name, tool.description or "", tool.input_schema)
            cursor = page.next_cursor
            if not cursor:
                return found
            if cursor in seen:
                raise ValueError("MCP tool discovery repeated a pagination cursor")
            seen.add(cursor)

    async def call(self, name: str, arguments: dict) -> ToolResult:
        result = await self.client.call_tool(
            name, arguments, read_timeout_seconds=self.config.mcp_timeout_seconds
        )
        return format_result(result, name, self.config)
