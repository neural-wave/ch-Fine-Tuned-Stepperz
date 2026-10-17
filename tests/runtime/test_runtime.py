import copy
import json
from types import SimpleNamespace

import pytest
from rdflib import Dataset, RDF, URIRef

from sparql_analyzer.demo import EXAMPLE_QUERY
from sparql_analyzer.execution.service import ResultBlocked, check_payload, execute_checked
from tools.generate_synthetic_data import SPHN, generate


@pytest.fixture
def cohort():
    return generate(patients=12, seed=42)


def test_synthetic_patients_are_reproducible():
    first, second = generate(), generate()
    assert set(first.quads((None, None, None, None))) == set(second.quads((None, None, None, None)))
    assert len(list(first.contexts())) >= 12


def test_cohort_count_approved(cohort):
    result = execute_checked(cohort, EXAMPLE_QUERY)
    assert result["results"]["bindings"][0]["patients"]["value"] == "8"
    assert "SYNTH-" not in str(result)


def test_fixture_roundtrip(tmp_path):
    path = tmp_path / "cohort.trig"
    generate().serialize(destination=str(path), format="trig")
    dataset = Dataset()
    dataset.parse(path, format="trig")
    assert execute_checked(dataset, EXAMPLE_QUERY)["head"]["vars"] == ["patients"]


def test_single_patient_suppressed(cohort):
    query = EXAMPLE_QUERY.replace("BilledDiagnosis", "OncologyDiagnosis")
    with pytest.raises(ResultBlocked, match="Coorte insufficiente"):
        execute_checked(cohort, query)


def test_ten_labs_from_one_patient_are_suppressed(cohort):
    query = EXAMPLE_QUERY.replace("COUNT(DISTINCT ?g)", "COUNT(?diagnosis)").replace("BilledDiagnosis", "LabTestEvent")
    with pytest.raises(ResultBlocked, match="Coorte insufficiente"):
        execute_checked(cohort, query)


def test_each_optional_aggregate_has_its_own_cohort(cohort):
    query = """PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>
    SELECT (COUNT(DISTINCT ?g) AS ?patients) (COUNT(DISTINCT ?lab) AS ?labs)
    WHERE { GRAPH ?g { ?dx a sphn:BilledDiagnosis . OPTIONAL { ?lab a sphn:LabTestEvent } } }
    """
    with pytest.raises(ResultBlocked, match="Coorte insufficiente"):
        execute_checked(cohort, query)


def test_identifiers_blocked_before_execution(cohort, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Una query non conforme non deve essere eseguita")
    monkeypatch.setattr(cohort, "query", forbidden)
    query = """PREFIX sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#>
    SELECT ?id WHERE { GRAPH ?g { ?subject sphn:hasIdentifier ?id } }
    """
    with pytest.raises(ResultBlocked, match="statico"):
        execute_checked(cohort, query)


@pytest.mark.parametrize("cell", [
    {"type": "uri", "value": "urn:synthetic:patient-0000"},
    {"type": "bnode", "value": "patient"},
    {"type": "literal", "value": "SYNTH-0000"},
    {"type": "literal", "value": "synthetic-0000@example.invalid"},
    {"type": "literal", "datatype": "http://www.w3.org/2001/XMLSchema#integer", "value": "-1"},
    {"type": "literal", "datatype": "http://www.w3.org/2001/XMLSchema#integer", "value": "SYNTH-0000"},
    {"type": "literal", "datatype": "http://www.w3.org/2001/XMLSchema#string", "value": "8"},
])
def test_plaintext_and_invalid_types_blocked(cohort, cell):
    payload = execute_checked(cohort, EXAMPLE_QUERY)
    payload["results"]["bindings"][0]["patients"] = cell
    with pytest.raises(ResultBlocked):
        check_payload(payload, ["patients"])


@pytest.mark.parametrize("mutation", ["extra_column", "missing_column", "two_rows", "empty", "metadata"])
def test_unexpected_result_shape_blocked(cohort, mutation):
    payload = execute_checked(cohort, EXAMPLE_QUERY)
    if mutation == "extra_column":
        payload["head"]["vars"].append("id")
    elif mutation == "missing_column":
        payload["results"]["bindings"][0] = {}
    elif mutation == "two_rows":
        payload["results"]["bindings"].append(copy.deepcopy(payload["results"]["bindings"][0]))
    elif mutation == "empty":
        payload["results"]["bindings"] = []
    else:
        payload["debug"] = "SYNTH-0000"
    with pytest.raises(ResultBlocked):
        check_payload(payload, ["patients"])


def test_foreign_graph_blocked(cohort):
    cohort.graph(URIRef("urn:foreign-graph")).add((URIRef("urn:foreign-record"), RDF.type, SPHN.BilledDiagnosis))
    query = EXAMPLE_QUERY[:EXAMPLE_QUERY.index("  FILTER")] + "}"
    with pytest.raises(ResultBlocked, match="autorizzato"):
        execute_checked(cohort, query)


@pytest.mark.parametrize("threshold", [0, 1, True, -1])
def test_invalid_threshold(cohort, threshold):
    with pytest.raises(ValueError):
        execute_checked(cohort, EXAMPLE_QUERY, min_patients=threshold)


def test_support_limit_blocks(cohort):
    with pytest.raises(ResultBlocked, match="Limite"):
        execute_checked(cohort, EXAMPLE_QUERY, max_support_rows=1)


def test_wrong_numeric_value_is_not_released(cohort, monkeypatch):
    original = cohort.query
    calls = 0

    def tampered(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 2:
            payload = json.loads(result.serialize(format="json"))
            payload["results"]["bindings"][0]["patients"]["value"] = "123456789"
            return SimpleNamespace(serialize=lambda **kwargs: json.dumps(payload))
        return result

    monkeypatch.setattr(cohort, "query", tampered)
    with pytest.raises(ResultBlocked, match="incoerente"):
        execute_checked(cohort, EXAMPLE_QUERY)


def test_direct_count_star_approved(cohort):
    query = EXAMPLE_QUERY.replace("COUNT(DISTINCT ?g)", "COUNT(*)")
    assert int(execute_checked(cohort, query)["results"]["bindings"][0]["patients"]["value"]) > 8


def test_arithmetic_projection_on_count_approved(cohort):
    query = EXAMPLE_QUERY.replace("COUNT(DISTINCT ?g)", "(COUNT(DISTINCT ?g) + 1)")
    result = execute_checked(cohort, query)
    assert result["results"]["bindings"][0]["patients"]["value"] == "9"


def test_errors_do_not_echo_sensitive_values(cohort):
    with pytest.raises(ResultBlocked) as error:
        execute_checked(cohort, EXAMPLE_QUERY.replace("BilledDiagnosis", "OncologyDiagnosis"))
    assert "synthetic-0000" not in str(error.value)
