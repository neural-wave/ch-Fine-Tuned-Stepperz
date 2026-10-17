"""Statistiche ammesse, provenienza delle misure e coorte per operando."""

import json
from decimal import Decimal
from types import SimpleNamespace
from pathlib import Path

import pytest
from rdflib import Dataset, Literal, RDF, URIRef, XSD

from sparql_analyzer.compliance import validate
from sparql_analyzer.runtime import ResultBlocked, execute_checked
from tests.generate_synthetic_data import SPHN, SYN

PREFIX = f"PREFIX sphn: <{SPHN}>\n"
PATTERN = "GRAPH ?g { ?quantity sphn:hasValue ?v . }"


def statistics(expression, pattern=PATTERN, suffix=""):
    return PREFIX + f"SELECT ({expression} AS ?result) WHERE {{ {pattern} }} {suffix}"


@pytest.fixture
def measurements():
    dataset = Dataset()
    for i in range(8):
        graph = dataset.graph(URIRef(f"http://example.org/graph/measurement-{i}"))
        graph.add((SYN[f"quantity-{i}"], SPHN.hasValue, Literal(10 + i)))
    return dataset


def result_value(dataset, query):
    result = execute_checked(dataset, query)
    return Decimal(result["results"]["bindings"][0]["result"]["value"])


@pytest.mark.parametrize("expression,expected", [
    ("COUNT(?v)", "8"), ("SUM(?v)", "108"), ("AVG(?v)", "13.5"),
    ("SUM(DISTINCT ?v)", "108"), ("AVG(DISTINCT ?v)", "13.5"),
    ("ROUND(AVG(?v))", "14"), ("CEIL(AVG(?v))", "14"),
    ("FLOOR(AVG(?v))", "13"), ("ABS(-SUM(?v))", "108"),
    ("(SUM(?v) / COUNT(?v))", "13.5"), ("(AVG(?v) * 100)", "1350"),
    ("(SUM(?v) - COUNT(?v))", "100"), ("AVG(?v + 1)", "14.5"),
    ("SUM(?v * 2)", "216"), ("AVG(ABS(?v))", "13.5"),
    ("SUM(-?v)", "-108"),
    ("IF(SUM(?v) > 100, AVG(?v), 0)", "13.5"),
    ("SUM(IF(?v > 13, 1, 0))", "4"),
    ("COALESCE(AVG(?v), 0)", "13.5"),
])
def test_approved_numeric_operations(measurements, expression, expected):
    query = statistics(expression)
    assert validate(query)["is_compliant"]
    assert result_value(measurements, query) == Decimal(expected)


@pytest.mark.parametrize("file,expected", [("average", "13.5"), ("sum", "108"),
                                           ("ratio", "13.5"), ("rounded_average", "14")])
def test_numeric_query_files(measurements, file, expected):
    query = (Path(__file__).parent / "numeric/queries" / (file + ".rq")).read_text(encoding="utf-8")
    assert result_value(measurements, query) == Decimal(expected)


def test_arithmetic_bind_measure(measurements):
    query = statistics("AVG(?adjusted)", PATTERN + " BIND((?v + 1) AS ?adjusted)")
    assert result_value(measurements, query) == Decimal("14.5")


def test_having_order_limit(measurements):
    query = statistics("AVG(?v)", suffix="HAVING(COUNT(DISTINCT ?g) >= 5) ORDER BY DESC(?result) LIMIT 1")
    assert result_value(measurements, query) == Decimal("13.5")


def test_distinct_keeps_all_contributing_patients(measurements):
    for graph in measurements.contexts():
        for quantity in list(graph.subjects(SPHN.hasValue, None)):
            graph.set((quantity, SPHN.hasValue, Literal(12)))
    assert result_value(measurements, statistics("AVG(DISTINCT ?v)")) == 12


@pytest.mark.parametrize("aggregate", ["SUM", "AVG"])
def test_numeric_identifiers_not_measures(measurements, aggregate):
    query = PREFIX + f"SELECT ({aggregate}(?id) AS ?result) WHERE {{ GRAPH ?g {{ ?person sphn:hasIdentifier ?id }} }}"
    for i in range(8):
        measurements.graph(URIRef(f"http://example.org/graph/measurement-{i}")).add((SYN[f"person-{i}"], SPHN.hasIdentifier, Literal(1000 + i)))
    assert not validate(query)["is_compliant"]
    with pytest.raises(ResultBlocked, match="statico"):
        execute_checked(measurements, query)


def test_unknown_numeric_predicate_blocked():
    assert not validate(statistics("AVG(?v)", "GRAPH ?g { ?s sphn:hasUnknownValue ?v }"))["is_compliant"]


@pytest.mark.parametrize("value", [Literal("SYNTH-0000"), URIRef("urn:synthetic:identifier"),
                                    Literal("NaN", datatype=XSD.double), Literal("INF", datatype=XSD.double)])
def test_invalid_measure_not_released(measurements, value):
    measurements.graph(URIRef("http://example.org/graph/measurement-0")).set((SYN["quantity-0"], SPHN.hasValue, value))
    with pytest.raises(ResultBlocked):
        execute_checked(measurements, statistics("AVG(?v)"))


