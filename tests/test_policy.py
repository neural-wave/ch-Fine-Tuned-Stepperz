"""Interruttori effettivi, dipendenze, isolamento e contratto predefinito."""

import json
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path

import pytest
from rdflib import URIRef, RDF

from sparql_analyzer import CHECKS, DEFAULT_POLICY, Policy
from sparql_analyzer.analysis import QueryAnalysis
from sparql_analyzer.compliance import validate
from sparql_analyzer.parser import analyze
from sparql_analyzer.results import ResultBlocked, check_payload, number
from sparql_analyzer.runtime import execute_checked
from tests.complex_fixture import complex_cohort
from tests.generate_synthetic_data import SPHN, generate

PREFIX = "PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>\n"
PATTERN = "GRAPH ?g { ?s a sphn:BilledDiagnosis }"
COUNT = PREFIX + f"SELECT (COUNT(DISTINCT ?g) AS ?n) WHERE {{ {PATTERN} }}"
NESTED = PREFIX + f"""SELECT (AVG(?n) AS ?summary) WHERE {{
  {{ SELECT (COUNT(?s) AS ?n) WHERE {{ {PATTERN} }} GROUP BY ?g }}
}}"""


@pytest.mark.parametrize("name", CHECKS)
def test_every_check_can_be_disabled_and_reenabled(name):
    disabled = DEFAULT_POLICY.with_checks(**{name: False})
    assert not disabled.enabled(name)
    assert DEFAULT_POLICY.enabled(name) == CHECKS[name].default_enabled
    assert disabled.with_checks(**{name: True}).enabled(name)
    assert Policy.from_dict(disabled.to_dict()) == disabled


STATIC_CASES = [
    ("known_nodes", f"SELECT (COUNT(*) AS ?n) WHERE {{ {PATTERN} BIND(SHA256(STR(?s)) AS ?hash) }}"),
    ("fixed_graph", "SELECT (COUNT(*) AS ?n) WHERE { GRAPH <urn:private> { ?s a sphn:BilledDiagnosis } }"),
    ("patient_reference", 'SELECT (COUNT(*) AS ?n) WHERE { GRAPH <http://example.org/graph/p1> { ?s a sphn:BilledDiagnosis } }'),
    ("clinical_pattern", "SELECT (COUNT(*) AS ?n) WHERE {}"),
    ("unrestricted_triple", "SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }"),
    ("fixed_subject", "SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { <urn:person> a sphn:BilledDiagnosis } }"),
    ("constant_identifier", 'SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s sphn:hasIdentifier "p1" } }'),
    ("predicate_shape", "SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s sphn:hasQuantity/sphn:hasValue ?v } }"),
    ("predicate_vocabulary", "SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s <urn:outside> ?v } }"),
    ("sensitive_filter", f'SELECT (COUNT(*) AS ?n) WHERE {{ {PATTERN} FILTER(STR(?g) = "p1") }}'),
    ("values", f'SELECT (COUNT(*) AS ?n) WHERE {{ VALUES ?v {{ 1 }} {PATTERN} }}'),
    ("sensitive_bind", f'SELECT (COUNT(*) AS ?n) WHERE {{ BIND(<urn:patient> AS ?g) {PATTERN} }}'),
    ("individual_group", f'SELECT ?g (COUNT(*) AS ?n) WHERE {{ {PATTERN} }} GROUP BY ?g'),
    ("category_group", 'SELECT ?v (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s sphn:hasValue ?v } } GROUP BY ?v'),
    ("sensitive_count", f'SELECT (COUNT(IF(BOUND(?g),1,0)) AS ?n) WHERE {{ {PATTERN} }}'),
    ("numeric_aggregates", 'SELECT (AVG(?v) AS ?n) WHERE { GRAPH ?g { ?s sphn:hasIdentifier ?v } }'),
    ("aggregate_output", f'SELECT ?g WHERE {{ {PATTERN} }}'),
    ("sensitive_output", f'SELECT ?g WHERE {{ {PATTERN} }}'),
    ("select_only", f'ASK WHERE {{ {PATTERN} }}'),
]


@pytest.mark.parametrize("check,body", STATIC_CASES)
def test_static_restrictions_have_independent_switches(check, body):
    query = PREFIX + body
    assert check in {f["check"] for f in validate(query)["findings"]}
    verdict = validate(query, policy=DEFAULT_POLICY.with_checks(**{check: False}))
    assert check not in {f["check"] for f in verdict["findings"]}
    assert verdict["configuration"]["checks"][check] is False


