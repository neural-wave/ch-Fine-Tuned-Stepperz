"""Real HTTP contract and deterministic checker; no model weights or services."""
import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from api import server
from api.service import TranslationService
from agent_orchestration.models import ModelResponse, SparqlResult, TokenUsage
from agent_orchestration.validation import PromptValidation
from sparql_analyzer.demo import EXAMPLE_QUERY

pytestmark = pytest.mark.offline_workflow


class Guard:
    def __init__(self, decision="allow"):
        self.decision = decision

    async def run_with_usage(self, request):
        return ModelResponse(PromptValidation(self.decision, "test decision"), TokenUsage(7, 0, source="reported"))


class Generator:
    def __init__(self, query=EXAMPLE_QUERY, usage=None):
        self.query, self.calls = query, []
        self.usage = usage if usage is not None else TokenUsage(10, 5, source="reported", requests=2)

    async def run_with_usage(self, request):
        self.calls.append(request)
        return ModelResponse(SparqlResult(self.query), self.usage)


def service(query=EXAMPLE_QUERY, *, decision="allow", usage=None):
    return TranslationService(Guard(decision), Generator(query, usage), schema="SPHN", policy="trusted", permissions="analyst")


def test_success_returns_original_query_and_all_models_tokens():
    translator = service()
    with TestClient(server.create_app(translator)) as client:
        for _ in range(2):
            response = client.post("/nl-to-sparql", json={"text": "count"})
            assert response.status_code == 200
            assert response.json() == {"sparql_query": EXAMPLE_QUERY, "tokens_consumed": 22, "is_compliant": True}
        assert client.get("/health").json() == {"status": "ok"}
        spec = client.get("/openapi.json").json()
        assert spec["paths"]["/nl-to-sparql"]["post"]["operationId"] == "generateSparql"
        assert "422" not in spec["paths"]["/nl-to-sparql"]["post"]["responses"]
    assert len(translator.generator.calls) == 2


def test_opt_in_analytics_exposes_real_counters_and_stage_times():
    with TestClient(server.create_app(service())) as client:
        result = client.post("/nl-to-sparql", json={"text": "count"}, headers={"X-Include-Analytics": "true"}).json()
    analytics = result["analytics"]
    assert analytics["token_usage"]["total_tokens"] == result["tokens_consumed"] == 22
    assert analytics["token_usage"]["by_stage"]["generation"]["requests"] == 2
    assert analytics["token_usage"]["by_stage"]["prompt_validation"]["input_tokens"] == 7
    assert analytics["prompt_decision"] == "allow"
    assert analytics["timings"]["generation"] >= 0
    assert analytics["timings"]["total"] >= sum(analytics["timings"][key] for key in ("prompt_validation", "generation", "analysis"))


@pytest.mark.parametrize("query", [
    "DELETE WHERE { ?s ?p ?o }",
    "ASK { ?s ?p ?o }",
    "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
    "SELECT ?g WHERE { GRAPH ?g { ?s ?p ?o } }",
    "SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }",
    "SELECT WHERE",
    'DEFINE sql:select-option "order" ' + EXAMPLE_QUERY,
])
def test_noncompliant_query_is_still_http_success_without_rewrite(query):
    translator = service(query)
    with TestClient(server.create_app(translator)) as client:
        response = client.post("/nl-to-sparql", json={"text": "original question"})
    assert response.status_code == 200
    assert response.json()["sparql_query"] == query
    assert response.json()["is_compliant"] is False
    assert response.json()["compliance_reason"]
    assert len(translator.generator.calls) == 1
    assert translator.generator.calls[0].prompt == "original question"


@pytest.mark.parametrize("decision", ["block", "review"])
def test_prompt_gate_is_kept_but_query_is_available_for_assessment(decision):
    translator = service(decision=decision)
    with TestClient(server.create_app(translator)) as client:
        result = client.post("/nl-to-sparql", json={"text": "question"}).json()
    assert result["sparql_query"] == EXAMPLE_QUERY
    assert result["is_compliant"] is False
    assert decision in result["compliance_reason"]
    assert result["tokens_consumed"] == 22


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": "  "}, {"text": None}, {"text": 12},
    {"text": True}, {"text": []}, {"text": "x" * 16385}, []])
def test_bad_input_is_400_before_inference(body):
    translator = service()
    with TestClient(server.create_app(translator)) as client:
        response = client.post("/nl-to-sparql", json=body)
    assert response.status_code == 400
    assert set(response.json()) == {"error"}
    assert not translator.generator.calls


def test_invalid_json_and_http_errors_follow_error_contract():
    with TestClient(server.create_app(service())) as client:
        for response in (client.post("/nl-to-sparql", content="{", headers={"content-type": "application/json"}),
                         client.get("/nl-to-sparql"), client.get("/missing")):
            assert response.status_code in {400, 404, 405}
            assert set(response.json()) == {"error"}


@pytest.mark.parametrize("usage", [TokenUsage(), TokenUsage(10, 5, source="estimated")])
def test_missing_or_estimated_tokens_are_not_reported_as_zero(usage):
    with TestClient(server.create_app(service(usage=usage))) as client:
        response = client.post("/nl-to-sparql", json={"text": "count"})
    assert response.status_code == 502
    assert set(response.json()) == {"error"}


def test_backend_failure_does_not_leak_private_details():
    translator = service()
    async def fail(request):
        raise ConnectionError("secret-key and patient-data")
    translator.generator.run_with_usage = fail
    with TestClient(server.create_app(translator)) as client:
        response = client.post("/nl-to-sparql", json={"text": "count"})
    assert response.status_code == 502
    assert "secret" not in response.text and "patient-data" not in response.text


def test_timeout_is_not_a_compliance_verdict(monkeypatch):
    monkeypatch.setattr(server, "REQUEST_TIMEOUT", 0.01)
    translator = service()
    async def wait(request):
        await asyncio.Event().wait()
    translator.generator.run_with_usage = wait
    with TestClient(server.create_app(translator)) as client:
        response = client.post("/nl-to-sparql", json={"text": "count"})
    assert response.status_code == 504 and set(response.json()) == {"error"}


def test_startup_reuses_main_backends_and_closes_them(monkeypatch):
    events = []
    translator = service()
    @asynccontextmanager
    async def models(config, *, assessment_mode):
        assert assessment_mode is True
        events.append("open")
        try:
            yield translator.guard, translator.generator
        finally:
            events.append("close")
    monkeypatch.setattr(server, "open_models", models)
    with TestClient(server.create_app()) as client:
        for _ in range(2):
            assert client.post("/nl-to-sparql", json={"text": "count"}).status_code == 200
        assert events == ["open"]
    assert events == ["open", "close"]
