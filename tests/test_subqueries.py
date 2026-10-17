"""Sottoquery reali: semantica RDFLib, scope e controllo dell'output finale."""

import json

import pytest
from rdflib import Variable

from sparql_analyzer.compliance import validate
from sparql_analyzer.parser import analyze
from sparql_analyzer.runtime import ResultBlocked, execute_checked
from sparql_analyzer.runtime import nodes
from tests.complex_fixture import complex_cohort

PREFIX = "PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>\n"


@pytest.mark.parametrize("inner", [
    "SELECT ?g ?v WHERE { GRAPH ?g { ?q sphn:hasValue ?v } }",
    "SELECT DISTINCT ?g ?v WHERE { GRAPH ?g { ?q sphn:hasValue ?v } }",
    "SELECT ?g ?v WHERE { { SELECT ?g ?v WHERE { GRAPH ?g { ?q sphn:hasValue ?v } } } }",
    "SELECT ?g (?raw AS ?v) WHERE { GRAPH ?g { ?q sphn:hasValue ?raw } }",
    "SELECT ?g ?v WHERE { GRAPH ?g { ?q sphn:hasValue ?v } } ORDER BY ?v LIMIT 100",
])
def test_individual_intermediates_are_allowed(inner):
    query = PREFIX + "SELECT (AVG(?v) AS ?summary) WHERE { { " + inner + " } }"
    dataset = complex_cohort()
    assert validate(query)["is_compliant"]
    actual = execute_checked(dataset, query)
    original = json.loads(dataset.query(query).serialize(format="json"))
    assert actual == original


def test_private_local_name_does_not_taint_outer_measure():
    query = PREFIX + """SELECT (AVG(?v) AS ?summary) WHERE {
      { SELECT DISTINCT ?g WHERE {
          GRAPH ?g { ?person sphn:hasIdentifier ?v }
      } }
      GRAPH ?g { ?q sphn:hasValue ?v }
    }"""
    assert validate(query)["is_compliant"]
    assert execute_checked(complex_cohort(), query)


def test_numeric_local_name_does_not_sanitize_exported_identifier():
    query = PREFIX + """SELECT (AVG(?v) AS ?summary) WHERE {
      { SELECT DISTINCT ?g WHERE { GRAPH ?g { ?q sphn:hasValue ?v } } }
      GRAPH ?g { ?person sphn:hasIdentifier ?v }
    }"""
    assert not validate(query)["is_compliant"]


@pytest.mark.parametrize("projection", ["?id", "(?id AS ?export)"])
def test_identifier_export_is_blocked(projection):
    query = PREFIX + "SELECT * WHERE { { SELECT " + projection + """ WHERE {
        GRAPH ?g { ?person sphn:hasIdentifier ?id }
    } } }"""
    with pytest.raises(ResultBlocked, match="statico"):
        execute_checked(complex_cohort(), query)


def test_small_cohort_inside_subquery_is_suppressed():
    query = PREFIX + """SELECT (AVG(?v) AS ?summary) WHERE {
      { SELECT ?g ?v WHERE { GRAPH ?g {
          ?q a sphn:OncologyDiagnosis ; sphn:hasValue ?v
      } } }
    }"""
    assert validate(query)["is_compliant"]
    with pytest.raises(ResultBlocked, match="Coorte insufficiente"):
        execute_checked(complex_cohort(), query)


def test_hidden_patient_graph_is_not_replaced_by_unrelated_outer_graph():
    query = PREFIX + """SELECT (AVG(?v) AS ?summary) WHERE {
      { SELECT ?v WHERE { GRAPH ?private { ?q sphn:hasValue ?v } } }
      GRAPH ?g { ?dx a sphn:BilledDiagnosis }
    }"""
    with pytest.raises(ResultBlocked):
        execute_checked(complex_cohort(), query)


def test_scope_names_do_not_collide_with_user_variables():
    query = PREFIX + """SELECT (COUNT(?g) AS ?n) WHERE {
      { SELECT ?g WHERE { GRAPH ?g { ?__scope_1 a sphn:BilledDiagnosis } } }
    }"""
    _, _, prepared = analyze(query)
    subjects = [t[0] for node in nodes(prepared.algebra) if node.name == "BGP"
                for t in node["triples"]]
    assert Variable("__scope_1") not in subjects
    assert Variable("__scope_2") in subjects
    assert execute_checked(complex_cohort(), query)