@pytest.mark.parametrize("operator", ["MIN", "MAX", "SAMPLE", "GROUP_CONCAT"])
def test_explicit_operator_switches(operator):
    query = PREFIX + f"SELECT ({operator}(?s) AS ?n) WHERE {{ {PATTERN} }}"
    policy = DEFAULT_POLICY.with_checks(**{"forbid_" + operator.lower(): False})
    assert operator in validate(query)["forbidden_operators"]
    assert operator not in validate(query, policy=policy)["forbidden_operators"]


def test_supported_aggregate_switch_is_separate_from_operator_ban():
    query = PREFIX + f"SELECT (MAX(?s) AS ?n) WHERE {{ {PATTERN} }}"
    policy = DEFAULT_POLICY.with_checks(forbid_max=False)
    assert "supported_aggregates" in {f["check"] for f in validate(query, policy=policy)["findings"]}
    policy = policy.with_checks(supported_aggregates=False)
    assert "supported_aggregates" not in {f["check"] for f in validate(query, policy=policy)["findings"]}


def test_query_limit_is_configurable_and_switchable():
    policy = replace(DEFAULT_POLICY, max_query_chars=10)
    assert not validate(COUNT, policy=policy)["is_compliant"]
    assert validate(COUNT, policy=policy.with_checks(query_length=False))["is_compliant"]


