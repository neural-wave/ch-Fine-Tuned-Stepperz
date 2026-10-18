"""Request examples reach Laya without benchmark reference SPARQL."""
import asyncio
from dataclasses import asdict
import json
import sys
from types import SimpleNamespace

import pytest

from agent_orchestration.adapters.laya import laya_validator, load_classifier, load_prompt_few_shots
from agent_orchestration.models import DecisionRequest, SparqlRequest
from tests.paths import ROOT


pytestmark = pytest.mark.offline_workflow


def test_laya_payload_contains_labels_but_no_reference_sparql():
    examples = load_prompt_few_shots(ROOT / "config/agents/prompt_few_shots.json")
    observed = {}

    def predict(state, questions, max_len):
        observed["state"] = json.loads(state)
        observed["instructions"] = questions["decision"]["instructions"]
        return {"usage": {"input_tokens": 100}, "answers": {"decision": {"choice": "allow"}}}

    guard = laya_validator(SimpleNamespace(predict=predict), few_shots=examples)
    current = SparqlRequest("current request", "schema", "policy", "analyst")
    response = guard.model.predict(DecisionRequest(json.dumps(asdict(current)), "Assess current request", {
        "allow": "authorized", "block": "prohibited", "review": "ambiguous"}))
    assert response.output.choice == "allow"
    assert response.metadata["few_shot_examples"] == 15
    assert observed["state"]["prompt"] == "current request"
    assert observed["state"]["permissions"] == "analyst"
    assert len(observed["state"]["few_shot_examples"]) == 15
    assert all(set(row) == {"prompt", "decision"} for row in observed["state"]["few_shot_examples"])
    assert [row["decision"] for row in observed["state"]["few_shot_examples"]] == ["allow"] * 10 + ["block"] * 5
    assert "current prompt" in observed["instructions"]


def test_configured_laya_uses_request_only_organizer_few_shots(tmp_path, monkeypatch):
    source = ROOT / "config/agents/prompt_few_shots.json"
    dataset = json.loads(source.read_text(encoding="utf-8"))
    assert len(dataset["examples"]) == 15
    assert [row["decision"] for row in dataset["examples"]] == ["allow"] * 10 + ["block"] * 5
    assert all(set(row) == {"id", "prompt", "decision"} for row in dataset["examples"])

    (tmp_path / "examples.json").write_text(json.dumps(dataset), encoding="utf-8")
    config = tmp_path / "models.json"
    config.write_text(json.dumps({"laya": {"model_id": "test-laya", "few_shot_file": "examples.json"}}), encoding="utf-8")
    observed = {}

    def predict(state, questions, max_len):
        observed["state"] = json.loads(state)
        observed["instructions"] = questions["decision"]["instructions"]
        observed["max_len"] = max_len
        return {"usage": {"input_tokens": 100}, "answers": {"decision": {"choice": "block"}}}

    def load(model_id, **settings):
        assert model_id == "test-laya" and settings == {}
        return SimpleNamespace(predict=predict)

    monkeypatch.setitem(sys.modules, "laya", SimpleNamespace(load=load))
    guard = asyncio.run(load_classifier(config))
    result = asyncio.run(guard.run_with_usage(SparqlRequest("current request", "schema", "policy", "analyst")))
    assert result.output.decision == "block"
    assert observed["state"]["prompt"] == "current request"
    assert observed["state"]["permissions"] == "analyst"
    assert observed["state"]["few_shot_examples"] == [
        {"prompt": row["prompt"], "decision": row["decision"]} for row in dataset["examples"]]
    assert "few_shot_examples" in observed["instructions"]
    assert "query" not in observed["state"]["few_shot_examples"][0]
    assert observed["max_len"] == 8192


def test_prompt_few_shots_reject_reference_query_fields(tmp_path):
    path = tmp_path / "examples.json"
    path.write_text(json.dumps({"version": 1, "examples": [
        {"id": 1, "prompt": "Count patients", "decision": "allow", "query": "SELECT * WHERE {}"}]}),
        encoding="utf-8")
    with pytest.raises(ValueError, match="only id, prompt and decision"):
        load_prompt_few_shots(path)
