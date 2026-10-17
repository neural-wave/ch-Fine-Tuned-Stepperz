"""Corpus merging and end-to-end evaluation artifacts, with simulated HTTP only."""
import csv
import json

import httpx
import pytest

from system_validation import runner
from system_validation.client import Clients
from system_validation.settings import load_cases, read_config

pytestmark = pytest.mark.offline_workflow


def test_default_corpus_merges_versions_and_keeps_provenance():
    config = read_config()
    cases = load_cases(config["cases_files"])["cases"]
    assert len({row["prompt"].strip() for row in cases}) == len(cases)
    assert {row["malicious"] for row in cases} == {True, False}
    first = next(row for row in cases if row["prompt"] == "How many patients are in the database?")
    assert first["malicious"] is False
    assert len(first["sources"]) == 3
    assert any("prompts.json" in source["file"] for row in cases for source in row["sources"])
    assert not any("reference" in row or "expected_result" in row for row in cases)


def test_merging_rejects_conflicting_labels(tmp_path):
    paths = [tmp_path / "a.jsonl", tmp_path / "b.jsonl"]
    for path, label in zip(paths, [True, False]):
        path.write_text(json.dumps({"id": "a", "question": "Same prompt", "compliant": label}), encoding="utf-8")
    with pytest.raises(ValueError, match="Conflicting labels"):
        load_cases(paths)


def test_api_only_runs_every_unique_prompt_and_keeps_all_statistics(tmp_path, monkeypatch):
    config = read_config()
    config.update(out_dir=tmp_path, repeats=1, warmup=1)
    cases = load_cases(config["cases_files"])["cases"]
    expected = {row["prompt"]: row["malicious"] for row in cases}
    received = []

    def respond(request):
        assert request.url.path == "/nl-to-sparql"
        body = json.loads(request.content)
        assert set(body) == {"text"}
        assert request.headers["x-include-analytics"] == "true"
        received.append(body["text"])
        return httpx.Response(200, json={"is_compliant": not expected[body["text"]],
            "sparql_query": "SELECT (COUNT(*) AS ?n) WHERE {}", "tokens_consumed": 15,
            "analytics": {"prompt_decision": "block" if expected[body["text"]] else "allow",
                "timings": {"prompt_validation": .1, "generation": .2, "total": .3},
                "token_usage": {"by_stage": {
                    "prompt_validation": {"model": "fake-classifier", "input_tokens": 3, "output_tokens": 0, "requests": 1},
                    "generation": {"model": "fake-generator", "input_tokens": 7, "output_tokens": 5, "requests": 1}}}}})

    def no_database(*args):
        pytest.fail("API-only must not inspect or query Virtuoso")

    monkeypatch.setattr(runner, "ready", no_database)
    clients = Clients(config, transport=httpx.MockTransport(respond))
    try:
        directory, report = runner.run(config, clients, api_only=True, label="simulated")
    finally:
        clients.close()
    assert len(received) == len(cases) + 1
    rows = [json.loads(line) for line in (directory / "trials.jsonl").read_text(encoding="utf-8").splitlines()]
    measured = [row for row in rows if not row["warmup"]]
    assert all(row["correct"] is True and row["total_seconds"] >= row["api_seconds"] for row in measured)
    assert all(row["prompt_correct"] is True for row in measured)
    assert all(row["effective_total_tokens_per_second"] > 0 for row in measured)
    assert all(row["execution"]["status"] == "disabled" for row in rows)
    metrics = report["metrics"]
    assert metrics["classification"]["cases"] == len(cases)
    assert metrics["resources"]["total_tokens"] == 15 * len(cases)
    assert metrics["resources"]["by_model"]["fake-classifier"]["known_input_tokens"] == 3 * len(cases)
    assert metrics["resources"]["by_model"]["fake-generator"]["known_output_tokens"] == 5 * len(cases)
    assert metrics["warmup_resources"]["total_tokens"] == 15
    assert len(metrics["by_case"]) == len(cases)
    assert report["metadata"]["api_only"] is True
    assert report["metadata"]["status"] == "complete"
    assert len(report["metadata"]["case_sources"]) == 4
    assert (directory / "cases.json").is_file()
    assert not (directory / "load-receipt.json").exists()
    log = (directory / "execution.log").read_text(encoding="utf-8")
    assert "Case started" in log and "tokens_consumed" in log and "Validation metrics" in log
    with (directory / "trials.csv").open(encoding="utf-8", newline="") as stream:
        table = list(csv.DictReader(stream))
    assert len(table) == len(rows)
    assert {"correct", "outcome", "total_seconds", "tokens_consumed"} <= table[0].keys()


def test_api_errors_are_measured_and_do_not_stop_later_cases(tmp_path):
    source = tmp_path / "cases.json"
    source.write_text(json.dumps({"version": 1, "cases": [
        {"id": "failed", "prompt": "unreachable", "malicious": True},
        {"id": "later", "prompt": "aggregate", "malicious": False}]}), encoding="utf-8")
    config = dict(cases_file=source, out_dir=tmp_path / "reports", warmup=0, repeats=1,
                  api_url="http://api.test", timeout_seconds=1)

    def respond(request):
        if json.loads(request.content)["text"] == "unreachable":
            return httpx.Response(502, json={"error": "model failed"})
        return httpx.Response(200, json={"is_compliant": True, "sparql_query": "SELECT * WHERE {}", "tokens_consumed": 4})

    clients = Clients(config, transport=httpx.MockTransport(respond))
    try:
        directory, report = runner.run(config, clients, api_only=True)
    finally:
        clients.close()
    metrics = report["metrics"]
    assert metrics["classification"]["coverage"] == .5
    assert metrics["classification"]["accuracy"] == .5
    assert metrics["classification"]["errors"]["malicious"] == 1
    assert metrics["resources"]["total_tokens"] is None
    assert metrics["resources"]["known_total_tokens"] == 4
    rows = [json.loads(line) for line in (directory / "trials.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["outcome"] == "error" and rows[0]["correct"] is None
    assert rows[1]["outcome"] == "tn"
    assert "HTTPStatusError" in (directory / "execution.log").read_text(encoding="utf-8")


def test_interruption_preserves_partial_reports_and_closes_log(tmp_path):
    source = tmp_path / "cases.json"
    source.write_text(json.dumps({"version": 1, "cases": [
        {"id": "first", "prompt": "aggregate", "malicious": False},
        {"id": "second", "prompt": "interrupt", "malicious": True}]}), encoding="utf-8")
    config = dict(cases_file=source, out_dir=tmp_path / "reports", warmup=0, repeats=1,
                  api_url="http://api.test", timeout_seconds=1)

    def respond(request):
        if json.loads(request.content)["text"] == "interrupt":
            raise KeyboardInterrupt("stop evaluation")
        return httpx.Response(200, json={"is_compliant": False, "sparql_query": "SELECT * WHERE {}", "tokens_consumed": 4,
            "analytics": {"prompt_decision": "allow"}})

    clients = Clients(config, transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(KeyboardInterrupt, match="stop evaluation"):
            runner.run(config, clients, api_only=True)
    finally:
        clients.close()
    directory, = config["out_dir"].iterdir()
    report = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    assert report["metadata"]["status"] == "invalid_or_interrupted"
    assert report["metrics"]["classification"]["confusion_matrix"]["fp"] == 1
    assert report["metrics"]["prompt_guard"]["confusion_matrix"]["tn"] == 1
    with (directory / "trials.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]["correct"] == "False" and rows[0]["prompt_correct"] == "True"
    assert "stop evaluation" in (directory / "execution.log").read_text(encoding="utf-8")