def test_disabled_analyses_are_not_computed(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Analisi disattivata eseguita")
    monkeypatch.setattr("sparql_analyzer.analysis.numeric_variables", forbidden)
    monkeypatch.setattr(QueryAnalysis, "propagate", forbidden)
    policy = DEFAULT_POLICY.with_checks(numeric_analysis=False, sensitivity_analysis=False, aggregate_analysis=False)
    assert validate(COUNT, policy=policy)["is_compliant"]


def test_ast_algebra_and_scope_analysis_can_be_disabled(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Analisi disattivata eseguita")
    monkeypatch.setattr("sparql_analyzer.parser.to_tree", forbidden)
    monkeypatch.setattr("sparql_analyzer.parser.isolate_subquery_scopes", forbidden)
    policy = DEFAULT_POLICY.with_checks(syntax_analysis=False, algebra_analysis=False, scope_analysis=False)
    syntax, tree, prepared = analyze(COUNT, policy=policy)
    assert syntax == tree == {}
    assert prepared.algebra.name == "SelectQuery"


def test_dependency_changes_are_explicit_in_effective_configuration():
    policy = DEFAULT_POLICY.with_checks(support_analysis=False)
    assert not policy.enabled("runtime_cohort")
    assert not policy.enabled("result_consistency")
    assert not policy.enabled("control_analysis")
    assert policy.with_checks(runtime_cohort=True).enabled("support_analysis")
    with pytest.raises(ValueError, match="contraddittoria"):
        DEFAULT_POLICY.with_checks(support_analysis=False, runtime_cohort=True)


@pytest.mark.parametrize("query", [COUNT, NESTED])
def test_cohort_toggle_changes_execution_in_both_engines(query):
    dataset = complex_cohort()
    with pytest.raises(ResultBlocked, match="Coorte"):
        execute_checked(dataset, query, min_patients=9)
    policy = replace(DEFAULT_POLICY.with_checks(runtime_cohort=False), min_patients=9)
    assert execute_checked(dataset, query, policy=policy)


@pytest.mark.parametrize("query", [COUNT, NESTED])
def test_work_limit_toggle_changes_execution_in_both_engines(query):
    dataset = complex_cohort()
    with pytest.raises(ResultBlocked, match="Limite"):
        execute_checked(dataset, query, max_support_rows=1)
    assert execute_checked(dataset, query, policy=DEFAULT_POLICY.with_checks(runtime_work_limit=False), max_support_rows=1)


@pytest.mark.parametrize("query", [COUNT, NESTED])
def test_graph_namespace_toggle_changes_execution_in_both_engines(query):
    dataset = complex_cohort()
    dataset.graph(URIRef("urn:foreign")).add((URIRef("urn:record"), RDF.type, SPHN.BilledDiagnosis))
    with pytest.raises(ResultBlocked, match="autorizzato"):
        execute_checked(dataset, query)
    assert execute_checked(dataset, query, policy=DEFAULT_POLICY.with_checks(runtime_graph_scope=False))


def test_raw_execution_does_not_run_support_evaluators(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Valutatore di supporto eseguito")
    monkeypatch.setattr("sparql_analyzer.flat.execute_flat", forbidden)
    monkeypatch.setattr("sparql_analyzer.nested.execute_nested", forbidden)
    policy = DEFAULT_POLICY.with_checks(support_analysis=False)
    assert execute_checked(generate(), COUNT, policy=policy)


def test_all_checks_off_allows_raw_individual_select():
    policy = Policy(enabled_checks=frozenset())
    query = PREFIX + "SELECT ?id WHERE { GRAPH ?g { ?s sphn:hasIdentifier ?id } }"
    assert validate(query, policy=policy)["is_compliant"]
    result = execute_checked(generate(), query, policy=policy)
    assert result["head"]["vars"] == ["id"]
    assert not validate(query)["is_compliant"]


def test_all_checks_off_allows_ask_without_numeric_json_contract():
    result = execute_checked(generate(), PREFIX + f"ASK {{ {PATTERN} }}", policy=Policy(enabled_checks=frozenset()))
    assert result["boolean"] is True


def test_configuration_rejects_typos_and_invalid_values():
    for value in ({"checks": {"typo": False}}, {"checks": {"runtime_cohort": 0}},
                  {"limits": {"min_patients": True}}, {"limits": {"typo": 10}},
                  {"unexpected": True}):
        with pytest.raises(ValueError):
            Policy.from_dict(value)


def test_policy_can_be_loaded_from_partial_json():
    policy = Policy.from_dict(json.loads('{"checks":{"runtime_cohort":false},"limits":{"min_patients":10}}'))
    assert policy.min_patients == 10
    assert not policy.enabled("runtime_cohort")
    assert policy.enabled("sensitive_output")


def test_result_restrictions_are_independent():
    payload = {"head": {"vars": ["n"]}, "results": {"bindings": [
        {"n": {"type": "literal", "datatype": "http://www.w3.org/2001/XMLSchema#integer", "value": "5"}}
    ]}}
    payload["debug"] = "extra"
    with pytest.raises(ResultBlocked):
        check_payload(payload, ["n"])
    check_payload(payload, ["n"], policy=DEFAULT_POLICY.with_checks(result_metadata=False))
    payload.pop("debug")
    payload["results"]["bindings"] *= 2
    with pytest.raises(ResultBlocked):
        check_payload(payload, ["n"])
    check_payload(payload, ["n"], policy=DEFAULT_POLICY.with_checks(result_single_row=False))


def test_count_finite_format_and_bound_switches():
    integer = {"type": "literal", "datatype": "http://www.w3.org/2001/XMLSchema#integer", "value": "-1"}
    with pytest.raises(ResultBlocked):
        number(integer, count=True)
    assert number(integer, count=True, policy=DEFAULT_POLICY.with_checks(count_format=False)) == -1
    floating = {**integer, "datatype": "http://www.w3.org/2001/XMLSchema#double", "value": "NaN"}
    with pytest.raises(ResultBlocked):
        number(floating)
    assert number(floating, policy=DEFAULT_POLICY.with_checks(finite_numbers=False)).is_nan()
    scientific = {**integer, "value": "1e3"}
    with pytest.raises(ResultBlocked):
        number(scientific)
    assert number(scientific, policy=DEFAULT_POLICY.with_checks(numeric_format=False)) == 1000
    large = {**floating, "value": "1e1001"}
    with pytest.raises(ResultBlocked):
        number(large)
    assert number(large, policy=DEFAULT_POLICY.with_checks(numeric_bounds=False)) == 10 ** 1001


def test_runtime_aggregate_switch_allows_numeric_min_when_other_bans_are_disabled():
    query = PREFIX + "SELECT (MIN(?v) AS ?n) WHERE { GRAPH ?g { ?q sphn:hasValue ?v } }"
    policy = DEFAULT_POLICY.with_checks(forbid_min=False, supported_aggregates=False)
    with pytest.raises(ResultBlocked, match="Aggregazione"):
        execute_checked(complex_cohort(), query, policy=policy)
    result = execute_checked(complex_cohort(), query, policy=policy.with_checks(runtime_aggregates=False))
    assert result["results"]["bindings"][0]["n"]["value"] == "0"


def test_distinct_star_switch_uses_real_row_semantics():
    query = PREFIX + f"SELECT (COUNT(DISTINCT *) AS ?n) WHERE {{ {PATTERN} }}"
    with pytest.raises(ResultBlocked, match="DISTINCT"):
        execute_checked(complex_cohort(), query)
    result = execute_checked(complex_cohort(), query, policy=DEFAULT_POLICY.with_checks(runtime_distinct_star=False))
    assert result["results"]["bindings"][0]["n"]["value"] == "8"


def test_single_graph_switch_allows_multiple_graph_variables():
    query = PREFIX + f"SELECT (COUNT(*) AS ?n) WHERE {{ {PATTERN} GRAPH ?other {{ ?x a sphn:BilledDiagnosis }} }}"
    with pytest.raises(ResultBlocked, match="Struttura"):
        execute_checked(complex_cohort(), query)
    result = execute_checked(complex_cohort(), query, policy=DEFAULT_POLICY.with_checks(runtime_single_graph=False))
    assert result["results"]["bindings"][0]["n"]["value"] == "64"


def test_global_group_and_single_row_contract_are_independent():
    query = PREFIX + f"SELECT (COUNT(*) AS ?n) WHERE {{ {PATTERN} }} GROUP BY ?g"
    policy = DEFAULT_POLICY.with_checks(individual_group=False, runtime_cohort=False)
    with pytest.raises(ResultBlocked):
        execute_checked(complex_cohort(), query, policy=policy)
    policy = policy.with_checks(runtime_global_group=False, result_single_row=False)
    result = execute_checked(complex_cohort(), query, policy=policy)
    assert len(result["results"]["bindings"]) == 8


@pytest.mark.parametrize("query", [COUNT, NESTED])
def test_consistency_toggle_does_not_change_numeric_and_shape_guards(monkeypatch, query):
    dataset = complex_cohort()
    original = dataset.query
    calls = 0

    def tampered(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 2:
            payload = json.loads(result.serialize(format="json"))
            column = payload["head"]["vars"][0]
            payload["results"]["bindings"][0][column]["value"] = "9999"
            return SimpleNamespace(serialize=lambda **kwargs: json.dumps(payload))
        return result

    monkeypatch.setattr(dataset, "query", tampered)
    with pytest.raises(ResultBlocked, match="incoerente"):
        execute_checked(dataset, query)
    calls = 0
    assert execute_checked(dataset, query, policy=DEFAULT_POLICY.with_checks(result_consistency=False))


def test_control_analysis_and_its_threshold_are_switchable():
    query = PREFIX + """SELECT (COUNT(*) AS ?n) WHERE {
      { SELECT (AVG(?v) AS ?secret) WHERE {
          GRAPH ?private { ?q a sphn:OncologyDiagnosis ; sphn:hasValue ?v }
      } }
      GRAPH ?g { ?dx a sphn:BilledDiagnosis }
      FILTER(?secret > 0)
    }"""
    with pytest.raises(ResultBlocked, match="Coorte"):
        execute_checked(complex_cohort(), query)
    for policy in (DEFAULT_POLICY.with_checks(runtime_control_cohort=False),
                   DEFAULT_POLICY.with_checks(control_analysis=False)):
        assert execute_checked(complex_cohort(), query, policy=policy)


def test_cli_lists_effective_checks(monkeypatch, capsys):
    from sparql_analyzer.cli import main
    monkeypatch.setattr("sys.argv", ["compliance", "--list-checks", "--disable", "numeric_analysis"])
    assert main() == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed.keys() == CHECKS.keys()
    assert listed["numeric_analysis"]["enabled"] is False
    assert listed["numeric_aggregates"]["enabled"] is False
    assert listed["runtime_expressions"]["enabled"] is False


def test_cli_reads_policy_and_applies_overrides(tmp_path, monkeypatch, capsys):
    from sparql_analyzer.cli import main
    query_path, policy_path = tmp_path / "query.rq", tmp_path / "policy.json"
    query_path.write_text(COUNT, encoding="utf-8")
    policy_path.write_text('{"checks":{"runtime_cohort":false}}', encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["compliance", str(query_path), "--policy", str(policy_path),
                                   "--enable", "runtime_cohort", "--disable", "forbid_min"])
    assert main() == 0
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["configuration"]["checks"]["runtime_cohort"] is True
    assert verdict["configuration"]["checks"]["forbid_min"] is False


def test_shipped_policies_and_catalog_match_registry():
    root = Path(__file__).resolve().parents[1]
    for name, expected in (("default", DEFAULT_POLICY), ("hardened", Policy.hardened()), ("unrestricted", Policy(enabled_checks=frozenset()))):
        value = json.loads((root / "policies" / (name + ".json")).read_text())
        assert Policy.from_dict(value) == expected
        assert value["checks"].keys() == CHECKS.keys()
    catalog = (root / "docs" / "policy-checks.md").read_text(encoding="utf-8")
    assert all(f"`{name}`" in catalog for name in CHECKS)
