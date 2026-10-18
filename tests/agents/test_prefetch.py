"""Prefetch keeps retrieval outside the model and preserves workflow gates."""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("pydantic_ai")
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from agent_orchestration import PromptRequest, SparqlWorkflow, StaticQueryAnalyzer
from agent_orchestration import local_models
from agent_orchestration.adapters.prefetch import PrefetchedSparqlLLM, SchemaRetrievalMiss
from agent_orchestration.models import ModelResponse as Response, SparqlResult, TokenUsage
from agent_orchestration.validation import PromptValidation
from sparql_analyzer.demo import EXAMPLE_QUERY
from tests.agents.test_shared_mcp import shared_server
from tools import benchmark_inference

pytestmark = pytest.mark.offline_workflow


@pytest.mark.parametrize("prompt,hints,expected_class", [
    ("Count patients with BilledDiagnosis", ["BilledDiagnosis"], "BilledDiagnosis"),
    ("How many patients are in the database?", [], "SubjectPseudoIdentifier"),
    ("Quanti pazienti ci sono nel database?", [], "SubjectPseudoIdentifier"),
    ("What is the average length of a hospital stay in days?", [], "AdministrativeCase"),
    ("How many births are recorded?", [], "Birth"),
])
def test_prefetch_actual_mcp_needs_one_model_turn(tmp_path, monkeypatch, prompt, hints, expected_class):
    calls = []
    query = EXAMPLE_QUERY.replace("sphn:BilledDiagnosis", "sphn:" + expected_class)
    def respond(messages, info):
        calls.append(messages)
        assert info.function_tools == []
        payload = json.loads(messages[-1].parts[-1].content)
        assert payload["policy"] == "trusted policy"
        assert payload["permissions"] == "analyst"
        assert "UNTRUSTED MCP RETRIEVAL" in payload["schema"]
        assert "void_schema_aggregate_pattern" in payload["schema"]
        assert expected_class in payload["schema"]
        assert "declared_value_types" in payload["schema"]
        assert '"shex"' not in payload["schema"]
        assert "not fixed data values" in payload["schema"]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"query": query})])
    monkeypatch.setattr(local_models, "chat_model", lambda *a: FunctionModel(respond))
    request = PromptRequest(prompt, "trusted schema", "trusted policy", "analyst")
    with shared_server(tmp_path) as url:
        config = tmp_path / "models.json"
        config.write_text(json.dumps({"base_url": "http://unused/v1", "model": "scripted",
            "mcp_url": url, "generation_mode": "prefetch", "retrieval_classes": hints}))
        async def exercise():
            async with local_models.open_generator(config) as generator:
                for _ in range(2):
                    response = await generator.run_with_usage(request)
                    assert response.output.query == query
                    assert response.usage.requests == 1
                    retrieval = response.metadata["retrieval"]
                    assert retrieval["classes"] > 0 and retrieval["examples"] > 0
                    assert retrieval["seconds"] >= 0
                    assert any(value.endswith(expected_class) for value in retrieval["class_iris"])
        asyncio.run(exercise())
    assert len(calls) == 2
    assert request.schema == "trusted schema"


@pytest.mark.parametrize("broken", ["examples", "schema", "network"])
def test_retrieval_failure_never_calls_generator(broken):
    class Server:
        async def direct_call_tool(self, name, args):
            if broken == "network":
                raise ConnectionError("MCP unavailable")
            if name == "search_sparql_examples":
                return {} if broken == "examples" else {"query_examples": []}
            return {"classes_schemas": []}
    class Generator:
        async def run_with_usage(self, request):
            pytest.fail("No generation with missing retrieval")
    with pytest.raises((ValueError, ConnectionError)):
        asyncio.run(PrefetchedSparqlLLM(Generator(), Server()).run(PromptRequest("p", "s", "policy")))


