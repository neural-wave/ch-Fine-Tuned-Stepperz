"""Contesto fidato SOLO per fixture sintetiche di cui conosciamo le identita."""

from rdflib import RDF

from sparql_analyzer.privacy import ExecutionContext, ReleaseHistory
from tests.generate_synthetic_data import SPHN


def trusted_context(dataset, *, history=None, dataset_id="synthetic-test", principal_id="test-user"):
    graphs = list(dataset.contexts())
    patients = {}
    for graph in graphs:
        if not str(graph.identifier).startswith("http://example.org/graph/"):
            continue
        ids = set(graph.objects(None, SPHN.hasSubjectPseudoIdentifier))
        if not ids:
            ids = set(graph.subjects(RDF.type, SPHN.SubjectPseudoIdentifier))
        if len(ids) == 1:
            patients[str(graph.identifier)] = str(next(iter(ids)))
        elif len(graph):
            # Le fixture prive di identificatori rappresentano un paziente per grafo.
            patients[str(graph.identifier)] = "fixture-person:" + str(graph.identifier)
    return ExecutionContext(principal_id, dataset_id,
        allowed_graphs=frozenset(str(g.identifier) for g in graphs if len(g)),
        graph_patients=patients, history=history if history is not None else ReleaseHistory())
