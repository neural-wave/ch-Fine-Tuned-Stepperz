"""Study responses expose one execution's measurements, including partial failures."""
import asyncio
from dataclasses import replace
from datetime import datetime

from fastapi.testclient import TestClient
import pytest
import httpx
from time import perf_counter

from api import server
from agent_orchestration.models import TokenUsage
from tests.api.test_server import EXAMPLE_QUERY, service

pytestmark = pytest.mark.offline_workflow
URL = "/study/nl-to-sparql"


def test_study_returns_full_analytics_without_header_and_only_runs_once(caplog):
    translator = service(usage=TokenUsage(10, 5, model="fake-qwen", source="reported", requests=2,
                                        cache_read_tokens=4, reasoning_tokens=2))
    original = translator.generator.run_with_usage

    async def generate(request):
        result = await original(request)
        return replace(result, metadata={"retrieval": {"classes": 2, "examples": 3, "seconds": .01}})

    translator.generator.run_with_usage = generate
    with TestClient(server.create_app(translator)) as client:
        response = client.post(URL, json={"text": "count"}, headers={"X-Include-Analytics": "false"})
        assert response.status_code == 200, response.text
        result = response.json()
        spec = client.get("/openapi.json").json()
    assert result["sparql_query"] == EXAMPLE_QUERY and result["tokens_consumed"] == 22
    assert result["is_compliant"] is True and len(translator.generator.calls) == 1
    analytics = result["analytics"]
    assert analytics["status"] == "complete" and analytics["executed"] is False
    assert analytics["prompt_assessment"]["decision"] == "allow"
    assert analytics["prompt_assessment"]["reason"] == "test decision"
    assert analytics["query_analysis"]["status"] == "compliant"
    assert "configuration" in analytics["query_analysis"]
    usage = analytics["token_usage"]["by_stage"]["generation"]
    assert usage["model"] == "fake-qwen" and usage["cache_read_tokens"] == 4
    assert usage["reasoning_tokens"] == 2 and usage["requests"] == 2
    assert analytics["generation_metadata"]["retrieval"]["examples"] == 3
    assert analytics["effective_output_tokens_per_second"]["generation"] > 0
    times = analytics["timings"]
    assert {"prompt_validation", "generation", "analysis", "total", "queue", "request_total"} <= times.keys()
    assert all(value >= 0 for value in times.values())
    assert times["request_total"] >= times["total"] + times["queue"]
    assert datetime.fromisoformat(analytics["request"]["finished_at"]) >= datetime.fromisoformat(analytics["request"]["received_at"])
    assert analytics["request"]["id"] in caplog.text
    assert analytics["request"]["prompt"] == "count"
    assert spec["paths"][URL]["post"]["operationId"] == "studySparql"
    assert "analytics" in spec["components"]["schemas"]["StudyResponse"]["required"]


@pytest.mark.parametrize("decision", ["block", "review"])
def test_study_keeps_prompt_rejections_and_query_assessment(decision):
    with TestClient(server.create_app(service(decision=decision))) as client:
        response = client.post(URL, json={"text": "original prompt"})
    assert response.status_code == 200
    result = response.json()
    assert result["is_compliant"] is False and result["sparql_query"] == EXAMPLE_QUERY
    assert result["analytics"]["prompt_assessment"]["decision"] == decision
    assert result["analytics"]["status"] == "complete"


def test_study_backend_failure_reports_known_tokens_without_private_exception_text():
    from agent_orchestration.adapters.prefetch import PrefetchedSparqlLLM

    translator = service()

    async def fail(request):
        error = ConnectionError("secret-key and patient-data")
        error.token_usage = TokenUsage(3, 1, model="failed-model", source="reported", complete=False)
        raise error

    translator.generator.run_with_usage = fail

    class SchemaServer:
        async def direct_call_tool(self, name, arguments):
            if name == "search_sparql_examples":
                return {"query_examples": []}
            return {"classes_schemas": [{"iri": "urn:Patient", "shex": "declared schema"}]}

    translator.generator = PrefetchedSparqlLLM(translator.generator, SchemaServer())
    with TestClient(server.create_app(translator)) as client:
        response = client.post(URL, json={"text": "count"})
    assert response.status_code == 502
    assert "secret-key" not in response.text and "patient-data" not in response.text
    analytics = response.json()["analytics"]
    assert analytics["status"] == "error" and analytics["failed_stage"] == "generation"
    assert analytics["prompt_assessment"]["decision"] == "allow"
    assert analytics["token_usage"]["known_total_tokens"] == 11
    assert analytics["token_usage"]["total_tokens"] is None
    assert analytics["token_usage"]["complete"] is False
    assert analytics["timings"]["generation"] >= 0
    assert analytics["timings"]["request_total"] >= analytics["timings"]["total"]
    assert analytics["generation_metadata"]["retrieval"]["classes"] == 1
    assert analytics["generation_metadata"]["retrieval"]["class_iris"] == ["urn:Patient"]


