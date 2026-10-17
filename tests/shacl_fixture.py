"""Dati dedicati alle shape di tests/shacl, separati dalle fixture privacy."""

from pathlib import Path
from rdflib import Dataset, Graph, Literal, Namespace, RDF, URIRef
from sparql_analyzer import ShaclContext

SPHN = Namespace("https://biomedit.ch/rdf/sphn-schema/sphn#")
EX = Namespace("urn:shacl-test:")
SHAPES = Path(__file__).parent / "shacl" / "shapes.ttl"
PREFIX = f"PREFIX sphn: <{SPHN}>\n"
COUNT = PREFIX + "SELECT (COUNT(DISTINCT ?g) AS ?n) WHERE { GRAPH ?g { ?d a sphn:BilledDiagnosis } }"


def cohort():
    dataset = Dataset()
    for i in range(5):
        graph = dataset.graph(URIRef(f"http://example.org/graph/shacl-{i}"))
        dx, person, source = EX[f"diagnosis-{i}"], EX[f"person-{i}"], EX[f"source-{i}"]
        for triple in (
            (dx, RDF.type, SPHN.BilledDiagnosis),
            (dx, SPHN.hasSubjectPseudoIdentifier, person),
            (dx, SPHN.hasSourceSystem, source),
            (dx, SPHN.hasCode, EX[f"code-{i}"]),
            (source, RDF.type, SPHN.SourceSystem),
            (person, RDF.type, SPHN.SubjectPseudoIdentifier),
            (person, SPHN.hasIdentifier, Literal(f"SYNTH-{i}")),
        ):
            graph.add(triple)
    return dataset


def shapes():
    return Graph().parse(SHAPES, format="turtle")


def shacl_context():
    return ShaclContext.from_files(SHAPES, inference="none")
