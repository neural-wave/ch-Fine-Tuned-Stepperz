from pathlib import Path

from sparql_agent.sphn_retrieval import SPHN, SphnVoidRetrieval

ROOT = Path(__file__).resolve().parents[1]


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
