"""Divieti espliciti: operatori AST, non ricerca testuale di parole."""

import pytest

from sparql_analyzer.compliance import validate
from sparql_analyzer.runtime import ResultBlocked, execute_checked
from tests.generate_synthetic_data import generate

PREFIX = "PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>\n"
PATTERN = "GRAPH ?g { ?s a sphn:BilledDiagnosis . }"


def assert_forbidden(body, operator):
    verdict = validate(PREFIX + body)
    assert verdict["status"] == "non_compliant", verdict
    assert not verdict["is_compliant"]
    assert operator in verdict["forbidden_operators"], verdict
    assert any(f["code"] == "FORBIDDEN_OPERATOR" for f in verdict["findings"])
    assert not any(f["code"] == "SYNTAX" for f in verdict["findings"])


@pytest.mark.parametrize("operator", ["GROUP_CONCAT", "SAMPLE", "MIN", "MAX"])
@pytest.mark.parametrize("lowercase", [False, True], ids=["uppercase", "lowercase"])
def test_explicit_aggregates_forbidden(operator, lowercase):
    spelling = operator.lower() if lowercase else operator
    assert_forbidden(f"SELECT ({spelling}(STR(?s)) AS ?metric) WHERE {{ {PATTERN} }}", operator)


@pytest.mark.parametrize("body,operator", [
    (f"ASK WHERE {{ {PATTERN} }}", "ASK"),
    (f"CONSTRUCT {{ ?s a sphn:BilledDiagnosis }} WHERE {{ {PATTERN} }}", "CONSTRUCT"),
    (f"DESCRIBE ?s WHERE {{ {PATTERN} }}", "DESCRIBE"),
    (f"SELECT (COUNT(*) AS ?n) WHERE {{ SERVICE <https://example.invalid/sparql> {{ {PATTERN} }} }}", "SERVICE"),
    (f"SELECT (COUNT(*) AS ?n) WHERE {{ SERVICE SILENT <https://example.invalid/sparql> {{ {PATTERN} }} }}", "SERVICE"),
    (f"SELECT (COUNT(*) AS ?n) FROM <urn:synthetic:dataset> WHERE {{ {PATTERN} }}", "FROM"),
    (f"SELECT (COUNT(*) AS ?n) FROM NAMED <urn:synthetic:dataset> WHERE {{ {PATTERN} }}", "FROM NAMED"),
])
def test_query_forms_and_dataset_forbidden(body, operator):
    assert_forbidden(body, operator)


@pytest.mark.parametrize("body,operator", [
    ('INSERT DATA { <urn:synthetic:s> sphn:hasIdentifier "SYNTH" }', "INSERT"),
    ('DELETE DATA { <urn:synthetic:s> sphn:hasIdentifier "SYNTH" }', "DELETE"),
    (f"DELETE WHERE {{ {PATTERN} }}", "DELETE"),
    ('LOAD <https://example.invalid/data.ttl>', "LOAD"),
    ('CLEAR SILENT ALL', "CLEAR"),
    ('DROP SILENT GRAPH <urn:synthetic:g>', "DROP"),
    ('CREATE SILENT GRAPH <urn:synthetic:g>', "CREATE"),
    ('ADD GRAPH <urn:synthetic:a> TO GRAPH <urn:synthetic:b>', "ADD"),
    ('MOVE GRAPH <urn:synthetic:a> TO GRAPH <urn:synthetic:b>', "MOVE"),
    ('COPY GRAPH <urn:synthetic:a> TO GRAPH <urn:synthetic:b>', "COPY"),
])
def test_update_operations_forbidden(body, operator):
    assert_forbidden(body, operator)


def test_modify_reports_insert_and_delete():
    verdict = validate(PREFIX + f"DELETE {{ ?s a sphn:BilledDiagnosis }} INSERT {{ ?s a sphn:OncologyDiagnosis }} WHERE {{ {PATTERN} }}")
    assert {"INSERT", "DELETE", "SPARQL UPDATE"} <= set(verdict["forbidden_operators"])


def test_nested_forbidden_aggregate():
    assert_forbidden(f"SELECT (COUNT(*) AS ?n) WHERE {{ {{ SELECT (MAX(?s) AS ?x) WHERE {{ {PATTERN} }} }} }}", "MAX")


def test_aggregate_in_having_is_forbidden():
    assert_forbidden(f"SELECT (COUNT(*) AS ?n) WHERE {{ {PATTERN} }} HAVING(MIN(?s) = MAX(?s))", "MIN")


def test_aggregate_in_order_by_is_forbidden():
    assert_forbidden(f"SELECT (COUNT(*) AS ?n) WHERE {{ {PATTERN} }} ORDER BY MAX(?s)", "MAX")


@pytest.mark.parametrize("body", [
    f"# DELETE SERVICE GROUP_CONCAT SAMPLE MIN MAX\nSELECT (COUNT(*) AS ?n) WHERE {{ {PATTERN} }}",
    'SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s sphn:hasValue ?label } FILTER(?label = "SERVICE GROUP_CONCAT SAMPLE MIN MAX FROM DELETE") }',
    'SELECT (COUNT(*) AS ?MIN) WHERE { GRAPH ?SERVICE { ?DELETE a sphn:BilledDiagnosis } }',
    'SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s a <urn:synthetic:SERVICE> } }',
    "PREFIX SERVICE: <https://biomedit.ch/rdf/sphn-schema/sphn#> SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s a SERVICE:BilledDiagnosis } }",
])
def test_keyword_as_data_is_not_an_operator(body):
    verdict = validate(PREFIX + body)
    assert verdict["is_compliant"], verdict
    assert verdict["forbidden_operators"] == []


@pytest.mark.parametrize("body", [
    f"SELECT (COUNT(DISTINCT ?g) AS ?n) WHERE {{ {PATTERN} OPTIONAL {{ GRAPH ?g {{ ?lab a sphn:LabTestEvent }} }} }}",
    f"SELECT (COUNT(DISTINCT ?g) AS ?n) WHERE {{ {{ {PATTERN} }} UNION {{ GRAPH ?g {{ ?lab a sphn:LabTestEvent }} }} }}",
    f"SELECT (COUNT(DISTINCT ?g) AS ?n) WHERE {{ {PATTERN} BIND(STR(?g) AS ?alias) }}",
])
def test_union_optional_bind_remain_available(body):
    assert validate(PREFIX + body)["is_compliant"]


def test_generated_sample_is_not_an_explicit_sample():
    verdict = validate(PREFIX + "SELECT ?class (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s a ?class } } GROUP BY ?class")
    assert "SAMPLE" not in verdict["forbidden_operators"]
    # GROUP BY resta non supportato: questo test non ne autorizza l'esecuzione.
    assert not verdict["is_compliant"]


def test_forbidden_operator_never_reaches_backend(monkeypatch):
    dataset = generate()

    def forbidden(*args, **kwargs):
        pytest.fail("SERVICE non deve raggiungere il backend")

    monkeypatch.setattr(dataset, "query", forbidden)
    body = f"SELECT (COUNT(*) AS ?n) WHERE {{ SERVICE SILENT <https://example.invalid/sparql> {{ {PATTERN} }} }}"
    with pytest.raises(ResultBlocked, match="statico"):
        execute_checked(dataset, PREFIX + body)
