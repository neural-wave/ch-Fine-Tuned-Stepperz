"""Protezione dei bypass noti, toggle e prerequisiti fidati del profilo hardened."""

from dataclasses import replace

import pytest
from rdflib import Literal, RDF, URIRef

from sparql_analyzer import DEFAULT_POLICY, ExecutionContext, Policy, ReleaseHistory
from sparql_analyzer.compliance import validate
from sparql_analyzer.runtime import ResultBlocked, execute_checked
from tests.complex_attacks import CASES, prepare
from tests.complex_fixture import complex_cohort
from tests.generate_synthetic_data import SPHN, SYN
from tests.privacy_fixture import trusted_context

# Fixture minimali per attaccare la privacy, non dati clinici conformi SPHN.
STRICT = Policy.hardened().with_checks(privacy_normalize_errors=False, adequacy_shacl=False)
PREFIX = "PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>\n"
COUNT = PREFIX + "SELECT (COUNT(DISTINCT ?g) AS ?n) WHERE { GRAPH ?g { ?dx a sphn:BilledDiagnosis } }"
MEAN = PREFIX + """SELECT (AVG(?perPatient) AS ?n) WHERE {
  { SELECT (AVG(?v) AS ?perPatient) WHERE { GRAPH ?g {
      ?lab a sphn:LabTestEvent ; sphn:hasQuantity ?quantity .
      ?quantity sphn:hasValue ?v
  } } GROUP BY ?g }
}"""


@pytest.mark.parametrize("case", [pytest.param(c, id=c["id"]) for c in CASES if c["expected"] == "released"])
def test_hardened_profile_keeps_complex_positive_controls(case):
    dataset, query = prepare(case)
    payload = execute_checked(dataset, query, policy=STRICT, context=trusted_context(dataset))
    assert payload["results"]["bindings"][0]["summary"]["value"] == case["expected_value"]


def test_hardened_profile_keeps_individual_intermediate_groups():
    dataset = complex_cohort()
    assert execute_checked(dataset, MEAN, policy=STRICT, context=trusted_context(dataset))


def test_effective_contributor_policy_is_independently_switchable():
    dataset, query = prepare(CASES[0])
    policy = DEFAULT_POLICY.with_checks(privacy_effective_contributors=True)
    with pytest.raises(ResultBlocked, match="Coorte"):
        execute_checked(dataset, query, policy=policy)
    assert execute_checked(dataset, query, policy=policy.with_checks(privacy_effective_contributors=False))


@pytest.mark.parametrize("expression", ["IF(?v > 1006, ?v, 0)", "COALESCE(?rareValue, 0)"])
def test_alias_inside_graph_cannot_hide_padding(expression):
    dataset = complex_cohort()
    query = PREFIX + f"""SELECT (SUM(?masked) AS ?n) WHERE {{ GRAPH ?g {{
      ?lab a sphn:LabTestEvent ; sphn:hasQuantity ?quantity .
      ?quantity sphn:hasValue ?v .
      OPTIONAL {{ ?rare a sphn:OncologyDiagnosis ; sphn:hasValue ?rareValue }}
      BIND({expression} AS ?masked)
    }} }}"""
    with pytest.raises(ResultBlocked, match="Coorte"):
        execute_checked(dataset, query, policy=STRICT, context=trusted_context(dataset))


def test_real_zero_measurements_still_contribute():
    dataset = complex_cohort()
    for graph in dataset.contexts():
        for subject in list(graph.subjects(SPHN.hasValue, None)):
            graph.set((subject, SPHN.hasValue, Literal(0)))
    query = PREFIX + "SELECT (SUM(?v) AS ?n) WHERE { GRAPH ?g { ?q sphn:hasValue ?v } }"
    payload = execute_checked(dataset, query, policy=STRICT, context=trusted_context(dataset))
    assert payload["results"]["bindings"][0]["n"]["value"] == "0"


def test_correlated_patterns_toggle_is_visible_in_static_findings():
    query = PREFIX + "SELECT (COUNT(*) AS ?n) WHERE { ?q a sphn:OncologyDiagnosis . GRAPH ?g { ?dx a sphn:BilledDiagnosis } }"
    policy = DEFAULT_POLICY.with_checks(privacy_correlated_patterns=True)
    assert "privacy_correlated_patterns" in {f["check"] for f in validate(query, policy=policy)["findings"]}
    assert validate(query, policy=policy.with_checks(privacy_correlated_patterns=False))["is_compliant"]


