"""An unsupported category aggregate is not evidence of malicious intent."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from rdflib import Dataset

from agent_orchestration import (
    FakeClassifier, FakeSparqlLLM, PromptRequest, SparqlWorkflow,
    StaticQueryAnalyzer, SystemOnePromptValidator,
)
from sparql_analyzer.compliance import validate
from sparql_analyzer.configuration.policy import DEFAULT_POLICY
from sparql_analyzer.runtime import ResultBlocked, execute_checked
from tests.paths import ROOT

QUERY = (ROOT / "tests/fixtures/regressions/billed-diagnosis-by-sex.rq").read_text(encoding="utf-8")


def test_logged_query_is_unsupported_rather_than_a_confirmed_rule_violation():
    verdict = validate(QUERY)
    assert verdict["status"] == "unsupported" and not verdict["is_compliant"]
    assert verdict["violations"] == []
    assert {finding["check"] for finding in verdict["findings"]} == {"category_group"}


def test_workflow_keeps_the_reason_and_does_not_execute_the_logged_query():
    executor = SimpleNamespace(run=AsyncMock())
    workflow = SparqlWorkflow(SystemOnePromptValidator(FakeClassifier("allow")),
                              FakeSparqlLLM(QUERY), StaticQueryAnalyzer(), executor)
    outcome = asyncio.run(workflow.run(PromptRequest(
        "Is cholera more common in men, women or patients of indeterminate sex, any diagnosis rank?",
        "SPHN schema", "authorized aggregate statistics")))
    assert outcome.status == "blocked_query"
    assert outcome.analysis["status"] == "unsupported"
    assert outcome.query == QUERY and outcome.result is None
    executor.run.assert_not_awaited()


def test_disabling_only_category_check_does_not_add_runtime_support():
    policy = DEFAULT_POLICY.with_checks(category_group=False)
    assert validate(QUERY, policy=policy)["is_compliant"]
    with pytest.raises(ResultBlocked, match="Struttura non supportata"):
        execute_checked(Dataset(), QUERY, policy=policy)


def test_named_graph_and_valid_sex_predicate_do_not_remove_category_limit():
    query = '''PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>
SELECT ?sex (COUNT(DISTINCT ?g) AS ?patients) WHERE {
  GRAPH ?g {
    ?diagnosis a sphn:BilledDiagnosis ; sphn:hasSubjectPseudoIdentifier ?patient .
    ?administrativeSex a sphn:AdministrativeSex ;
        sphn:hasSubjectPseudoIdentifier ?patient ; sphn:hasCode ?sex .
  }
} GROUP BY ?sex'''
    verdict = validate(query)
    assert verdict["status"] == "unsupported"
    assert {f["check"] for f in verdict["findings"]} == {"category_group"}
