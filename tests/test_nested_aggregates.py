"""Calcoli individuali intermedi, aggregazione finale e provenienza."""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from rdflib import Literal, URIRef

from sparql_analyzer.compliance import validate
from sparql_analyzer.runtime import ResultBlocked, execute_checked
from tests.complex_fixture import complex_cohort
from tests.generate_synthetic_data import SPHN, SYN

PREFIX = "PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>\n"
PATTERN = "GRAPH ?g { ?q sphn:hasValue ?v }"


def checked(body, dataset=None):
    dataset = dataset if dataset is not None else complex_cohort()
    query = PREFIX + body
    verdict = validate(query)
    assert verdict["is_compliant"], verdict
    actual = execute_checked(dataset, query)
    expected = json.loads(dataset.query(query).serialize(format="json"))
    assert actual == expected
    return actual


@pytest.mark.parametrize("inner,outer", [
    ("AVG(?v)", "AVG(?perPatient)"),
    ("SUM(?v)", "SUM(?perPatient)"),
    ("COUNT(?v)", "AVG(?perPatient)"),
    ("AVG(?v)", "COUNT(?perPatient)"),
    ("AVG(?v)", "AVG(?perPatient * 2)"),
    ("AVG(?v)", "AVG(DISTINCT ?perPatient)"),
])
def test_aggregate_over_individual_groups(inner, outer):
    checked(f"""SELECT ({outer} AS ?summary) WHERE {{
      {{ SELECT ?g ({inner} AS ?perPatient) WHERE {{ {PATTERN} }} GROUP BY ?g }}
    }}""")


def test_graph_key_can_remain_private():
    checked(f"""SELECT (AVG(?perPatient) AS ?summary) WHERE {{
      {{ SELECT (AVG(?v) AS ?perPatient) WHERE {{ {PATTERN} }} GROUP BY ?g }}
    }}""")


def test_three_levels_and_private_group_key():
    checked(f"""SELECT (AVG(?second) AS ?summary) WHERE {{
      {{ SELECT (SUM(?first) AS ?second) WHERE {{
        {{ SELECT (AVG(?v) AS ?first) WHERE {{ {PATTERN} }} GROUP BY ?g }}
      }} }}
    }}""")


def test_global_inner_aggregate_can_be_projected():
    checked(f"""SELECT ?summary WHERE {{
      {{ SELECT (AVG(?v) AS ?summary) WHERE {{ {PATTERN} }} }}
    }}""")


def test_patient_weights_are_equal():
    dataset = complex_cohort()
    # Il primo paziente ha una misura extra; AVG(AVG(...)) deve mantenere
    # il peso dei pazienti, senza appiattire i due livelli di aggregazione.
    dataset.graph(URIRef("http://example.org/graph/complex-0")).add(
        (SYN.extra, SPHN.hasValue, Literal(50000)))
    result = checked("""SELECT (AVG(?perPatient) AS ?summary) WHERE {
      { SELECT (AVG(?v) AS ?perPatient) WHERE {
          GRAPH ?g { ?q sphn:hasValue ?v . FILTER(?v >= 1000) }
      } GROUP BY ?g }
    }""", dataset)
    assert Decimal(result["results"]["bindings"][0]["summary"]["value"]) == Decimal("3180.25")


def test_individual_group_output_is_still_blocked():
    query = PREFIX + f"""SELECT ?g ?perPatient WHERE {{
      {{ SELECT ?g (AVG(?v) AS ?perPatient) WHERE {{ {PATTERN} }} GROUP BY ?g }}
    }}"""
    with pytest.raises(ResultBlocked):
        execute_checked(complex_cohort(), query)


def test_single_patient_cannot_be_broadcast_over_large_cohort():
    query = PREFIX + """SELECT (AVG(?secret) AS ?summary) WHERE {
      { SELECT (AVG(?v) AS ?secret) WHERE {
          GRAPH ?private { ?q a sphn:OncologyDiagnosis ; sphn:hasValue ?v }
      } }
      GRAPH ?g { ?dx a sphn:BilledDiagnosis }
    }"""
    assert validate(query)["is_compliant"]
    with pytest.raises(ResultBlocked, match="Coorte insufficiente"):
        execute_checked(complex_cohort(), query)


def test_repeated_scalar_does_not_inflate_count_cohort():
    query = PREFIX + """SELECT (COUNT(?secret) AS ?summary) WHERE {
      { SELECT (AVG(?v) AS ?secret) WHERE {
          GRAPH ?private { ?q a sphn:OncologyDiagnosis ; sphn:hasValue ?v }
      } }
      GRAPH ?g { ?dx a sphn:BilledDiagnosis }
    }"""
    with pytest.raises(ResultBlocked, match="Coorte insufficiente"):
        execute_checked(complex_cohort(), query)