def test_person_identity_toggle_changes_duplicate_graph_result():
    case = next(c for c in CASES if c["recipe"] == "duplicate_person")
    dataset, query = prepare(case)
    context = trusted_context(dataset)
    policy = DEFAULT_POLICY.with_checks(privacy_distinct_persons=True)
    with pytest.raises(ResultBlocked, match="Coorte"):
        execute_checked(dataset, query, policy=policy, context=context)
    assert execute_checked(dataset, query, policy=policy.with_checks(privacy_distinct_persons=False), context=context)


def test_authorization_checks_dataset_before_backend_query(monkeypatch):
    dataset = complex_cohort()
    context = replace(trusted_context(dataset), allowed_graphs=frozenset())
    policy = DEFAULT_POLICY.with_checks(privacy_authorization=True)
    def forbidden(*args, **kwargs):
        pytest.fail("Il backend non deve vedere un dataset non autorizzato")
    monkeypatch.setattr(dataset, "query", forbidden)
    with pytest.raises(ResultBlocked, match="autorizzato"):
        execute_checked(dataset, COUNT, policy=policy, context=context)


@pytest.mark.parametrize("flag", ["privacy_authorization", "privacy_distinct_persons", "privacy_query_history", "privacy_temporal_history"])
def test_context_dependent_policy_fails_closed_when_context_missing(flag):
    with pytest.raises(ResultBlocked, match="ExecutionContext"):
        execute_checked(complex_cohort(), COUNT, policy=DEFAULT_POLICY.with_checks(**{flag: True}))


def test_missing_person_mapping_does_not_fall_back_to_graph_count():
    dataset = complex_cohort()
    context = replace(trusted_context(dataset), graph_patients={})
    with pytest.raises(ResultBlocked, match="mapping"):
        execute_checked(dataset, COUNT, policy=STRICT, context=context)
    mapping = dict(trusted_context(dataset).graph_patients)
    mapping.pop(next(iter(mapping)))
    with pytest.raises(ResultBlocked, match="identita canonica"):
        execute_checked(dataset, COUNT, policy=STRICT, context=replace(context, graph_patients=mapping))


def test_missing_history_does_not_silently_disable_protection():
    dataset = complex_cohort()
    with pytest.raises(ResultBlocked, match="storico"):
        execute_checked(dataset, COUNT, policy=STRICT, context=replace(trusted_context(dataset), history=None))


def test_repeated_identical_query_is_allowed_and_not_counted_twice():
    dataset = complex_cohort()
    context = trusted_context(dataset)
    first = execute_checked(dataset, COUNT, policy=STRICT, context=context)
    assert execute_checked(dataset, COUNT, policy=STRICT, context=context) == first


def test_different_statistics_on_same_cohort_are_suppressed():
    dataset = complex_cohort()
    context = trusted_context(dataset)
    execute_checked(dataset, COUNT, policy=STRICT, context=context)
    with pytest.raises(ResultBlocked, match="Storico"):
        execute_checked(dataset, MEAN, policy=STRICT, context=context)
    assert execute_checked(dataset, MEAN, policy=STRICT.with_checks(privacy_query_history=False), context=context)


def test_history_is_shared_across_principals():
    dataset = complex_cohort()
    context = trusted_context(dataset)
    execute_checked(dataset, COUNT, policy=STRICT, context=context)
    with pytest.raises(ResultBlocked, match="Storico"):
        execute_checked(dataset, MEAN, policy=STRICT, context=replace(context, principal_id="second-user"))


def test_history_checks_small_complements_and_keeps_old_record_after_rejection():
    dataset = complex_cohort()
    context = trusted_context(dataset)
    query = PREFIX + """SELECT (COUNT(DISTINCT ?g) AS ?n) WHERE { GRAPH ?g {
      ?lab a sphn:LabTestEvent ; sphn:hasQuantity ?q .
      ?q sphn:hasValue ?v . FILTER(?v > 1000)
    } }"""
    execute_checked(dataset, COUNT, policy=STRICT, context=context)
    with pytest.raises(ResultBlocked, match="Storico"):
        execute_checked(dataset, query, policy=STRICT, context=context)
    assert execute_checked(dataset, COUNT, policy=STRICT, context=context)
    assert execute_checked(dataset, query, policy=STRICT.with_checks(privacy_query_history=False), context=context)


