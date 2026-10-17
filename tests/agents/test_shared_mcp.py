"""Actual LLM_ENGINE MCP 2 server with the main PydanticAI MCP 1 client."""
import asyncio
from contextlib import contextmanager
import json
import os
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("pydantic_ai")
pytest.importorskip("mcp")
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from agent_orchestration import CheckedQueryExecutor, PromptRequest, SparqlWorkflow, StaticQueryAnalyzer
from agent_orchestration import cli, local_models
from sparql_analyzer.demo import EXAMPLE_QUERY
from tests.paths import ROOT
from tools.generate_synthetic_data import generate

pytestmark = pytest.mark.offline_workflow


@pytest.mark.parametrize("config", [
    {"mcp_url": "http://localhost:18888/mcp", "mcp_settings": "other.json"},
    {"mcp_url": "file:///tmp/mcp"},
    {"mcp_url": "http://user:secret@localhost:18888/mcp"},
])
def test_invalid_mcp_configuration(config):
    with pytest.raises(ValueError):
        local_models.schema_server(config)


def test_cli_mcp_check_does_not_load_model_backends(monkeypatch, capsys):
    async def check(path):
        return {"status": "mcp_ready", "models_loaded": False}
    monkeypatch.setattr(cli, "check_mcp", check)
    monkeypatch.setattr("sys.argv", ["sparql-run", "--check-mcp"])
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["models_loaded"] is False


@contextmanager
def shared_server(tmp_path):
    engine = ROOT / "LLM_ENGINE"
    python = engine / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        pytest.skip("Prepare LLM_ENGINE first: uv sync --locked --project LLM_ENGINE --python 3.12")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (tmp_path / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(python), "scripts/serve_sphn_void.py", "--port", str(port),
            "--void-file", str(ROOT / "schemas/void/sphn-schema-void.ttl"),
            "--ontology", str(ROOT / "schemas/sphn/sphn_rdf_schema.ttl")],
            cwd=engine, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                pytest.fail("LLM_ENGINE server did not start; inspect " + str(tmp_path / "server.log"))
            yield f"http://127.0.0.1:{port}/mcp"
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_llm_engine_http_retrieval_in_the_checked_workflow(tmp_path, monkeypatch):
    loads, requests = [], []
    def load(*args, **kwargs):
        loads.append(args)
        return SimpleNamespace(predict=lambda *a, **k: {
            "answers": {"decision": {"choice": "allow", "answer_confidence": 0.9}}})
    monkeypatch.setitem(sys.modules, "laya", SimpleNamespace(load=load))
    def respond(messages, info):
        requests.append(messages)
        names = {tool.name for tool in info.function_tools}
        assert names == {"search_sparql_examples", "search_sparql_classes"}
        if len(requests) == 1:
            return ModelResponse(parts=[ToolCallPart("search_sparql_classes", {"classes": ["BilledDiagnosis"]})])
        if len(requests) == 2:
            assert any(isinstance(part, ToolReturnPart) and "BilledDiagnosis" in str(part.content)
                       for message in messages for part in message.parts)
            return ModelResponse(parts=[ToolCallPart("search_sparql_examples", {
                "question": "Count patients with BilledDiagnosis", "steps": []})])
        assert any(isinstance(part, ToolReturnPart) and "void_schema_aggregate_pattern" in str(part.content)
                   for message in messages for part in message.parts)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"query": EXAMPLE_QUERY})])
    monkeypatch.setattr(local_models, "chat_model", lambda *a: FunctionModel(respond))

    with shared_server(tmp_path) as url:
        config = tmp_path / "models.json"
        config.write_text(json.dumps({"base_url": "http://unused/v1", "model": "scripted",
            "laya": {"model_id": "scripted"}, "mcp_url": url}))
        async def exercise():
            status = await local_models.check_mcp(config)
            assert status["allowed_tools"] == ["search_sparql_classes", "search_sparql_examples"]
            assert status["excluded_tools"] == [] and loads == []
            async with local_models.open_models(config) as (guard, generator):
                workflow = SparqlWorkflow(guard, generator, StaticQueryAnalyzer(), CheckedQueryExecutor(generate()))
                outcome = await workflow.run(PromptRequest("count", "SPHN schema", "aggregate only", "analyst"))
                assert outcome.status == "released", outcome
                assert outcome.result["results"]["bindings"][0]["patients"]["value"] == "8"
        asyncio.run(exercise())
    assert len(loads) == 1 and len(requests) == 3
