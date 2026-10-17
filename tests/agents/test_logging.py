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
        assert "httpx library-event" in text
        assert "status=query_ready" in text and "generated_query=" in text
        assert "status=error stage=generation" in text
        assert "Traceback" in text and "inference-unavailable" in text
