"""Full CLI wiring with real RDF execution and substituted model inference."""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace

import pytest

from agent_orchestration import FakeClassifier, FakeSparqlLLM, SystemOnePromptValidator
from agent_orchestration import cli
from sparql_analyzer.demo import EXAMPLE_QUERY
from tools.generate_synthetic_data import generate

pytestmark = pytest.mark.offline_workflow


@pytest.mark.parametrize("with_data,decision,query,status", [
    (False, "allow", EXAMPLE_QUERY, "query_ready"),
    (True, "allow", EXAMPLE_QUERY, "released"),
    (True, "block", EXAMPLE_QUERY, "blocked_prompt"),
    (True, "review", EXAMPLE_QUERY, "review_prompt"),
    (True, "allow", "DELETE WHERE { ?s ?p ?o }", "blocked_query"),
    (True, "allow", EXAMPLE_QUERY.replace("BilledDiagnosis", "OncologyDiagnosis"), "blocked_runtime"),
    (True, "allow", RuntimeError("private provider message"), "error"),
])
def test_cli_complete_workflow(tmp_path, monkeypatch, capsys, with_data, decision, query, status):
    config, schema, dataset = (tmp_path / name for name in ["models.json", "schema.txt", "cohort.trig"])
    config.write_text(json.dumps({"mcp_settings": None}))
    schema.write_text("SPHN patient named graphs")
    (tmp_path / "policy.txt").write_text("aggregate counts only")
    (tmp_path / "permissions.txt").write_text("authorized analyst")
    generate().serialize(dataset, format="trig")
    classifier, generator = FakeClassifier(decision), FakeSparqlLLM(query)
    @asynccontextmanager
    async def models(path):
        assert path == config
        yield SystemOnePromptValidator(classifier), generator
    monkeypatch.setattr(cli, "open_models", models)
    argv = ["generate_sparql", "--config", str(config), "--schema-file", str(schema), "--prompt", "Count patients"]
    if with_data:
        argv += ["--dataset", str(dataset)]
    monkeypatch.setattr("sys.argv", argv)
    assert cli.main() == (0 if status in {"query_ready", "released"} else 1)
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == status
    assert result["executed"] is (status == "released")
    assert "private provider message" not in repr(result)
    if status == "released":
        assert result["result"]["results"]["bindings"][0]["patients"]["value"] == "8"
    else:
        assert result["result"] is None
    if decision != "allow":
        assert generator.calls == []


def test_invalid_dataset_is_rejected_before_models_load(tmp_path, monkeypatch):
    for name, value in [("models.json", '{"mcp_settings": true}'), ("policy.txt", "policy"), ("permissions.txt", "analyst")]:
        (tmp_path / name).write_text(value)
    def unexpected_load(*args):
        pytest.fail("Models must not load when the dataset cannot be read")
    monkeypatch.setattr(cli, "open_models", unexpected_load)
    args = SimpleNamespace(config=tmp_path / "models.json", prompt="count", schema_file=None,
        policy_file=None, permissions_file=None, dataset=tmp_path / "missing.trig", rdf_format=None)
    with pytest.raises(FileNotFoundError):
        asyncio.run(cli.generate(args))
