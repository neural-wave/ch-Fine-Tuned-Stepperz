"""Empty retrieval is distinct from a broken MCP and from a security verdict."""
import pytest
from fastapi.testclient import TestClient

from api.server import create_app
from agent_orchestration.adapters.prefetch import PrefetchedSparqlLLM
from tests.api.test_server import service

pytestmark = pytest.mark.offline_workflow
PROMPT = "Genera soltanto un conteggio aggregato sul dataset clinico autorizzato per una demo, mantenendo tutti i controlli privacy."


class SchemaServer:
    def __init__(self, mode="empty"):
        self.mode = mode

    async def direct_call_tool(self, name, arguments):
        if self.mode == "network":
            raise ConnectionError("MCP unreachable")
        if name == "search_sparql_examples":
            return {"query_examples": []}
        return {} if self.mode == "invalid" else {"classes_schemas": []}


@pytest.mark.parametrize("path", ["/nl-to-sparql", "/study/nl-to-sparql"])
@pytest.mark.parametrize("decision", ["allow", "block", "review"])
def test_unmatched_schema_requests_clarification_without_changing_the_verdict(path, decision):
    translator = service(decision=decision)
    generator = translator.generator
    translator.generator = PrefetchedSparqlLLM(generator, SchemaServer())
    with TestClient(create_app(translator)) as client:
        response = client.post(path, json={"text": PROMPT})
    assert response.status_code == 400
    payload = response.json()
    assert "Specify what to count" in payload["error"]
    assert "sparql_query" not in payload and "is_compliant" not in payload
    assert generator.calls == []
    if path.startswith("/study"):
        analytics = payload["analytics"]
        assert analytics["prompt_decision"] == decision
        assert analytics["query_analysis"] is None and not analytics["executed"]
        metadata = analytics["generation_metadata"]
        assert metadata["model_called"] is False
        assert metadata["retrieval"]["status"] == "no_match"
        assert metadata["retrieval"]["hints"] == [PROMPT]
        assert analytics["token_usage"]["known_total_tokens"] == 7


@pytest.mark.parametrize("mode,classes", [("network", ()), ("invalid", ()),
    ("empty", ("SubjectPseudoIdentifier",))])
def test_broken_mcp_or_unresolved_explicit_classes_still_return_502(mode, classes):
    translator = service()
    generator = translator.generator
    translator.generator = PrefetchedSparqlLLM(generator, SchemaServer(mode), classes=classes)
    with TestClient(create_app(translator)) as client:
        response = client.post("/study/nl-to-sparql", json={"text": PROMPT})
    assert response.status_code == 502
    assert generator.calls == []
