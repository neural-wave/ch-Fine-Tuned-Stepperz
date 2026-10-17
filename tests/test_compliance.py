"""Regressioni del validatore: alias, scope, query valide e blocchi conservativi."""

import json
from pathlib import Path

import pytest

from sparql_analyzer.compliance import validate


PREFIX = "PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>\n"
PATTERN = "GRAPH ?g { ?dx a sphn:BilledDiagnosis . }"


def check_query(body, compliant=False, rule=None, status=None):
    result = validate(PREFIX + body)
    assert result["is_compliant"] == compliant, result
    if rule:
        assert rule in result["violations"], result
    if status:
        assert result["status"] == status, result
    return result


def test_count():
    check_query("SELECT (COUNT(DISTINCT ?g) AS ?n) WHERE { " + PATTERN + " }", True)

def test_count_star():
    check_query("SELECT (COUNT(*) AS ?n) WHERE { " + PATTERN + " }", True)

def test_full_iris_and_comments():
    check_query("SELECT # comment\n (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?d "
                     "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
                     "<https://biomedit.ch/rdf/sphn-schema/sphn#BilledDiagnosis> } }", True)

def test_demo_prefix_filter():
    from sparql_analyzer.demo import EXAMPLE_QUERY
    assert validate(EXAMPLE_QUERY)["is_compliant"]

def test_alias_chain_exposes_graph():
    check_query("SELECT ?b WHERE { " + PATTERN +
                     " BIND(STR(?g) AS ?a) BIND(?a AS ?b) }", rule="R5")

def test_count_does_not_sanitize_group_concat():
    check_query("SELECT (COUNT(*) AS ?n) (GROUP_CONCAT(STR(?g)) AS ?ids) WHERE { "
                     + PATTERN + " }", rule="R5")

def test_filter_patient_alias():
    check_query('SELECT (COUNT(*) AS ?n) WHERE { ' + PATTERN +
                     ' BIND(STR(?g) AS ?alias) FILTER(?alias = "http://example.org/graph/p42") }', rule="R1")

def test_identifier_constant():
    check_query('SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?p sphn:hasIdentifier "0042" } }', rule="R1")

def test_graph_bound_to_constant():
    check_query('SELECT (COUNT(*) AS ?n) WHERE { BIND(<urn:patient42> AS ?g) '
                     + PATTERN + ' }', rule="R1")

def test_identifier_filter():
    check_query('SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?p sphn:hasIdentifier ?id } FILTER(?id="0042") }', rule="R1")

def test_unrestricted_branch():
    check_query("SELECT (COUNT(*) AS ?n) WHERE { { " + PATTERN +
                     " } UNION { GRAPH ?g { ?s ?p ?o } } }", rule="R3")

def test_service_blocked():
    check_query("SELECT (COUNT(*) AS ?n) WHERE { SERVICE <http://example.invalid/sparql> { "
                     + PATTERN + " } }", status="non_compliant")

def test_subquery_approved():
    check_query("SELECT (COUNT(*) AS ?n) WHERE { { SELECT ?g WHERE { "
                     + PATTERN + " } } }", compliant=True)

def test_average_of_authorized_measure_approved():
    check_query("SELECT (AVG(?v) AS ?n) WHERE { GRAPH ?g { ?d sphn:hasValue ?v } }", compliant=True)

def test_update():
    check_query("DELETE WHERE { " + PATTERN + " }", rule="R4")

def test_ask():
    check_query("ASK WHERE { " + PATTERN + " }", rule="R4")

def test_invalid_syntax():
    result = check_query("SELECT WHERE {", status="unsupported")
    assert result["findings"][0]["code"] == "SYNTAX"

def test_virtuoso_extension_blocked():
    check_query('DEFINE sql:select-option "order" SELECT (COUNT(*) AS ?n) WHERE { '
                     + PATTERN + ' }', status="unsupported")

def test_deterministic():
    query = PREFIX + "SELECT ?g WHERE { " + PATTERN + " }"
    assert validate(query) == validate(query)


CASES_DIR = Path(__file__).resolve().parent / "cases"
CASES = json.loads((CASES_DIR / "cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[case["file"] for case in CASES])
def test_compliance_case(case):
    query = (CASES_DIR / case["file"]).read_text(encoding="utf-8")
    result = validate(query)
    assert result["is_compliant"] == case["expected_compliant"], result
    assert set(case["expected_violations"]) <= set(result["violations"]), result
