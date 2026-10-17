"""Schema-only MCP transports and discovery; no model loading."""
import json
import logging
from pathlib import Path
from urllib.parse import urlparse
from ..logging_setup import configure_logging

CONFIG = Path(__file__).resolve().parents[3] / "config/agents/models.json"
logger = logging.getLogger(__name__)
RETRIEVAL_TOOLS = frozenset({
    "search_sparql_examples", "search_sparql_classes",  # LLM_ENGINE SPHN
    "search_sparql_docs", "get_classes_schema",  # upstream stdio
})


def schema_server(config, config_path=CONFIG):
    """Connect to the shared HTTP MCP, or explicitly launch the legacy stdio server."""
    from pydantic_ai.mcp import MCPServerStdio, MCPServerStreamableHTTP
    url, settings = config.get("mcp_url"), config.get("mcp_settings")
    if url and settings:
        raise ValueError("Choose mcp_url or mcp_settings, not both")
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("mcp_url must be an HTTP(S) URL without embedded credentials")
        return MCPServerStreamableHTTP(url, timeout=120, read_timeout=120, allow_sampling=False)
    if settings:
        return MCPServerStdio("uvx", args=["sparql-llm"],
            env={"SETTINGS_FILEPATH": str((Path(config_path).resolve().parent / settings).resolve())},
            cwd=str(CONFIG.parents[2]), timeout=120, read_timeout=120, allow_sampling=False)
    return None


async def check_mcp(config_path=CONFIG):
    """Discover the shared server without loading Laya or calling an LLM."""
    configure_logging()
    logger.info("MCP discovery started config=%s", config_path)
    config = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    server = schema_server(config, config_path)
    if server is None:
        raise ValueError("MCP is disabled")
    async with server:
        names = {tool.name for tool in await server.list_tools()}
    allowed = sorted(names & RETRIEVAL_TOOLS)
    logger.info("MCP discovered tools=%s allowed=%s", sorted(names), allowed)
    if not allowed:
        raise ValueError("MCP exposes no supported schema retrieval tools")
    return {"status": "mcp_ready", "allowed_tools": allowed,
            "excluded_tools": sorted(names - RETRIEVAL_TOOLS), "models_loaded": False}


