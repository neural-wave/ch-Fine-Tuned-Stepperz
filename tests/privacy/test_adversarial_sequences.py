"""Regressioni delle lacune storiche e dimostrazioni sul profilo predefinito.

Le dimostrazioni di rischio passano quando osservano il rischio, non quando
provano una protezione. I test security_gap verificano invece il profilo hardened.
"""

from tests.paths import FIXTURES


import pytest
from rdflib import Dataset, Literal, RDF, URIRef

from sparql_analyzer.execution.service import ResultBlocked, execute_checked
from sparql_analyzer.compliance import validate
from tools.generate_synthetic_data import SPHN, SYN, generate
from sparql_analyzer.configuration.policy import DEFAULT_POLICY, Policy
from tests.support.privacy_fixture import trusted_context

ROOT = FIXTURES / "adversarial/queries"
# Isola le regressioni privacy da SHACL: le fixture sono intenzionalmente minimali.
PRIVACY_POLICY = Policy.hardened().with_checks(adequacy_shacl=False)


def query(name):
    return (ROOT / (name + ".rq")).read_text(encoding="utf-8")


def count(dataset, name="s01_baseline", *, policy=DEFAULT_POLICY, context=None):
    result = execute_checked(dataset, query(name), min_patients=5, policy=policy, context=context)
    return int(result["results"]["bindings"][0]["patients"]["value"])


@pytest.fixture
def indexed_cohort():
    dataset = generate()
    for graph in dataset.contexts():
        diagnoses = list(graph.subjects(RDF.type, SPHN.BilledDiagnosis))
        if diagnoses:
            index = int(str(graph.identifier).rsplit("-", 1)[1])
            for dx in diagnoses:
                graph.add((dx, SPHN.hasValue, Literal(index)))
    return dataset


@pytest.mark.security_gap
def test_differencing_sequence_is_suppressed(indexed_cohort):
    context, policy = trusted_context(indexed_cohort), PRIVACY_POLICY
    assert count(indexed_cohort, policy=policy, context=context) == 8
    with pytest.raises(ResultBlocked):
        count(indexed_cohort, "s02_exclude_value_zero", policy=policy, context=context)


@pytest.mark.security_gap
def test_temporal_difference_is_suppressed(indexed_cohort):
    context, policy = trusted_context(indexed_cohort), PRIVACY_POLICY
    assert count(indexed_cohort, policy=policy, context=context) == 8
    graph = indexed_cohort.graph(URIRef("http://example.org/graph/synthetic-0000"))
    for dx in list(graph.subjects(RDF.type, SPHN.BilledDiagnosis)):
        graph.remove((dx, RDF.type, SPHN.BilledDiagnosis))
    with pytest.raises(ResultBlocked):
        count(indexed_cohort, policy=policy, context=context)


@pytest.mark.security_gap
def test_duplicate_graphs_do_not_count_as_distinct_patients():
    dataset = Dataset()
    for i in range(5):
        graph = dataset.graph(URIRef(f"http://example.org/graph/copy-{i}"))
        graph.add((SYN[f"copy-diagnosis-{i}"], RDF.type, SPHN.BilledDiagnosis))
        graph.add((SYN[f"copy-diagnosis-{i}"], SPHN.hasSubjectPseudoIdentifier, SYN.one_person))
    with pytest.raises(ResultBlocked):
        count(dataset, policy=PRIVACY_POLICY, context=trusted_context(dataset))


@pytest.mark.security_gap
def test_prefix_is_not_user_authorization(indexed_cohort):
    context = trusted_context(indexed_cohort)
    graph = indexed_cohort.graph(URIRef("http://example.org/graph/other-tenant"))
    graph.add((SYN["other-tenant-diagnosis"], RDF.type, SPHN.BilledDiagnosis))
    with pytest.raises(ResultBlocked):
        count(indexed_cohort, policy=PRIVACY_POLICY, context=context)


@pytest.mark.security_gap
def test_uncorrelated_sensitive_condition_is_suppressed(indexed_cohort):
    indexed_cohort.default_context.add((SYN["private-default-record"], RDF.type, SPHN.OncologyDiagnosis))
    with pytest.raises(ResultBlocked):
        count(indexed_cohort, "s03_uncorrelated_default_graph", policy=PRIVACY_POLICY, context=trusted_context(indexed_cohort))


@pytest.mark.security_gap
def test_backend_error_does_not_escape_with_private_values(indexed_cohort, monkeypatch):
    context = trusted_context(indexed_cohort)
    def failing_backend(*args, **kwargs):
        raise RuntimeError("Backend error: SYNTH-0000@example.invalid")
    monkeypatch.setattr(indexed_cohort, "query", failing_backend)
    with pytest.raises(ResultBlocked) as error:
        count(indexed_cohort, policy=PRIVACY_POLICY, context=context)
    assert "SYNTH-0000" not in str(error.value)


@pytest.mark.risk_demonstration
def test_homogeneity_is_not_hidden_by_threshold():
    dataset = generate(patients=8)
    for i in range(8):
        dataset.graph(URIRef(f"http://example.org/graph/synthetic-{i:04d}")).add(
            (SYN[f"shared-trait-{i}"], RDF.type, SPHN.BilledDiagnosis)
        )
    # Rischio osservato: tutti gli appartenenti alla popolazione hanno la diagnosi.
    assert count(dataset, "s04_population") == count(dataset) == 8


@pytest.mark.risk_demonstration
def test_overlapping_cohorts_are_individually_released(indexed_cohort):
    # Rischio osservato: ogni query supera k, non esiste un controllo dello storico.
    assert [count(indexed_cohort, name) for name in
            ("s01_baseline", "s02_exclude_value_zero", "s05_lower_overlap")] == [8, 7, 7]


@pytest.mark.risk_demonstration
def test_suppressed_complement_is_recoverable(indexed_cohort):
    large = count(indexed_cohort)
    remaining = count(indexed_cohort, "s02_exclude_value_zero")
    singleton = query("s02_exclude_value_zero").replace("?v > 0", "?v = 0")
    with pytest.raises(ResultBlocked, match="Coorte insufficiente"):
        execute_checked(indexed_cohort, singleton)
    # Non e una prova di protezione: il dato soppresso si ricava da due risultati.
    assert large - remaining == 1


@pytest.mark.risk_demonstration
def test_multiple_exact_counts_reconstruct_synthetic_membership(indexed_cohort):
    assert validate(query("s06_reconstruct_sum"))["is_compliant"]
    baseline = count(indexed_cohort)
    membership = [baseline - count(indexed_cohort, f"s07_reconstruction_exclude_{i:02d}") for i in range(12)]
    # Tutti i risultati sono 7 o 8, ma rivelano il vettore di appartenenza.
    # La conoscenza esterna simulata e il collegamento persona <-> valore ?v.
    assert membership == [1] * 8 + [0] * 4
