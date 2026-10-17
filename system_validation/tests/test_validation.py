"""Benchmark wiring and metrics with HTTP doubles; no live services or inference."""
import json
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest

from system_validation import runner, virtuoso
from system_validation.client import Clients
from system_validation.settings import load_cases, read_config
from sparql_analyzer.demo import EXAMPLE_QUERY

pytestmark = pytest.mark.offline_workflow


def result(value="8"):
    return {"head": {"vars": ["patients"]}, "results": {"bindings": [
        {"patients": {"type": "literal", "datatype": "http://www.w3.org/2001/XMLSchema#integer", "value": value}}]}}


def test_http_runner_records_tokens_timings_and_never_executes_malicious_labels(tmp_path, monkeypatch):
    cases = [{"id": name, "prompt": name, "malicious": label, "category": "test"} for name, label in
             [("benign", False), ("attack", True), ("false_positive", False), ("false_negative", True), ("error", True)]]
    case_file, receipt_file = tmp_path / "cases.json", tmp_path / "ready.json"
    case_file.write_text(json.dumps({"version": 1, "cases": cases}))
    receipt_file.write_text("{}")
    config = {"api_url": "http://api.test", "virtuoso_url": "http://db.test/sparql", "timeout_seconds": 5,
              "cases_file": case_file, "receipt_file": receipt_file, "out_dir": tmp_path,
              "warmup": 1, "repeats": 1, "query_repeats": 2}
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.host == "db.test":
            return httpx.Response(200, json=result())
        body = json.loads(request.content)
        assert set(body) == {"text"}  # Labels never reach the system being evaluated.
        assert request.headers["x-include-analytics"] == "true"
        if body["text"] == "error":
            return httpx.Response(502, json={"error": "unavailable"})
        allow = body["text"] in {"benign", "false_negative"}
        return httpx.Response(200, json={"is_compliant": allow, "sparql_query": EXAMPLE_QUERY,
            "tokens_consumed": 15, "analytics": {"prompt_decision": "allow" if allow else "block",
            "token_usage": {"by_stage": {"generation": {"model": "scripted", "input_tokens": 10,
                "output_tokens": 5, "requests": 1, "cache_read_tokens": 3}}}, "timings": {"generation": 2.0}}})
    checks = []
    def ready(config, clients):
        checks.append(1)
        return {"sources": {"patients": [{}], "ontologies": [{}]}}
    monkeypatch.setattr(runner, "ready", ready)
    clients = Clients(config, transport=httpx.MockTransport(respond))
    try:
        directory, report = runner.run(config, clients)
    finally:
        clients.close()
    assert len(checks) == 2
    assert sum(request.url.host == "db.test" for request in calls) == 3  # One warmup + two repeats, only benign.
    rows = [json.loads(line) for line in (directory / "trials.jsonl").read_text().splitlines()]
    assert len(rows) == 6 and rows[0]["warmup"]
    assert next(row for row in rows if row["id"] == "false_negative")["execution"]["status"] == "not_eligible"
    assert (directory / "summary.json").is_file() and (directory / "trials.csv").is_file()
    assert (directory / "metrics.log").is_file()


def test_run_requires_prepared_data_before_any_model_call(tmp_path, monkeypatch):
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"version": 1, "cases": [{"id": "a", "prompt": "p", "malicious": False}]}))
    config = {"cases_file": cases, "receipt_file": tmp_path / "missing.json"}
    with pytest.raises(ValueError, match="receipt"):
        runner.run(config, object())


def test_partial_virtuoso_results_are_rejected():
    clients = Clients({"virtuoso_url": "http://db/sparql", "timeout_seconds": 1},
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=result(), headers={"X-SQL-State": "S1TAT"})))
    try:
        with pytest.raises(ValueError, match="incomplete"):
            clients.query("SELECT (COUNT(*) AS ?n) WHERE {}")
    finally:
        clients.close()


def test_sources_do_not_silently_use_nested_sample(tmp_path):
    nested = tmp_path / "patients/sample"
    nested.mkdir(parents=True)
    (nested / "p.ttl").write_text("<urn:s> <urn:p> <urn:o> .")
    with pytest.raises(ValueError, match="top-level"):
        virtuoso.sources({"patients_dir": nested.parent})


def test_loader_errors_and_stale_graphs_are_fatal(tmp_path, monkeypatch):
    (tmp_path / "patient.ttl").touch()
    config = {"patients_dir": tmp_path, "graph_prefix": "http://example.org/graph/", "rule_set": "urn:rule"}
    counts = iter([1, 1, 1])
    monkeypatch.setattr(virtuoso, "sql_number", lambda *a: next(counts))
    with pytest.raises(ValueError, match="Incomplete load"):
        virtuoso.check_database(config, object(), 1)
    counts = iter([1, 0, 1])
    class Client:
        def query(self, query):
            return {"results": {"bindings": [{"g": {"value": "http://example.org/graph/stale"}, "triples": {"value": "1"}}]}}, .1
    with pytest.raises(ValueError, match="graphs differ"):
        virtuoso.check_database(config, Client(), 1)


def test_cache_is_refreshed_from_the_current_archive(tmp_path):
    ontologies, cache = tmp_path / "ontologies", tmp_path / "cache"
    ontologies.mkdir()
    cache.mkdir()
    (cache / "ontology.ttl").write_text("old")
    with ZipFile(ontologies / "terms.zip", "w") as archive:
        archive.writestr("nested/ontology.ttl", "new")
    virtuoso.refresh_archives({"ontologies_dir": ontologies, "ontology_cache_dir": cache})
    assert (cache / "ontology.ttl").read_text() == "new"


def test_starter_dataset_has_both_classes_and_no_expected_queries():
    payload = load_cases(Path(__file__).resolve().parents[1] / "data/prompts.json")
    assert {row["malicious"] for row in payload["cases"]} == {True, False}
    assert all("reference_query" not in row for row in payload["cases"])
    assert read_config()["repeats"] == 1
