"""Native logs persist across successful/failed requests without changing stdout."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.offline_workflow


def test_native_log_file_captures_workflow_errors_and_library_events(tmp_path):
    code = '''
import asyncio, json, logging
from types import SimpleNamespace
from agent_orchestration import (FakeClassifier, FakeSparqlLLM, PromptRequest,
    SparqlWorkflow, StaticQueryAnalyzer, SystemOnePromptValidator)
from agent_orchestration.logging_setup import configure_logging
from sparql_analyzer.demo import EXAMPLE_QUERY

path = configure_logging('probe')
assert configure_logging('another-label') == path
logging.getLogger('httpx').info('library-event')

async def exercise():
    request = PromptRequest('Count patients', 'schema', 'aggregates only')
    guard = SystemOnePromptValidator(FakeClassifier('allow'))
    good = SparqlWorkflow(guard, FakeSparqlLLM(EXAMPLE_QUERY), StaticQueryAnalyzer())
    assert (await good.run(request, execute=False)).status == 'query_ready'
    async def broken(_):
        raise RuntimeError('inference-unavailable')
    bad = SparqlWorkflow(guard, SimpleNamespace(run=broken), StaticQueryAnalyzer())
    assert (await bad.run(request, execute=False)).status == 'error'

asyncio.run(exercise())
print(json.dumps({'ok': True}))
'''
    env = {**os.environ, "SPARQL_LOG_DIR": str(tmp_path), "SPARQL_LOG_LEVEL": "INFO",
           "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    for _ in range(2):
        result = subprocess.run([sys.executable, "-c", code], env=env,
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"ok": True}
    files = list(tmp_path.glob("probe-*.log"))
    assert len(files) == 2
    for file in files:
        text = file.read_text(encoding="utf-8")
        assert text.count("Logging initialized") == 1
        assert "httpx | library-event" in text
        assert "status=query_ready" in text and "generated_query=" in text
        assert "status=error stage=generation" in text
        assert "Traceback" in text and "inference-unavailable" in text
        assert "    PREFIX sphn:" in text
        assert "\n    SELECT (COUNT(DISTINCT ?g) AS ?patients)" in text
        assert "\n    WHERE {" in text
        assert "generated_query='PREFIX" not in text


def test_log_block_preserves_query_text_and_does_not_change_it(caplog):
    import logging
    from agent_orchestration.logging_setup import log_block
    query = 'SELECT ?label WHERE {\n  BIND("literal \\n and {braces}" AS ?label) # keep comment\n}'
    original = query
    with caplog.at_level(logging.INFO):
        log_block(logging.getLogger("query-preview"), "SPARQL", query)
        log_block(logging.getLogger("query-preview"), "Result", {"patients": 8})
    assert query == original
    assert all(f"    {line}" in caplog.text for line in query.splitlines())
    assert '"patients": 8' in caplog.text


def test_workflow_logs_query_once_but_standalone_adapter_keeps_its_logs(caplog):
    import asyncio
    import logging
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from agent_orchestration import (
        FakeClassifier, PromptRequest, PydanticAISparqlLLM, SparqlResult,
        SparqlWorkflow, StaticQueryAnalyzer, SystemOnePromptValidator,
    )
    from agent_orchestration.logging_setup import active_workflow
    from sparql_analyzer.demo import EXAMPLE_QUERY
    agent = SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(output=SparqlResult(EXAMPLE_QUERY))))
    generator = PydanticAISparqlLLM(agent)
    request = PromptRequest("one-prompt-marker", "schema", "policy")
    workflow = SparqlWorkflow(SystemOnePromptValidator(FakeClassifier("allow")),
                              generator, StaticQueryAnalyzer())
    async def exercise():
        result = await workflow.run(request, execute=False)
        assert active_workflow.get() is None
        return result
    with caplog.at_level(logging.INFO):
        result = asyncio.run(exercise())
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert messages.count(EXAMPLE_QUERY.splitlines()[0]) == 1
    assert messages.count("one-prompt-marker") == 1
    assert "Generator response - SPARQL query" not in messages
    assert result.query == EXAMPLE_QUERY
    assert active_workflow.get() is None
    caplog.clear()
    with caplog.at_level(logging.INFO):
        direct = asyncio.run(generator.run(request))
    assert direct.query == EXAMPLE_QUERY
    assert "Generator response - SPARQL query" in caplog.text


def test_logging_scope_is_reset_after_failure(caplog):
    import asyncio
    from types import SimpleNamespace
    from agent_orchestration import FakeClassifier, PromptRequest, SparqlWorkflow, StaticQueryAnalyzer, SystemOnePromptValidator
    from agent_orchestration.logging_setup import active_workflow
    async def broken(_):
        raise RuntimeError("failure")
    workflow = SparqlWorkflow(SystemOnePromptValidator(FakeClassifier("allow")),
                              SimpleNamespace(run=broken), StaticQueryAnalyzer())
    async def exercise():
        result = await workflow.run(PromptRequest("count", "schema", "policy"), execute=False)
        assert result.status == "error"
        assert active_workflow.get() is None
    asyncio.run(exercise())