def test_rare_optional_average_blocked(measurements):
    pattern = """GRAPH ?g {
      ?quantity sphn:hasValue ?v .
      OPTIONAL { ?rare a sphn:OncologyDiagnosis ; sphn:hasValue ?rare_value . }
    }"""
    measurements.graph(URIRef("http://example.org/graph/measurement-0")).add((SYN.rare, RDF.type, SPHN.OncologyDiagnosis))
    measurements.graph(URIRef("http://example.org/graph/measurement-0")).add((SYN.rare, SPHN.hasValue, Literal(42)))
    query = PREFIX + f"SELECT (COUNT(DISTINCT ?g) AS ?patients) (AVG(?rare_value) AS ?mean) WHERE {{ {pattern} }}"
    with pytest.raises(ResultBlocked, match="Coorte insufficiente"):
        execute_checked(measurements, query)


def test_hidden_having_aggregate_checked(measurements):
    pattern = PATTERN + " OPTIONAL { GRAPH ?g { ?rare a sphn:OncologyDiagnosis ; sphn:hasValue ?rare_value } }"
    graph = measurements.graph(URIRef("http://example.org/graph/measurement-0"))
    graph.add((SYN.rare, RDF.type, SPHN.OncologyDiagnosis))
    graph.add((SYN.rare, SPHN.hasValue, Literal(42)))
    query = statistics("AVG(?v)", pattern, "HAVING(COUNT(?rare_value) > 0)")
    with pytest.raises(ResultBlocked, match="Coorte insufficiente"):
        execute_checked(measurements, query)


@pytest.mark.parametrize("expression", ["AVG(?v)", "SUM(?v)", "ROUND(AVG(?v))"])
def test_fewer_than_k_actual_contributors(measurements, expression):
    for i in range(4):
        measurements.graph(URIRef(f"http://example.org/graph/measurement-{i}")).remove((None, SPHN.hasValue, None))
    with pytest.raises(ResultBlocked, match="Coorte insufficiente"):
        execute_checked(measurements, statistics(expression))


@pytest.mark.parametrize("replacement", [
    {"type": "literal", "datatype": str(XSD.decimal), "value": "999.5"},
    {"type": "literal", "datatype": str(XSD.integer), "value": "13.5"},
    {"type": "literal", "datatype": str(XSD.string), "value": "13.5"},
    {"type": "literal", "datatype": str(XSD.double), "value": "NaN"},
])
def test_numeric_payload_tampering(measurements, monkeypatch, replacement):
    original = measurements.query
    calls = 0
    def tampered(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 2:
            payload = json.loads(result.serialize(format="json"))
            payload["results"]["bindings"][0]["result"] = replacement
            return SimpleNamespace(serialize=lambda **kwargs: json.dumps(payload))
        return result
    monkeypatch.setattr(measurements, "query", tampered)
    with pytest.raises(ResultBlocked):
        execute_checked(measurements, statistics("AVG(?v)"))


def test_division_by_zero_blocked(measurements):
    with pytest.raises(ResultBlocked):
        execute_checked(measurements, statistics("(SUM(?v) / (COUNT(?v) - COUNT(?v)))"))


@pytest.mark.parametrize("condition", ["isNumeric(?v)", "?v >= 10 && ?v < 30", "ABS(?v) > 0", "ROUND(?v) >= 10"])
def test_numeric_filters_supported(measurements, condition):
    assert result_value(measurements, statistics("AVG(?v)", PATTERN + f" FILTER({condition})")) == Decimal("13.5")


@pytest.mark.parametrize("condition", [
    'CONTAINS(LCASE(?label), "mg")',
    'STRSTARTS(UCASE(?label), "MG")',
    'STRENDS(?label, "L")',
    'STRLEN(?label) > 1',
    'REGEX(?label, "^mg")',
])
def test_string_filters_do_not_expose_labels(measurements, condition):
    for graph in measurements.contexts():
        for quantity in list(graph.subjects(SPHN.hasValue, None)):
            graph.add((quantity, SPHN.hasCode, Literal("mg/L")))
    pattern = "GRAPH ?g { ?quantity sphn:hasValue ?v ; sphn:hasCode ?label . }"
    assert result_value(measurements, statistics("AVG(?v)", pattern + f" FILTER({condition})")) == Decimal("13.5")


@pytest.mark.parametrize("condition", ['YEAR(?date) = 2026', 'MONTH(?date) = 10', 'DAY(?date) = 17'])
def test_date_filters_supported(measurements, condition):
    for graph in measurements.contexts():
        for quantity in list(graph.subjects(SPHN.hasValue, None)):
            graph.add((quantity, SPHN.hasDateTime, Literal("2026-10-17T12:30:00", datatype=XSD.dateTime)))
    pattern = "GRAPH ?g { ?quantity sphn:hasValue ?v ; sphn:hasDateTime ?date . }"
    assert result_value(measurements, statistics("AVG(?v)", pattern + f" FILTER({condition})")) == Decimal("13.5")
