"""Fixture strutturale fittizia per attaccare la provenienza degli aggregati."""

from rdflib import Dataset, Literal, RDF, URIRef

from tools.generate_synthetic_data import SPHN, SYN


def complex_cohort():
    dataset = Dataset()
    for i in range(8):
        graph = dataset.graph(URIRef(f"http://example.org/graph/complex-{i}"))
        person, case = SYN[f"complex-person-{i}"], SYN[f"complex-case-{i}"]
        lab, quantity = SYN[f"complex-lab-{i}"], SYN[f"complex-quantity-{i}"]
        age, marker = SYN[f"complex-age-{i}"], SYN[f"complex-marker-{i}"]
        diagnosis = SYN[f"complex-diagnosis-{i}"]
        for triple in [
            (person, RDF.type, SPHN.SubjectPseudoIdentifier),
            (person, SPHN.hasIdentifier, Literal(90000 + i)),
            (diagnosis, RDF.type, SPHN.BilledDiagnosis),
            (diagnosis, SPHN.hasAdministrativeCase, case),
            (diagnosis, SPHN.hasSubjectPseudoIdentifier, person),
            (lab, RDF.type, SPHN.LabTestEvent),
            (lab, SPHN.hasAdministrativeCase, case),
            (lab, SPHN.hasSubjectPseudoIdentifier, person),
            (lab, SPHN.hasQuantity, quantity),
            (quantity, SPHN.hasValue, Literal(1000 + i)),
            (age, RDF.type, SPHN.Age),
            (age, SPHN.hasSubjectPseudoIdentifier, person),
            (age, SPHN.hasQuantity, marker),
            (marker, SPHN.hasValue, Literal(i)),
        ]:
            graph.add(triple)
        if i == 0:
            graph.add((SYN["complex-rare"], RDF.type, SPHN.OncologyDiagnosis))
            graph.add((SYN["complex-rare"], SPHN.hasValue, Literal(4242)))
    dataset.default_context.add((SYN["complex-default-secret"], RDF.type, SPHN.Quantity))
    dataset.default_context.add((SYN["complex-default-secret"], SPHN.hasValue, Literal(7777)))
    return dataset
