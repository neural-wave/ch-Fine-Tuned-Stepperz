from pathlib import Path

from sparql_agent.sphn_retrieval import SPHN, SphnVoidRetrieval

ROOT = Path(__file__).resolve().parents[1]


def test_range_classes_are_not_rendered_as_fixed_object_values(tmp_path):
    path = tmp_path / "void.ttl"
    path.write_text('''
@prefix void: <http://rdfs.org/ns/void#> .
@prefix ve: <http://ldf.fi/void-ext#> .
@prefix sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<urn:class> void:class sphn:BilledDiagnosis ;
  void:propertyPartition [ void:property sphn:hasCode ;
    void:classPartition [ void:class <urn:coding-system:ICD> ] ] ;
  void:propertyPartition [ void:property sphn:hasRecordDateTime ;
    ve:datatypePartition [ ve:datatype xsd:dateTime ] ] .
''', encoding="utf-8")
    schema = SphnVoidRetrieval(path).classes[0]
    assert "sphn:hasCode { a [ <urn:coding-system:ICD> ] }" in schema["shex"]
    assert "sphn:hasCode [" not in schema["shex"]
    assert "sphn:hasRecordDateTime xsd:dateTime" in schema["shex"]
    assert schema["declared_value_types"][SPHN + "hasCode"] == ["urn:coding-system:ICD"]
    assert "not fixed data values" in schema["schema_notes"]


def test_void_retrieves_only_sphn_schema_and_derived_examples():
    retrieval = SphnVoidRetrieval(ROOT / "metadata/sphn-schema-void.ttl")
    classes = retrieval.search_sparql_classes(
        ["OncologyDiagnosis", "OncologySurgery", "RadiotherapyProcedure"]
    )["classes_schemas"]
    assert classes
    assert all(row["iri"].startswith(SPHN) for row in classes)
    assert any("hasIncidenceDateTime" in row["shex"] for row in classes)

    examples = retrieval.search_sparql_examples(
        "After a cancer diagnosis, compare surgery and radiotherapy treatments", []
    )["query_examples"]
    assert {"sphn:OncologyDiagnosis", "sphn:OncologySurgery", "sphn:RadiotherapyProcedure"} <= {
        term for row in examples for term in (
            "sphn:OncologyDiagnosis", "sphn:OncologySurgery", "sphn:RadiotherapyProcedure"
        ) if term in row["query"]
    }
    assert all(row["source"] == "void_schema_aggregate_pattern" for row in examples)
    assert all("COUNT(DISTINCT ?record)" in row["query"] for row in examples)
    assert all("uniprot" not in str(row).lower() for row in examples + classes)


def test_reference_answers_are_not_read_for_void_backend(monkeypatch):
    reference = ROOT / "data/sphn/queries-example.md"
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        if path == reference:
            raise AssertionError("Reference answers accessed during retrieval")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    retrieval = SphnVoidRetrieval(ROOT / "metadata/sphn-schema-void.ttl")
    assert retrieval.search_sparql_examples("cancer surgery", [])["query_examples"]


def test_exact_class_hints_do_not_spend_context_on_similar_classes():
    retrieval = SphnVoidRetrieval(ROOT / "metadata/sphn-schema-void.ttl")
    hints = ["BilledDiagnosis", "sphn:SubjectPseudoIdentifier", SPHN + "AdministrativeSex"]
    rows = retrieval.search_sparql_classes(hints)["classes_schemas"]
    assert [row["iri"] for row in rows] == [SPHN + "BilledDiagnosis", SPHN + "SubjectPseudoIdentifier", SPHN + "AdministrativeSex"]
    examples = retrieval.search_sparql_examples("BilledDiagnosis", [])["query_examples"]
    assert all(row["class_iri"].startswith(SPHN) for row in examples)
