"""Failure accounting and refusal diagnosis, without inference or database."""
import json

import httpx
import pytest

from system_validation.client import Clients
from system_validation.diagnostics import diagnose
from system_validation.metrics import resources, summarize
from system_validation.report import rebuild
from system_validation.runner import trial
from sparql_analyzer.demo import EXAMPLE_QUERY

pytestmark = pytest.mark.offline_workflow


@pytest.mark.parametrize("status", [502, 504])
def test_failure_retains_guard_verdict_and_partial_usage(status):
    payload = {"error": "failed", "analytics": {"prompt_decision": "allow", "failed_stage": "generation",
        "token_usage": {"complete": False, "total_tokens": None, "known_total_tokens": 11,
                        "by_stage": {"prompt_validation": {"model": "guard", "input_tokens": 7,
                            "output_tokens": 0}, "generation": {"model": "generator", "input_tokens": 4}}}}}
    def respond(request):
        assert request.url.path == "/study/nl-to-sparql"
        assert json.loads(request.content) == {"text": "count"}
        return httpx.Response(status, json=payload)
    clients = Clients({"api_url": "http://api.test", "timeout_seconds": 1}, transport=httpx.MockTransport(respond))
    try:
        row = trial({"id": "a", "prompt": "count", "malicious": False}, clients, {}, index=0, warmup=False, api_only=True)
    finally:
        clients.close()
    assert row["response"] == payload
    assert row["http_status"] == status
    assert row["predicted_malicious"] is None and row["outcome"] == "error"
    report = summarize([row])
    assert report["prompt_guard"]["confusion_matrix"]["tn"] == 1
    assert report["classification"]["valid_verdicts"] == 0
    assert report["resources"]["total_tokens"] is None
    assert report["resources"]["known_total_tokens"] == 11
    assert report["resources"]["calls_with_partial_token_usage"] == 1
    assert report["diagnostics"]["failed_stages"] == {"generation": 1}


def test_complete_failure_accounting_and_partial_usage_are_not_double_counted():
    rows = [{"api_seconds": 1, "response": response} for response in [
        {"tokens_consumed": 8, "analytics": {"token_usage": {"complete": True, "total_tokens": 8, "known_total_tokens": 8}}},
        {"error": "analysis failed", "analytics": {"token_usage": {"complete": True, "total_tokens": 9, "known_total_tokens": 9}}}]]
    assert resources(rows)["total_tokens"] == 17
    assert resources(rows)["known_total_tokens"] == 17
    rows.append({"api_seconds": 1, "response": {"analytics": {"token_usage": {
        "complete": False, "known_total_tokens": 3}}}})
    assert resources(rows)["total_tokens"] is None
    assert resources(rows)["known_total_tokens"] == 20
    assert resources(rows)["calls_without_token_usage"] == 0


def test_server_unsupported_and_prompt_review_are_independent_causes():
    row = {"predicted_malicious": True, "reference_query": EXAMPLE_QUERY,
           "response": {"sparql_query": "invalid", "analytics": {"prompt_decision": "review",
               "query_analysis": {"status": "unsupported", "is_compliant": False, "findings": []}}}}
    diagnostic = diagnose(row)
    assert diagnostic["causes"] == ["prompt_review", "query_unsupported"]
    assert diagnostic["query_analysis_source"] == "server"
    assert diagnostic["reference_analysis"]["status"] == "compliant"


def test_offline_report_preserves_original_and_cannot_invent_missing_tokens(tmp_path, monkeypatch):
    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps({"id": "a", "question": "count", "compliant": True,
                                "reference": EXAMPLE_QUERY}), encoding="utf-8")
    source = tmp_path / "trials.jsonl"
    row = {"id": "old:a", "prompt": "count", "malicious": False, "warmup": False,
           "api_seconds": 1, "predicted_malicious": True, "response": {
               "is_compliant": False, "sparql_query": "SELECT * WHERE {}", "tokens_consumed": 4},
           "execution": {"status": "disabled"}}
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    original = source.read_bytes()
    def no_http(*args, **kwargs):
        pytest.fail("Offline reports must not contact any service")
    monkeypatch.setattr(httpx.Client, "send", no_http)
    directory, report = rebuild({"cases_file": cases, "out_dir": tmp_path / "reports"}, source)
    assert source.read_bytes() == original
    enriched = json.loads((directory / "trials.jsonl").read_text(encoding="utf-8"))
    assert enriched["diagnostics"]["query_analysis_source"] == "local_recheck"
    assert enriched["diagnostics"]["causes"] == ["unknown_rejection"]
    assert enriched["reference_query"] == EXAMPLE_QUERY
    assert report["metrics"]["diagnostics"]["reference_statuses"] == {"compliant": 1}
    assert report["metrics"]["classification"]["both_classes_present"] is False
    assert report["metrics"]["resources"]["known_total_tokens"] == 4
    assert report["metrics"]["resources"]["calls_missing_detailed_analytics"] == 1


def test_non_json_failure_is_still_an_error():
    clients = Clients({"api_url": "http://api.test", "timeout_seconds": 1},
                      transport=httpx.MockTransport(lambda request: httpx.Response(502, text="bad gateway")))
    try:
        row = trial({"id": "a", "prompt": "count", "malicious": False}, clients, {}, index=0, warmup=False, api_only=True)
    finally:
        clients.close()
    assert row["predicted_malicious"] is None
    assert resources([row])["calls_without_token_usage"] == 1


def test_single_class_sample_exposes_support_and_undefined_recall():
    row = {"id": "a", "malicious": False, "predicted_malicious": False,
           "warmup": False, "api_seconds": 1, "response": {"tokens_consumed": 0}}
    result = summarize([row])["classification"]
    assert result["class_support"] == {"malicious": 0, "benign": 1}
    assert result["both_classes_present"] is False
    assert result["recall"] is None
