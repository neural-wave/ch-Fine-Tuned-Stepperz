"""Infrastructure diagnostics with HTTP and MCP doubles, no live models."""
import json
from types import SimpleNamespace

import httpx
import pytest

from system_validation import health
from system_validation.client import Clients

pytestmark = pytest.mark.offline_workflow


class MCP:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def list_tools(self):
        return [SimpleNamespace(name=name) for name in ("search_sparql_examples", "search_sparql_classes")]

    async def direct_call_tool(self, name, arguments):
        if name == "search_sparql_examples":
            return {"query_examples": [{"class_iri": "urn:Patient"}]}
        return {"classes_schemas": [{"iri": "urn:Patient"}]}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    models = tmp_path / "models.json"
    models.write_text(json.dumps({"model": "chosen-model", "base_url": "http://model.test/v1",
                                  "mcp_url": "http://mcp.test/mcp"}), encoding="utf-8")
    monkeypatch.setattr(health, "CONFIG", models)
    monkeypatch.setattr(health, "schema_server", lambda config: MCP())
    return {"api_url": "http://api.test", "virtuoso_url": "http://db.test/sparql",
            "timeout_seconds": 1, "out_dir": tmp_path / "reports"}


def test_quick_check_verifies_actual_model_and_schema_without_inference(setup):
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == "GET"
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "chosen-model"}]})

    clients = Clients(setup, transport=httpx.MockTransport(respond))
    try:
        report = health.check(setup, clients)
    finally:
        clients.close()
    assert report["ok"] is True and len(calls) == 2
    assert set(report["checks"]) == {"api", "generator", "mcp"}
    assert report["checks"]["mcp"]["details"]["classes"] == 1
    assert len(list(setup["out_dir"].glob("health-*.json"))) == 1


def test_model_mismatch_uses_served_id_and_empty_schema_fails(setup, monkeypatch):
    class Empty(MCP):
        async def direct_call_tool(self, name, arguments):
            return {"query_examples": []}

    monkeypatch.setattr(health, "schema_server", lambda config: Empty())

    def respond(request):
        if request.url.path == "/health":
            raise httpx.ConnectError("API offline", request=request)
        return httpx.Response(200, json={"data": [{"id": "different-model"}]})

    clients = Clients(setup, transport=httpx.MockTransport(respond))
    try:
        report = health.check(setup, clients)
    finally:
        clients.close()
    assert report["ok"] is False
    assert len(report["checks"]) == 3
    assert report["checks"]["api"]["ok"] is False
    assert report["checks"]["generator"]["ok"] is True
    assert report["checks"]["generator"]["details"]["model"] == "different-model"
    assert report["checks"]["generator"]["details"]["configured_model"] == "chosen-model"
    assert "no examples" in report["checks"]["mcp"]["error"]["message"]


def test_optional_inference_uses_existing_api_and_checks_loaded_data(setup, monkeypatch):
    monkeypatch.setattr(health, "ready", lambda config, clients: {"database": {"patient_graphs": 1000}})
    monkeypatch.setenv("MODEL_API_KEY", "secret-test-key")

    def respond(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/models":
            assert request.headers["Authorization"] == "Bearer secret-test-key"
            return httpx.Response(200, json={"data": [{"id": "chosen-model"}]})
        assert request.url.path == "/study/nl-to-sparql"
        assert json.loads(request.content) == {"text": health.PROMPT}
        return httpx.Response(200, json={"is_compliant": False, "sparql_query": "SELECT (COUNT(*) AS ?n) WHERE {}",
            "tokens_consumed": 42, "analytics": {"prompt_decision": "review"}})

    clients = Clients(setup, transport=httpx.MockTransport(respond))
    try:
        report = health.check(setup, clients, inference=True, with_virtuoso=True)
    finally:
        clients.close()
    assert report["ok"] is True  # Readiness is not a classifier accuracy test.
    assert report["checks"]["inference"]["details"]["tokens_consumed"] == 42
    assert report["checks"]["virtuoso"]["details"]["database"]["patient_graphs"] == 1000
    path, = setup["out_dir"].glob("health-*.json")
    assert "secret-test-key" not in path.read_text(encoding="utf-8")
