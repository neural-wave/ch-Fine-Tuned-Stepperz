"""Limiti dimostrabili del prototipo: xfail strict = requisito non soddisfatto.

Le dimostrazioni di rischio passano quando osservano il rischio, non quando
provano una protezione. I test security_gap richiedono invece il blocco futuro.
"""

from pathlib import Path

import pytest
from rdflib import Dataset, Literal, RDF, URIRef

from sparql_analyzer.runtime import ResultBlocked, execute_checked
from sparql_analyzer.compliance import validate
from tests.generate_synthetic_data import SPHN, SYN, generate

ROOT = Path(__file__).parent / "adversarial/queries"


def query(name):
    return (ROOT / (name + ".rq")).read_text(encoding="utf-8")


def count(dataset, name="s01_baseline"):
    result = execute_checked(dataset, query(name), min_patients=5)
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
@pytest.mark.xfail(strict=True, reason="GAP-01: manca una policy delle query multiple")
def test_differencing_sequence_is_suppressed(indexed_cohort):
    assert count(indexed_cohort) == 8
    with pytest.raises(ResultBlocked):
        count(indexed_cohort, "s02_exclude_value_zero")


@pytest.mark.security_gap
@pytest.mark.xfail(strict=True, reason="GAP-02: nessuna protezione dai confronti temporali")
def test_temporal_difference_is_suppressed(indexed_cohort):
    assert count(indexed_cohort) == 8
    graph = indexed_cohort.graph(URIRef("http://example.org/graph/synthetic-0000"))
    for dx in list(graph.subjects(RDF.type, SPHN.BilledDiagnosis)):
        graph.remove((dx, RDF.type, SPHN.BilledDiagnosis))
    with pytest.raises(ResultBlocked):
        count(indexed_cohort)


@pytest.mark.security_gap
@pytest.mark.xfail(strict=True, reason="GAP-03: cinque grafi non provano cinque persone")
def test_duplicate_graphs_do_not_count_as_distinct_patients():
    dataset = Dataset()
    for i in range(5):
        graph = dataset.graph(URIRef(f"http://example.org/graph/copy-{i}"))
        graph.add((SYN[f"copy-diagnosis-{i}"], RDF.type, SPHN.BilledDiagnosis))
        graph.add((SYN[f"copy-diagnosis-{i}"], SPHN.hasSubjectPseudoIdentifier, SYN.one_person))
    with pytest.raises(ResultBlocked):
        count(dataset)


@pytest.mark.security_gap
@pytest.mark.xfail(strict=True, reason="GAP-04: manca il contesto di autorizzazione utente")
def test_prefix_is_not_user_authorization(indexed_cohort):
    graph = indexed_cohort.graph(URIRef("http://example.org/graph/other-tenant"))
    graph.add((SYN["other-tenant-diagnosis"], RDF.type, SPHN.BilledDiagnosis))
    with pytest.raises(ResultBlocked):
        count(indexed_cohort)


@pytest.mark.security_gap
@pytest.mark.xfail(strict=True, reason="GAP-05: condizioni non correlate fuori da GRAPH")
def test_uncorrelated_sensitive_condition_is_suppressed(indexed_cohort):
    indexed_cohort.default_context.add((SYN["private-default-record"], RDF.type, SPHN.OncologyDiagnosis))
    with pytest.raises(ResultBlocked):
        count(indexed_cohort, "s03_uncorrelated_default_graph")


@pytest.mark.security_gap
@pytest.mark.xfail(strict=True, reason="GAP-06: gli errori del backend non sono normalizzati")
def test_backend_error_does_not_escape_with_private_values(indexed_cohort, monkeypatch):
    def failing_backend(*args, **kwargs):
        raise RuntimeError("Backend error: SYNTH-0000@example.invalid")
    monkeypatch.setattr(indexed_cohort, "query", failing_backend)
    with pytest.raises(ResultBlocked) as error:
        count(indexed_cohort)
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
