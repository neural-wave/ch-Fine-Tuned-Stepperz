"""API log files are verified in an isolated process, without model inference."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.offline_workflow


def test_endpoint_logs_requests_query_tokens_and_failures_to_file(tmp_path):
    code = '''
import logging, logging.config
from fastapi.testclient import TestClient
from uvicorn.config import LOGGING_CONFIG
from api.server import create_app
from tests.api.test_server import service

logging.config.dictConfig(LOGGING_CONFIG)
translator = service()
app = create_app(translator)
with TestClient(app) as client:
    response = client.post('/nl-to-sparql', json={'text': 'logging-success-marker'})
    assert response.status_code == 200, response.text
    first = app.state.log_path
    handler = next(h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler))
    logging.getLogger().removeHandler(handler)
    assert client.get('/health').status_code == 200
    assert app.state.log_path == first
    logging.config.dictConfig(LOGGING_CONFIG)
    assert client.post('/nl-to-sparql', json={}).status_code == 400
    assert app.state.log_path == first
    assert client.get('/missing').status_code == 404
    async def fail(request):
        raise ConnectionError('logging-backend-failure-marker')
    translator.generator.run_with_usage = fail
    assert client.post('/nl-to-sparql', json={'text': 'failure'}).status_code == 502
text = '\\n'.join(path.read_text(encoding='utf-8') for path in first.parent.glob('sparql-api-*.log'))
assert 'API logging file=' in text
assert 'HTTP request started method=POST path=/nl-to-sparql' in text
assert 'path=/health status=200' in text
assert 'status=400' in text and 'status=404' in text and 'status=502' in text
assert 'elapsed_seconds=' in text
assert 'API token usage' in text
assert text.count('API generated SPARQL') == 1
assert 'logging-backend-failure-marker' in text and 'Traceback' in text
print('api-log-check-passed')
'''
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "SPARQL_LOG_DIR": str(tmp_path), "SPARQL_LOG_LEVEL": "INFO",
           "PYTHONPATH": os.pathsep.join([str(root / "src"), str(root)])}
    result = subprocess.run([sys.executable, "-c", code], cwd=root, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'api-log-check-passed' in result.stdout
    assert 'API logging file=' in result.stderr


def test_endpoint_recovers_application_loggers_disabled_by_backend_config(tmp_path):
    code = '''
import logging, logging.config
from fastapi.testclient import TestClient
from api.server import create_app
from tests.api.test_server import service

app = create_app(service())
with TestClient(app) as client:
    path = app.state.log_path
    # dictConfig defaults to disable_existing_loggers=True. Root handlers can
    # be restored while api.server/api.service remain individually disabled.
    logging.config.dictConfig({'version': 1, 'handlers': {},
        'root': {'level': 'WARNING', 'handlers': []}})
    assert logging.getLogger('api.service').disabled
    logging.getLogger('api.service').setLevel(logging.CRITICAL)
    logging.getLogger('api.service').propagate = False
    response = client.post('/nl-to-sparql', json={'text': 'after-backend-log-config-marker'})
    assert response.status_code == 200, response.text
text = path.read_text(encoding='utf-8')
assert 'after-backend-log-config-marker' in text, 'API logger remained disabled'
assert 'API generated SPARQL' in text
assert 'API token usage' in text
assert 'HTTP request completed' in text
assert text.count('API generated SPARQL') == 1
'''
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "SPARQL_LOG_DIR": str(tmp_path), "SPARQL_LOG_LEVEL": "INFO",
           "PYTHONPATH": os.pathsep.join([str(root / "src"), str(root)])}
    result = subprocess.run([sys.executable, "-c", code], cwd=root, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
