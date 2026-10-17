"""Small clinical fixtures and independent arithmetic oracles for EXISTING queries.

No SPARQL execution is used to compute the expected answers. These synthetic
graphs exercise joins, OPTIONAL, dates, ranges, UNION, MINUS and DISTINCT.
"""
import random

from rdflib import Dataset, Literal, RDF, URIRef, XSD

from tools.generate_synthetic_data import SPHN, SYN


def result(**counts):
    return {"head": {"vars": list(counts)}, "results": {"bindings": [{
        key: {"type": "literal", "datatype": str(XSD.integer), "value": str(value)}
        for key, value in counts.items()
    }]}}


def generate(patients=18, seed=42):
    if patients < 18:
        raise ValueError("At least 18 patients are needed for all positive cohort checks")
    rng = random.Random(seed)
    diagnosis_patients = set(range(patients * 2 // 3))
    lab_counts = {i: (i % 3 + 1 if i % 4 else 0) for i in range(patients)}
    diagnosis_counts = {i: rng.randint(1, 3) for i in sorted(diagnosis_patients)}
    procedure_counts = {i: 1 + i % 2 for i in range(len(diagnosis_patients) - 1)}
    oncology_patients = set(range(patients - 1))
    surgeries = {i for i in range(patients) if i % 5 == 0}
    deaths = {i for i in range(patients) if i % 7 == 0}
    dataset = Dataset()
    for i in range(patients):
        graph = dataset.graph(URIRef(f"http://example.org/graph/workflow-{i}"))
        person, case = SYN[f"person-{i}"], SYN[f"case-{i}"]
        graph.add((person, RDF.type, SPHN.SubjectPseudoIdentifier))
        graph.add((person, SPHN.hasIdentifier, Literal(f"FAKE-{i}")))

        def event(name, kind):
            node = SYN[name]
            graph.add((node, RDF.type, kind))
            graph.add((node, SPHN.hasSubjectPseudoIdentifier, person))
            graph.add((node, SPHN.hasAdministrativeCase, case))
            return node

        for j in range(diagnosis_counts.get(i, 0)):
            node = event(f"dx-{i}-{j}", SPHN.BilledDiagnosis)
            year = "2026" if i == len(diagnosis_patients) - 1 else "2025"
            graph.add((node, SPHN.hasRecordDateTime, Literal(f"{year}-02-01T00:00:00", datatype=XSD.dateTime)))
        for j in range(lab_counts[i]):
            node = event(f"lab-{i}-{j}", SPHN.LabTestEvent)
            year = "2024" if i == 1 else "2025"
            graph.add((node, SPHN.hasDateTime, Literal(f"{year}-02-01T00:00:00", datatype=XSD.dateTime)))
        for j in range(procedure_counts.get(i, 0)):
            node = event(f"proc-{i}-{j}", SPHN.BilledProcedure)
            graph.add((node, SPHN.hasStartDateTime, Literal("2025-02-01T00:00:00", datatype=XSD.dateTime)))
        if i in oncology_patients:
            event(f"onco-{i}", SPHN.OncologyDiagnosis)
        if i in surgeries:
            event(f"surgery-{i}", SPHN.OncologySurgery)
        if i in deaths:
            event(f"death-{i}", SPHN.Death)
        node = event(f"measurement-{i}", SPHN.Measurement)
        quantity = SYN[f"quantity-{i}"]
        graph.add((node, SPHN.hasQuantity, quantity))
        graph.add((quantity, SPHN.hasValue, Literal(150 if i % 2 else 50)))

    lab_patients = {i for i, count in lab_counts.items() if count}
    recent_labs = lab_patients - {1}
    joined = diagnosis_patients & lab_patients
    oracles = {
        "00_compliant": result(patients=len(diagnosis_patients)),
        "12_ok_diagnosis_lab_join": result(patients=len(joined), labs=sum(lab_counts[i] for i in joined)),
        "13_ok_optional_dates": result(patients=len(lab_patients), dated_labs=sum(lab_counts[i] for i in recent_labs)),
        "14_ok_union_cohorts": result(patients=len(diagnosis_patients | recent_labs)),
        "15_ok_minus_treatment": result(patients_without_surgery=len(oncology_patients - surgeries)),
        "16_ok_numeric_range": result(patients=sum(i % 2 == 0 for i in range(patients)), measurements=sum(i % 2 == 0 for i in range(patients))),
        "17_ok_multiple_optional_counts": result(patients=len(diagnosis_patients), labs=sum(lab_counts[i] for i in diagnosis_patients), procedures=sum(procedure_counts.values())),
        "18_ok_arithmetic_counts": result(patients=len(diagnosis_patients), records=sum(diagnosis_counts.values()) + sum(lab_counts[i] for i in diagnosis_patients)),
        "19_ok_having_count": result(patients=len(diagnosis_patients) - 1),
        "20_ok_optional_numeric_filter": result(patients=len(diagnosis_patients), high_measurements=sum(i % 2 == 1 for i in diagnosis_patients)),
        "21_ok_union_minus_join": result(patients=len((oncology_patients | joined) - deaths)),
    }
    return dataset, oracles
