from scripts.benchmark_sphn import read_examples, schema_documents


def test_all_numbered_examples_are_preserved(tmp_path):
    path = tmp_path / "examples.md"
    path.write_text("\n\n".join(f'{i}. Title {i}\n"Question {i}?"\nSELECT * WHERE {{ ?s ?p ?o }}' for i in range(1, 16)))
    rows = read_examples(path)
    assert len(rows) == 15
    assert rows[14]["question"] == "Question 15?"
    assert rows[0]["query"] == "SELECT * WHERE { ?s ?p ?o }"


def test_nested_value_restriction_is_not_a_direct_property(tmp_path):
    path = tmp_path / "schema.ttl"
    path.write_text('''
@prefix sphn: <https://biomedit.ch/rdf/sphn-schema/sphn#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://biomedit.ch/rdf/sphn-schema/sphn> owl:versionIRI <https://biomedit.ch/rdf/sphn-schema/sphn/2026/1> .
sphn:Example a owl:Class ; rdfs:label "Example" ;
 rdfs:subClassOf [a owl:Restriction; owl:onProperty sphn:hasPattern;
 owl:someValuesFrom [a owl:Restriction; owl:onProperty sphn:hasTypeCode]] .
''')
    docs, _ = schema_documents(path)
    assert "hasPattern" in docs[0]["shex"]
    assert "hasTypeCode" not in docs[0]["shex"]
    assert "<n" not in docs[0]["shex"]