def test_filter_on_small_private_aggregate_is_not_sanitized_by_count_star():
    query = PREFIX + """SELECT (COUNT(*) AS ?summary) WHERE {
      { SELECT (AVG(?v) AS ?secret) WHERE {
          GRAPH ?private { ?q a sphn:OncologyDiagnosis ; sphn:hasValue ?v }
      } }
      GRAPH ?g { ?dx a sphn:BilledDiagnosis }
      FILTER(?secret > 0)
    }"""
    with pytest.raises(ResultBlocked, match="Coorte insufficiente"):
        execute_checked(complex_cohort(), query)


def test_private_aggregate_not_reaching_output_or_control_is_allowed():
    checked("""SELECT (COUNT(DISTINCT ?g) AS ?summary) WHERE {
      { SELECT (AVG(?v) AS ?unused) WHERE {
          GRAPH ?private { ?q a sphn:OncologyDiagnosis ; sphn:hasValue ?v }
      } }
      GRAPH ?g { ?dx a sphn:BilledDiagnosis }
    }""")


@pytest.mark.parametrize("tail", [
    "HAVING(AVG(?v) >= 0)",
    "ORDER BY ?perPatient",
    "ORDER BY DESC(?perPatient) LIMIT 8",
])
def test_inner_having_order_and_limit_keep_semantics(tail):
    checked(f"""SELECT (AVG(?perPatient) AS ?summary) WHERE {{
      {{ SELECT (AVG(?v) AS ?perPatient) WHERE {{ {PATTERN} }} GROUP BY ?g {tail} }}
    }}""")


@pytest.mark.parametrize("pattern", [
    "GRAPH ?g { ?q sphn:hasValue ?v . OPTIONAL { ?q a sphn:Quantity } }",
    "{ GRAPH ?g { ?q sphn:hasValue ?v . FILTER(?v < 1000) } } UNION "
    "{ GRAPH ?g { ?q sphn:hasValue ?v . FILTER(?v >= 1000) } }",
    "GRAPH ?g { ?q sphn:hasValue ?v } MINUS { GRAPH ?g { ?q a sphn:MissingClass } }",
])
def test_inner_binary_operators_keep_semantics(pattern):
    checked(f"""SELECT (AVG(?perPatient) AS ?summary) WHERE {{
      {{ SELECT (AVG(?v) AS ?perPatient) WHERE {{ {pattern} }} GROUP BY ?g }}
    }}""")


def test_intermediate_row_limit_is_enforced():
    query = PREFIX + f"""SELECT (AVG(?perPatient) AS ?summary) WHERE {{
      {{ SELECT (AVG(?v) AS ?perPatient) WHERE {{ {PATTERN} }} GROUP BY ?g }}
    }}"""
    with pytest.raises(ResultBlocked, match="Limite"):
        execute_checked(complex_cohort(), query, max_support_rows=1)


def test_limit_cannot_release_one_patient_average():
    query = PREFIX + f"""SELECT (AVG(?perPatient) AS ?summary) WHERE {{
      {{ SELECT (AVG(?v) AS ?perPatient) WHERE {{ {PATTERN} }} GROUP BY ?g LIMIT 1 }}
    }}"""
    with pytest.raises(ResultBlocked, match="Coorte insufficiente"):
        execute_checked(complex_cohort(), query)


@pytest.mark.parametrize("condition", ["HAVING(AVG(?rare) > 0)", "ORDER BY AVG(?rare)"])
def test_unprojected_rare_aggregate_still_controls_release(condition):
    query = PREFIX + f"""SELECT (AVG(?perPatient) AS ?summary) WHERE {{
      {{ SELECT ?g (AVG(?v) AS ?perPatient) WHERE {{ {PATTERN} }} GROUP BY ?g }}
      OPTIONAL {{ GRAPH ?g {{ ?q a sphn:OncologyDiagnosis ; sphn:hasValue ?rare }} }}
    }} {condition}"""
    assert validate(query)["is_compliant"]
    with pytest.raises(ResultBlocked, match="Coorte insufficiente"):
        execute_checked(complex_cohort(), query)


def test_nested_result_tampering_is_blocked(monkeypatch):
    dataset = complex_cohort()
    query = PREFIX + f"""SELECT (AVG(?perPatient) AS ?summary) WHERE {{
      {{ SELECT (AVG(?v) AS ?perPatient) WHERE {{ {PATTERN} }} GROUP BY ?g }}
    }}"""
    original = dataset.query
    calls = 0

    def tampered(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 2:
            payload = json.loads(result.serialize(format="json"))
            payload["results"]["bindings"][0]["summary"]["value"] = "123456789"
            return SimpleNamespace(serialize=lambda **kwargs: json.dumps(payload))
        return result

    monkeypatch.setattr(dataset, "query", tampered)
    with pytest.raises(ResultBlocked, match="incoerente"):
        execute_checked(dataset, query)
