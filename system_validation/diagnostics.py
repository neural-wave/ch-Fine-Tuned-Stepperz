"""Evaluation-only diagnostics; references are never submitted to the API."""
from collections import Counter

from sparql_analyzer.validation import validate


def diagnose(row):
    response = row.get("response", {})
    analytics = response.get("analytics", {})
    analysis = analytics.get("query_analysis")
    source = "server" if isinstance(analysis, dict) else None
    # Older runs did not retain the server analysis. A current local check is
    # useful evidence, but cannot reconstruct the historical server decision.
    if source is None and response.get("sparql_query"):
        analysis, source = validate(response["sparql_query"]), "local_recheck"
    causes = []
    decision = analytics.get("prompt_decision")
    if decision in {"block", "review"}:
        causes.append("prompt_" + decision)
    if source == "server" and analysis.get("status") in {"unsupported", "non_compliant"}:
        causes.append("query_" + analysis["status"])
    if row.get("error"):
        causes.append("technical_error")
    if row.get("predicted_malicious") is True and not causes:
        causes.append("unknown_rejection")
    reference = row.get("reference_query")
    return {"causes": causes, "failed_stage": analytics.get("failed_stage"),
            "compliance_reason": response.get("compliance_reason"),
            "query_analysis_source": source, "query_analysis": analysis,
            "reference_analysis": validate(reference) if reference else None}


def diagnostic_summary(rows):
    diagnostics = [row.get("diagnostics") or diagnose(row) for row in rows]
    return {"causes": dict(Counter(cause for item in diagnostics for cause in item["causes"])),
            "server_query_statuses": dict(Counter(item["query_analysis"]["status"] for item in diagnostics
                if item["query_analysis_source"] == "server" and item["query_analysis"].get("status"))),
            "local_recheck_statuses": dict(Counter(item["query_analysis"]["status"] for item in diagnostics
                if item["query_analysis_source"] == "local_recheck" and item["query_analysis"].get("status"))),
            "failed_stages": dict(Counter(item["failed_stage"] for item in diagnostics if item["failed_stage"])),
            "reference_statuses": dict(Counter(item["reference_analysis"]["status"]
                for item in diagnostics if item["reference_analysis"])),
            "note": "Causes can overlap. Unsupported queries are checker coverage gaps, not proof of malicious intent. Reference checks use the current local default policy, not semantic equivalence."}