def test_temporal_guard_is_independently_switchable():
    dataset = complex_cohort()
    policy = DEFAULT_POLICY.with_checks(privacy_temporal_history=True)
    context = trusted_context(dataset)
    execute_checked(dataset, COUNT, policy=policy, context=context)
    graph = dataset.graph(URIRef("http://example.org/graph/complex-0"))
    graph.remove((None, RDF.type, SPHN.BilledDiagnosis))
    with pytest.raises(ResultBlocked, match="Snapshot"):
        execute_checked(dataset, COUNT, policy=policy, context=context)
    assert execute_checked(dataset, COUNT, policy=policy.with_checks(privacy_temporal_history=False), context=context)


def test_history_capacity_fails_closed_without_evicting_old_records():
    history = ReleaseHistory(max_records=1)
    history.record(dataset_id="test", fingerprint="snapshot", query="first", cohorts=[set(range(5))], min_patients=5, check_queries=True, check_temporal=True)
    with pytest.raises(ResultBlocked, match="Capacita"):
        history.record(dataset_id="test", fingerprint="snapshot", query="second", cohorts=[set(range(5, 10))], min_patients=5, check_queries=True, check_temporal=True)
    history.record(dataset_id="test", fingerprint="snapshot", query="first", cohorts=[set(range(5))], min_patients=5, check_queries=True, check_temporal=True)


def test_multi_query_partition_refinement_is_not_only_pairwise():
    history = ReleaseHistory()
    def release(name, cohort):
        history.record(dataset_id="test", fingerprint="snapshot", query=name, cohorts=[set(cohort)], min_patients=2, check_queries=True, check_temporal=True)
    release("one", range(8))
    release("two", [0, 1, 2, 3])
    with pytest.raises(ResultBlocked, match="intersezione"):
        release("three", [0, 4, 5, 6])


def test_backend_error_normalization_is_independently_switchable(monkeypatch):
    dataset = complex_cohort()
    def failing(*args, **kwargs):
        raise RuntimeError("private-patient@example.invalid")
    monkeypatch.setattr(dataset, "query", failing)
    policy = DEFAULT_POLICY.with_checks(privacy_normalize_errors=True)
    with pytest.raises(ResultBlocked) as error:
        execute_checked(dataset, COUNT, policy=policy)
    assert "private-patient" not in str(error.value)
    assert error.value.__suppress_context__
    with pytest.raises(RuntimeError):
        execute_checked(dataset, COUNT, policy=policy.with_checks(privacy_normalize_errors=False))


def test_dataset_mutation_during_execution_is_suppressed_without_committing_history(monkeypatch):
    dataset = complex_cohort()
    context = trusted_context(dataset)
    policy = DEFAULT_POLICY.with_checks(privacy_temporal_history=True, result_consistency=False)
    original, calls = dataset.query, 0
    def mutate(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 2:
            dataset.graph(URIRef("http://example.org/graph/complex-0")).remove((None, RDF.type, SPHN.BilledDiagnosis))
        return result
    monkeypatch.setattr(dataset, "query", mutate)
    with pytest.raises(ResultBlocked, match="modificato"):
        execute_checked(dataset, COUNT, policy=policy, context=context)
    assert execute_checked(dataset, COUNT, policy=policy, context=context)


def test_context_copies_acl_and_identity_metadata():
    acl, mapping = {"urn:g"}, {"urn:g": "canonical-one"}
    context = ExecutionContext("user", "dataset", allowed_graphs=acl, graph_patients=mapping)
    acl.clear()
    mapping.clear()
    assert context.allowed_graphs == {"urn:g"}
    assert context.graph_patients["urn:g"] == "canonical-one"


def test_history_does_not_store_query_text():
    history = ReleaseHistory()
    history.record(dataset_id="test", fingerprint="snapshot", query="private-query-literal", cohorts=[set(range(5))],
                   min_patients=5, check_queries=True, check_temporal=True)
    assert "private-query-literal" not in repr(history._records)