def test_generic_aggregate_prompt_is_a_lookup_miss_with_the_actual_mcp(tmp_path):
    prompt = "Genera soltanto un conteggio aggregato sul dataset clinico autorizzato per una demo, mantenendo tutti i controlli privacy."
    with shared_server(tmp_path) as url:
        async def exercise():
            async with local_models.schema_server({"mcp_url": url}) as server:
                # None makes any accidental call to the generator fail the test.
                generator = PrefetchedSparqlLLM(None, server)
                with pytest.raises(SchemaRetrievalMiss) as caught:
                    await generator.run(PromptRequest(prompt, "schema", "policy"))
                metadata = caught.value.model_metadata
                assert metadata["model_called"] is False
                assert metadata["retrieval"]["status"] == "no_match"
                assert metadata["retrieval"]["hints"] == [prompt]
        asyncio.run(exercise())


def test_prefetch_does_not_weaken_prompt_gate():
    class Guard:
        async def run(self, request):
            return PromptValidation("block", "forbidden")
    class Server:
        async def direct_call_tool(self, *args):
            pytest.fail("Blocked prompt must never reach MCP")
    workflow = SparqlWorkflow(Guard(), PrefetchedSparqlLLM(None, Server()), StaticQueryAnalyzer())
    result = asyncio.run(workflow.run(PromptRequest("p", "s", "policy"), execute=False))
    assert result.status == "blocked_prompt"


def test_empty_schema_reports_the_actual_retrieval_hints(caplog):
    class Server:
        async def direct_call_tool(self, name, args):
            if name == "search_sparql_examples":
                return {"query_examples": [{"class_iri": "urn:MissingClass"}]}
            return {"classes_schemas": []}

    class Generator:
        async def run_with_usage(self, request):
            pytest.fail("Generation must not run without schema")

    with pytest.raises(ValueError, match="urn:MissingClass"):
        asyncio.run(PrefetchedSparqlLLM(Generator(), Server()).run(PromptRequest("unmatched question", "s", "p")))
    assert "unmatched question" in caplog.text
    assert "urn:MissingClass" in caplog.text
    assert "example_count=1" in caplog.text


@pytest.mark.parametrize("field,value", [("generation_mode", "unknown"), ("retrieval_classes", "BilledDiagnosis")])
def test_invalid_mode_configuration(tmp_path, field, value):
    config = tmp_path / "models.json"
    config.write_text(json.dumps({field: value}))
    async def exercise():
        async with local_models.open_generator(config):
            pytest.fail("Invalid configuration accepted")
    with pytest.raises(ValueError):
        asyncio.run(exercise())


def test_benchmark_preserves_failures_usage_and_warmup(tmp_path, monkeypatch):
    config = tmp_path / "models.json"
    config.write_text(json.dumps({"model": "scripted", "mcp_url": "http://unused/mcp"}))
    (tmp_path / "policy.txt").write_text("aggregates")
    (tmp_path / "permissions.txt").write_text("analyst")
    loads = []
    class Guard:
        async def run(self, request):
            return PromptValidation("allow", "test")
    async def load(path):
        loads.append(path)
        return Guard()
    @asynccontextmanager
    async def generator(path, *, generation_mode):
        class Generator:
            async def run_with_usage(self, request):
                query = EXAMPLE_QUERY if generation_mode == "prefetch" else "DELETE WHERE { ?s ?p ?o }"
                return Response(SparqlResult(query), TokenUsage(10, 5, source="simulated", requests=1))
        yield Generator()
    monkeypatch.setattr(benchmark_inference, "load_classifier", load)
    monkeypatch.setattr(benchmark_inference, "open_generator", generator)
    args = SimpleNamespace(config=config, prompt="count", schema_file=None, policy_file=None,
        permissions_file=None, label="offline", warmup=1, repeats=2, timeout=30,
        modes=["agentic", "prefetch"], out=tmp_path / "report.json")
    report = asyncio.run(benchmark_inference.benchmark(args))
    assert len(loads) == 1
    assert report["modes"]["agentic"]["summary"]["accepted"] == 0
    assert report["modes"]["agentic"]["summary"]["accepted_median_seconds"] is None
    assert report["modes"]["prefetch"]["summary"]["accepted"] == 2
    rows = report["modes"]["prefetch"]["runs"]
    assert len(rows) == 3 and rows[0]["warmup"]
    assert rows[1]["outcome"]["analytics"]["token_usage"]["by_stage"]["generation"]["requests"] == 1
    assert json.loads(args.out.read_text())["semantic_validation"].startswith("not_checked")