def test_study_timeout_keeps_partial_metrics(monkeypatch):
    monkeypatch.setattr(server, "REQUEST_TIMEOUT", .01)
    translator = service()

    async def wait(request):
        await asyncio.Event().wait()

    translator.generator.run_with_usage = wait
    with TestClient(server.create_app(translator)) as client:
        response = client.post(URL, json={"text": "count"})
    assert response.status_code == 504
    analytics = response.json()["analytics"]
    assert analytics["failed_stage"] == "generation"
    assert analytics["token_usage"]["known_total_tokens"] == 7
    assert analytics["token_usage"]["by_stage"]["generation"]["source"] == "unavailable"
    assert analytics["token_usage"]["total_tokens"] is None


def test_study_bad_input_does_not_run_models():
    translator = service()
    with TestClient(server.create_app(translator)) as client:
        response = client.post(URL, json={"text": "  "})
    assert response.status_code == 400 and translator.generator.calls == []


def test_study_analysis_failure_keeps_already_generated_query_and_usage(monkeypatch):
    from api import service as service_module

    def fail(query):
        raise RuntimeError("private implementation details")

    monkeypatch.setattr(service_module, "validate", fail)
    with TestClient(server.create_app(service())) as client:
        response = client.post(URL, json={"text": "count"})
    assert response.status_code == 502
    result = response.json()
    assert result["sparql_query"] == EXAMPLE_QUERY
    assert result["analytics"]["failed_stage"] == "analysis"
    assert result["analytics"]["token_usage"]["total_tokens"] == 22
    assert "private implementation details" not in response.text


def test_study_measures_waiting_for_shared_inference_lock():
    async def exercise():
        translator = service()
        original = translator.run
        entered, release, waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
        wait_started = None

        class ObservedLock(asyncio.Lock):
            async def acquire(self):
                nonlocal wait_started
                if self.locked():
                    wait_started = perf_counter()
                    waiting.set()
                return await super().acquire()

        async def run(text):
            if text == "first":
                entered.set()
                await release.wait()
            return await original(text)

        translator.run = run
        app = server.create_app(translator)
        async with app.router.lifespan_context(app):
            app.state.lock = ObservedLock()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                async with asyncio.timeout(5):
                    first = asyncio.create_task(client.post(URL, json={"text": "first"}))
                    await entered.wait()
                    second = asyncio.create_task(client.post(URL, json={"text": "second"}))
                    await waiting.wait()
                    held_seconds = perf_counter() - wait_started
                    release.set()
                    responses = await asyncio.gather(first, second)
        assert all(response.status_code == 200 for response in responses)
        assert len(translator.generator.calls) == 2
        measured = responses[1].json()["analytics"]["timings"]
        assert measured["queue"] >= held_seconds
        assert measured["request_total"] >= measured["queue"] + measured["total"]

    asyncio.run(exercise())


def test_standard_endpoint_does_not_strip_analytics_from_reused_service_result():
    class Cached:
        result = {"sparql_query": EXAMPLE_QUERY, "is_compliant": True, "tokens_consumed": 4,
                  "analytics": {"timings": {"total": .1}}}

        async def run(self, text):
            return self.result

    translator = Cached()
    with TestClient(server.create_app(translator)) as client:
        standard = client.post("/nl-to-sparql", json={"text": "count"}).json()
        study = client.post(URL, json={"text": "count"}).json()
    assert "analytics" not in standard
    assert study["analytics"]["timings"]["total"] == .1
    assert translator.result["analytics"] == {"timings": {"total": .1}}
